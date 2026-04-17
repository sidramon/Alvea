import os
import json
from typing import Dict, Any, List

from agents.base_agent import BaseAgent
from core.event_bus import EventBus
from core.task_manager import TaskManager
from core.executor_runtime import ExecutorRuntime
from core.llm_client import LocalLLM
from core.file_utils import load_json


class Earl(BaseAgent):
    """
    Reviewer. Validates code produced by Zed against quality and vision constraints.

    Responsibilities:
    - Read all files produced by Zed from workspace/
    - Evaluate them against vision.json quality constraints
    - Publish REVIEW_PASSED (code is correct) or REVIEW_FAILED (issues found)
    - Provide structured feedback on failures so Zed can correct

    Does NOT orchestrate, plan, write code, or execute commands.
    """

    SYSTEM_PROMPT = """You are Earl, a strict senior code reviewer inside a multi-agent system.

Your ONLY job is to review code produced by Zed and determine if it meets all quality constraints.

Evaluation criteria (ALL must pass — any single failure = passed: false):
1. Correctness: Does the code logically accomplish what the task describes?
2. Completeness: Are all expected output files present and fully implemented?
3. Architecture: Does the code respect single responsibility and clean separation of concerns?
4. Quality: No dead code, no obvious bugs, no hardcoded secrets, no bare except clauses.
5. Conformance: Does the code respect any constraints declared in vision_constraints?
6. No placeholders: REJECT immediately if any file contains:
   - Empty function or method bodies (only a comment or only "pass")
   - "# Your code here", "# TODO", "# implement this", "# test code here", or similar
   - Imports from fictional modules ("your_module", "my_module", "xxx_module")
   - Test methods with no assertions (just comments or pass)
   - Any stub that is not real, working code
7. Integration: If integration constraints are listed, verify every required reference/import/link is present.
8. Relevance: Does the implementation match the project type? A pure frontend task must not introduce unnecessary server-side code. Tests must import real symbols that exist in the project.

Respond ONLY with a valid JSON object in this exact format:
{
  "passed": true,
  "issues": [],
  "feedback": "Brief summary of the review outcome"
}

If passed is false, 'issues' must be a non-empty list of specific, actionable problem descriptions.
Be precise: name the file, the offending pattern, and what the correct implementation should be."""

    def __init__(
        self,
        event_bus: EventBus,
        task_manager: TaskManager,
        executor: ExecutorRuntime,
        llm: LocalLLM,
        vision_file: str = "vision/vision.json",
        state_file: str = "runtime/state.json"
    ):
        super().__init__("Earl", event_bus, state_file)
        self.tasks = task_manager
        self.executor = executor
        self.llm = llm
        self.vision_file = vision_file

    # ==========================================
    # MAIN ACTION
    # ==========================================

    def review_task(self, task_id: str) -> dict:
        """
        Reviews all files produced for the given task.
        Returns {"passed": bool, "issues": list, "feedback": str}.
        Publishes REVIEW_PASSED or REVIEW_FAILED accordingly.
        """
        task = self._get_task(task_id)
        if not task:
            raise ValueError(f"Earl: task '{task_id}' not found in backlog.")

        self.update_status("busy", current_task=task_id, last_action="REVIEWING")
        cycle = self.get_current_cycle()

        # Collect all code files that should exist in workspace
        code_files = self._read_output_files(task)

        if not code_files:
            reason = "No output files found in workspace — Zed may not have written anything."
            self._publish_failed(task_id, [reason], reason, cycle)
            return {"passed": False, "issues": [reason], "feedback": reason}

        # Load vision constraints for the review prompt
        try:
            vision = load_json(self.vision_file)
        except Exception:
            vision = {}

        # List existing workspace files so Earl can validate imports/references
        try:
            existing_files = self.executor.list_files()
        except Exception:
            existing_files = []

        user_prompt = self._build_prompt(task, code_files, vision, existing_files)
        response = self.llm.ask_json(self.SYSTEM_PROMPT, user_prompt)

        passed = response.get("passed", False)
        issues = response.get("issues", [])
        feedback = response.get("feedback", "")

        if passed:
            self.event_bus.publish(
                agent="Earl",
                event_type="REVIEW_PASSED",
                target=task_id,
                payload={"task_id": task_id, "feedback": feedback},
                current_cycle=cycle
            )
            self.update_status("idle", current_task=None, last_action=f"REVIEW_PASSED:{task_id}")
        else:
            self._publish_failed(task_id, issues, feedback, cycle)

        return {"passed": passed, "issues": issues, "feedback": feedback}

    # ==========================================
    # PRIVATE HELPERS
    # ==========================================

    def _get_task(self, task_id: str) -> Dict[str, Any] | None:
        """Retrieves a task from the backlog by ID."""
        backlog = self.tasks.load_state()["backlog"]
        return next((t for t in backlog if t["id"] == task_id), None)

    def _read_output_files(self, task: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Reads each declared output file from workspace/.
        Returns a list of {path, content} dicts for files that exist.
        """
        result = []
        for output_path in task.get("outputs", []):
            # Normalize: strip 'workspace/' prefix if present
            rel_path = output_path.replace("workspace/", "", 1) if output_path.startswith("workspace/") else output_path
            try:
                content = self.executor.read_file(rel_path)
                result.append({"path": rel_path, "content": content})
            except FileNotFoundError:
                result.append({"path": rel_path, "content": "[FILE NOT FOUND]"})
        return result

    def _build_prompt(
        self,
        task: Dict[str, Any],
        code_files: List[Dict[str, str]],
        vision: Dict[str, Any],
        existing_files: List[str] = None
    ) -> str:
        """Constructs the full review prompt for the LLM."""
        lines = [
            f"=== TASK TO REVIEW ===",
            f"ID: {task['id']}",
            f"Title: {task['title']}",
            f"Description: {task['description']}",
            f"Expected outputs: {task.get('outputs', [])}",
            f"",
        ]

        if existing_files:
            lines.append("=== EXISTING WORKSPACE FILES ===")
            lines.append("Imports and references must point to files in this list (or files produced by this task):")
            for f in existing_files:
                lines.append(f"  - {f}")
            lines.append("")

        # Include relevant vision constraints
        quality = vision.get("quality_constraints", {})
        forbidden = [p for p in vision.get("forbidden_patterns", []) if p]
        if quality or forbidden:
            lines.append("=== VISION CONSTRAINTS ===")
            if quality.get("require_linting"):
                lines.append("- Linting is required (no unused imports, correct style)")
            if quality.get("tests_required"):
                lines.append("- Tests are required for all logic")
            if quality.get("max_function_length") and quality["max_function_length"] > 0:
                lines.append(f"- Max function length: {quality['max_function_length']} lines")
            for pattern in forbidden:
                lines.append(f"- Forbidden pattern: {pattern}")
            lines.append("")

        # Forward-dependency integration check
        try:
            all_tasks = self.tasks.load_state()["backlog"]
            dependents = [t for t in all_tasks if task["id"] in t.get("dependencies", [])]
            if dependents:
                lines.append("=== INTEGRATION CONSTRAINTS ===")
                lines.append(
                    "This task has dependents that will produce the files listed below. "
                    "The code under review MUST already reference/import/link these files correctly:"
                )
                for dep in dependents:
                    for output in dep.get("outputs", []):
                        clean = output.replace("workspace/", "", 1) if output.startswith("workspace/") else output
                        lines.append(f"  - {clean}  ({dep['id']}: {dep['title']})")
                lines.append(
                    "If any of these references are missing, mark passed=false and list them in issues."
                )
                lines.append("")
        except Exception:
            pass

        lines.append("=== CODE TO REVIEW ===")
        for file_entry in code_files:
            lines.append(f"\n--- {file_entry['path']} ---")
            lines.append(file_entry["content"])

        return "\n".join(lines)

    def _publish_failed(self, task_id: str, issues: List[str], feedback: str, cycle: int):
        """Publishes REVIEW_FAILED and resets agent status."""
        self.event_bus.publish(
            agent="Earl",
            event_type="REVIEW_FAILED",
            target=task_id,
            payload={
                "task_id": task_id,
                "issues": issues,
                "feedback": feedback
            },
            current_cycle=cycle
        )
        self.update_status("idle", current_task=None, last_action=f"REVIEW_FAILED:{task_id}")
