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
    - Generate all required source files via LLM and write them to workspace/
    - Optionally run setup_commands to generate binary/scaffolded files
      (SQLite databases, npm/npx scaffolding, compiled assets, etc.)
    - Publish CODE_WRITTEN on success, SYSTEM_ERROR on failure

    Does NOT orchestrate, plan, review, or run validation commands.
    """

    SYSTEM_PROMPT = """You are Zed, an expert software engineer inside a multi-agent system.

Your job is to write the code needed to complete the given task AND to run any necessary setup commands to generate files that cannot be written as plain text.

Rules for files:
- Produce ONLY working, production-quality code. No placeholders, no stubs, no ellipsis.
- Every file must be fully implemented — no "TODO", no "pass" where logic is expected, no empty function bodies.
- NEVER write comments like "# Your code here", "# TODO", "# implement this". Write the actual implementation.
- NEVER import from fictional modules. Imports must reference real files listed in the project context.
- When writing tests: every test method must contain real assertions against real code.
- When writing JS: use only vanilla JS or libraries explicitly mentioned in the task.
- When writing HTML for a frontend-only task: handle all logic client-side.
- Respect the output paths specified in the task ('outputs').
- Respect the architecture style specified in the vision (Hexagonal, MVC, Clean, etc.).
- If correction feedback is provided, fix every listed issue before submitting.

Rules for setup_commands:
- Use setup_commands when the task requires generating files that cannot be written as text:
  * Project scaffolding: npx create-next-app, npm init, django-admin startproject, etc.
  * Database initialization: running a Python init script, flask db upgrade, etc.
  * Binary asset generation: npm run build, webpack, etc.
  * Dependency installation: npm install, pip install -r requirements.txt, etc.
- Commands run sequentially in the workspace directory. Each must succeed before the next runs.
- Prefer a single compound command (with &&) over many separate commands when possible.
- Do NOT use setup_commands for tasks that only require writing text files.
- setup_commands output is NOT reviewed by Earl — only the resulting files are.
- CRITICAL: The task prompt includes an "Execution environment" section listing which tools are installed.
  You MUST only use tools marked ✓ Available. Never use a tool marked ✗ Missing.
  Common substitutions when tools are missing:
  * sqlite3 CLI missing → write a Python init_db.py using the built-in sqlite3 module, run: python3 init_db.py
  * npm/npx missing → write all project files manually (package.json, src/, etc.) instead of scaffolding
  * No tool available → write everything as plain files, no setup_commands needed

Respond ONLY with a valid JSON object in this exact format:
{
  "files": [
    {
      "path": "relative/path/from/workspace/file.py",
      "content": "full file content here"
    }
  ],
  "setup_commands": [],
  "summary": "One-sentence description of what was implemented"
}

