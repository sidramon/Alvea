import json
import os
from typing import Dict, Any, List

from agents.base_agent import BaseAgent
from core.event_bus import EventBus
from core.task_manager import TaskManager
from core.executor_runtime import ExecutorRuntime
from core.llm_client import LocalLLM


class Zed(BaseAgent):
    """
    Coder. Writes the code required to complete a task.

    Responsibilities:
    - Read the task definition from tasks.json
    - Generate all required source files via LLM
    - Write files to workspace/ via ExecutorRuntime
    - Publish CODE_WRITTEN on success, SYSTEM_ERROR on failure

    Does NOT orchestrate, plan, review, or run commands.
    """

    SYSTEM_PROMPT = """You are Zed, an expert software engineer inside a multi-agent system.

Your ONLY job is to write the code needed to complete the given task.

Rules:
- Produce ONLY working, production-quality code. No placeholders.
- Respect the output paths specified in the task ('outputs').
- Each file must be complete and self-contained where possible.
- Follow clean architecture principles: single responsibility, no leaking layers.
- Do NOT add tests — Earl handles review and tests are handled separately.

Respond ONLY with a valid JSON object in this exact format:
{
  "files": [
    {
      "path": "relative/path/from/workspace/file.py",
      "content": "full file content here"
    }
  ],
  "summary": "One-sentence description of what was implemented"
}

The 'path' field must be relative to workspace/ (do not include 'workspace/' prefix)."""

    def __init__(
        self,
        event_bus: EventBus,
        task_manager: TaskManager,
        executor: ExecutorRuntime,
        llm: LocalLLM,
        state_file: str = "runtime/state.json"
    ):
        super().__init__("Zed", event_bus, state_file)
        self.tasks = task_manager
        self.executor = executor
        self.llm = llm

    # ==========================================
    # MAIN ACTION
    # ==========================================

    def implement_task(self, task_id: str) -> List[str]:
        """
        Generates and writes code for the given task.
        Returns the list of file paths written to workspace/.
        """
        task = self._get_task(task_id)
        if not task:
            raise ValueError(f"Zed: task '{task_id}' not found in backlog.")

        self.update_status("busy", current_task=task_id, last_action="IMPLEMENTING")
        cycle = self.get_current_cycle()

        user_prompt = self._build_prompt(task)
        response = self.llm.ask_json(self.SYSTEM_PROMPT, user_prompt)

        files = response.get("files", [])
        summary = response.get("summary", "")

        if not files:
            self._publish_error(task_id, "LLM returned no files.", cycle)
            raise ValueError(f"Zed: no files generated for task '{task_id}'.")

        written_paths = []
        for file_entry in files:
            rel_path = file_entry["path"]
            content = file_entry["content"]
            self.executor.write_file(rel_path, content)
            written_paths.append(rel_path)

        self.event_bus.publish(
            agent="Zed",
            event_type="CODE_WRITTEN",
            target=task_id,
            payload={
                "task_id": task_id,
                "files": written_paths,
                "summary": summary
            },
            current_cycle=cycle
        )

        self.update_status("idle", current_task=None, last_action=f"CODE_WRITTEN:{task_id}")
        return written_paths

    # ==========================================
    # PRIVATE HELPERS
    # ==========================================

    def _get_task(self, task_id: str) -> Dict[str, Any] | None:
        """Retrieves a task from the backlog by ID."""
        backlog = self.tasks.load_state()["backlog"]
        return next((t for t in backlog if t["id"] == task_id), None)

    def _build_prompt(self, task: Dict[str, Any]) -> str:
        """Constructs the user prompt for the LLM from the task definition."""
        lines = [
            f"Task ID: {task['id']}",
            f"Title: {task['title']}",
            f"Type: {task['type']}",
            f"Layer: {task['layer']}",
            f"",
            f"Description:",
            task['description'],
            f"",
            f"Expected output files (relative to workspace/):",
        ]
        for output in task.get("outputs", []):
            # Strip 'workspace/' prefix if included in the task definition
            clean = output.replace("workspace/", "", 1) if output.startswith("workspace/") else output
            lines.append(f"  - {clean}")

        if task.get("tags"):
            lines.append(f"\nTags: {', '.join(task['tags'])}")

        return "\n".join(lines)

    def _publish_error(self, task_id: str, reason: str, cycle: int):
        """Publishes a SYSTEM_ERROR event and resets agent status."""
        self.event_bus.publish(
            agent="Zed",
            event_type="SYSTEM_ERROR",
            target=task_id,
            payload={"error": reason, "task_id": task_id},
            current_cycle=cycle
        )
        self.update_status("idle", current_task=None, last_action="ERROR")