- 'path' is relative to workspace/ (do not include 'workspace/' prefix)
- 'setup_commands' is a list of shell command strings, or an empty list
- 'files' can be empty if the task is pure scaffolding (e.g. npx create-next-app creates all files)"""

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
        Optionally runs setup_commands for binary/scaffolded file generation.
        Returns the list of file paths written to workspace/.
        """
        task = self._get_task(task_id)
        if not task:
            raise ValueError(f"Zed: task '{task_id}' not found in backlog.")

        self.update_status("busy", current_task=task_id, last_action="IMPLEMENTING")
        cycle = self.get_current_cycle()

        user_prompt = self._build_prompt(task)
        response = self.llm.ask_json(self.SYSTEM_PROMPT, user_prompt)

        files          = response.get("files", [])
        setup_commands = response.get("setup_commands", [])
        summary        = response.get("summary", "")

        if not files and not setup_commands:
            self._publish_error(task_id, "LLM returned no files and no setup_commands.", cycle)
            raise ValueError(f"Zed: no output generated for task '{task_id}'.")

        # Write text files
        written_paths = []
        for file_entry in files:
            rel_path = file_entry["path"]
            content  = file_entry["content"]
            self.executor.write_file(rel_path, content)
            written_paths.append(rel_path)

        # Run setup commands (scaffolding, db init, binary generation…)
        setup_log = []
        if setup_commands:
            self.update_status("busy", current_task=task_id, last_action="SETUP_COMMANDS")
            for cmd in setup_commands:
                result = self.executor.run_command(cmd, timeout=300)
                entry  = {"command": cmd, "success": result["success"]}
                if result["stdout"]:
                    entry["stdout"] = result["stdout"][:800]
                if result["stderr"]:
                    entry["stderr"] = result["stderr"][:800]
                setup_log.append(entry)

                if not result["success"]:
                    error_msg = (
                        f"Setup command failed: {cmd}\n"
                        f"stderr: {result['stderr'][:500]}\n"
                        f"stdout: {result['stdout'][:500]}"
                    )
                    self._publish_error(task_id, error_msg, cycle)
                    raise ValueError(f"Zed: {error_msg}")

        self.event_bus.publish(
            agent="Zed",
            event_type="CODE_WRITTEN",
            target=task_id,
            payload={
                "task_id":        task_id,
                "files":          written_paths,
                "setup_commands": [e["command"] for e in setup_log],
                "summary":        summary,
            },
            current_cycle=cycle
        )

        self.update_status("idle", current_task=None, last_action=f"CODE_WRITTEN:{task_id}")
        return written_paths

    # ==========================================
    # PRIVATE HELPERS
    # ==========================================

    def _get_task(self, task_id: str) -> Dict[str, Any] | None:
        backlog = self.tasks.load_state()["backlog"]
        return next((t for t in backlog if t["id"] == task_id), None)

    def _build_prompt(self, task: Dict[str, Any]) -> str:
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
            clean = output.replace("workspace/", "", 1) if output.startswith("workspace/") else output
            lines.append(f"  - {clean}")

        if task.get("tags"):
            lines.append(f"\nTags: {', '.join(task['tags'])}")

        if task.get("run_command"):
            lines.append(f"\nValidation command (run by Chris after review): {task['run_command']}")

        # Vision architecture + quality constraints
        try:
            from core.file_utils import load_json
            vision = load_json("vision/vision.json")
            arch   = vision.get("architecture", {}).get("style", "")
            if arch:
                lines.append(f"\nArchitecture style: {arch}")
            quality = vision.get("quality_constraints", {})
            if quality.get("tests_required"):
                lines.append("Tests are required (write them in a separate test file if not already in outputs).")
        except Exception:
            pass

        # Execution environment — which tools are available for setup_commands
        try:
            lines.append(f"\n{self.executor.tools_summary()}")
        except Exception:
            pass

        # Existing workspace files — for correct imports and references
        try:
            existing = self.executor.list_files()
            if existing:
                lines.append(f"\nExisting files in workspace/ (use for imports and references):")
                for f in existing:
                    lines.append(f"  - {f}")
                # Include content of small code files for symbol awareness
                for f in existing:
                    if f.endswith((".py", ".js", ".ts")) and not f.startswith("test"):
                        try:
                            content = self.executor.read_file(f)
                            if len(content) < 3000:
                                lines.append(f"\n--- workspace/{f} ---")
                                lines.append(content)
                        except Exception:
                            pass
        except Exception:
            pass

        # Forward-dependency awareness
        try:
            all_tasks  = self.tasks.load_state()["backlog"]
            dependents = [t for t in all_tasks if task["id"] in t.get("dependencies", [])]
            if dependents:
                lines.append(
                    f"\nThe following tasks depend on this one. "
                    f"Your code MUST reference/import/link them correctly:"
                )
                for dep in dependents:
                    for output in dep.get("outputs", []):
                        clean = output.replace("workspace/", "", 1) if output.startswith("workspace/") else output
                        lines.append(f"  - {clean}  ({dep['id']}: {dep['title']})")
        except Exception:
            pass

        # Correction feedback from a previous failed review
        feedback = task.get("correction_feedback", "").strip()
        if feedback:
            lines.append(f"\n⚠ CORRECTION REQUIRED — previous attempt was rejected.")
            lines.append("You MUST fix all of the following issues before submitting:")
            lines.append(feedback)

        return "\n".join(lines)

    def _publish_error(self, task_id: str, reason: str, cycle: int):
        self.event_bus.publish(
            agent="Zed",
            event_type="SYSTEM_ERROR",
            target=task_id,
            payload={"error": reason, "task_id": task_id},
            current_cycle=cycle
        )
        self.update_status("idle", current_task=None, last_action="ERROR")
