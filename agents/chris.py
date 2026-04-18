import os
import re
from typing import Dict, Any, List, Optional

from agents.base_agent import BaseAgent
from core.event_bus import EventBus
from core.task_manager import TaskManager
from core.executor_runtime import ExecutorRuntime
from core.llm_client import LocalLLM


class Chris(BaseAgent):
    """
    Executor. Runs and validates code produced by Zed and approved by Earl.

    With LLM:
    - If no run_command is declared, asks LLM what command to run (if any)
    - After execution failure, asks LLM to interpret the error into actionable feedback
    - Performs static HTML/JS reference checking (ERR_FILE_NOT_FOUND style)

    Without LLM: falls back to file-presence verification only.
    """

    COMMAND_SYSTEM_PROMPT = """You are Chris, a code executor agent. Given a task and its output files, decide if any shell command needs to be run to validate the result.

Rules:
- Python test files (test_*.py / *_test.py): run with: python -m pytest <file> -v
- Python scripts meant to be executed: run with: python <file>
- Shell scripts (.sh): run with: sh <file>
- HTML / CSS / JS / JSON / Markdown / config files: NO execution needed
- Files that only need to exist: NO execution needed

Respond ONLY with valid JSON:
{
  "needs_execution": false,
  "command": null,
  "reason": "short explanation"
}"""

    ERROR_SYSTEM_PROMPT = """You are Chris, a code executor agent. A shell command failed. Analyze the error and produce structured, actionable feedback for the coder.

Look for:
- Missing files or modules (ModuleNotFoundError, ImportError, No such file)
- Syntax errors (SyntaxError, unexpected token, IndentationError)
- Runtime exceptions (TypeError, ValueError, AttributeError, NameError)
- Permission errors

Respond ONLY with valid JSON:
{
  "error_type": "missing_file|import_error|syntax_error|runtime_error|permission_error|other",
  "missing": ["list of missing files or modules, if any"],
  "feedback": "Specific, actionable instructions for the coder to fix this. Name the exact file and line if possible."
}"""

    def __init__(
        self,
        event_bus: EventBus,
        task_manager: TaskManager,
        executor: ExecutorRuntime,
        llm: Optional[LocalLLM] = None,
        state_file: str = "runtime/state.json"
    ):
        super().__init__("Chris", event_bus, state_file)
        self.tasks = task_manager
        self.executor = executor
        self.llm = llm

    # ==========================================
    # MAIN ACTION
    # ==========================================

    def execute_task(self, task_id: str) -> dict:
        """
        Verifies outputs, runs static checks, executes the task's command.
        Returns {"success": bool, "reason": str}.
        """
        task = self._get_task(task_id)
        if not task:
            raise ValueError(f"Chris: task '{task_id}' not found in backlog.")

        self.update_status("busy", current_task=task_id, last_action="EXECUTING")
        cycle = self.get_current_cycle()

        # Step 1 — Verify output files
        missing = self._check_outputs(task)
        if missing:
            reason = f"Missing output files: {missing}"
            self._publish_crash(task_id, reason, "", reason, cycle)
            return {"success": False, "reason": reason}

        # Step 2 — Static reference check (HTML/JS/CSS broken links)
        ref_errors = self._check_static_references(task)
        if ref_errors:
            reason = "Static reference errors:\n" + "\n".join(ref_errors)
            self._publish_crash(task_id, reason, "", reason, cycle)
            return {"success": False, "reason": reason}

        # Step 3 — Determine command
        command = self._resolve_command(task)

        # Step 4 — Run command (or just confirm presence)
        if command is None:
            self.event_bus.publish(
                agent="Chris",
                event_type="EXECUTION_SUCCESS",
                target=task_id,
                payload={"task_id": task_id, "command": "none", "stdout": "Output files verified.", "exit_code": 0},
                current_cycle=cycle
            )
            self.update_status("idle", current_task=None, last_action=f"SUCCESS:{task_id}")
            return {"success": True, "reason": ""}

        result = self.executor.run_command(command)

        if result["success"]:
            self.event_bus.publish(
                agent="Chris",
                event_type="EXECUTION_SUCCESS",
                target=task_id,
                payload={
                    "task_id": task_id,
                    "command": command,
                    "stdout": result["stdout"],
                    "exit_code": result["exit_code"]
                },
                current_cycle=cycle
            )
            self.update_status("idle", current_task=None, last_action=f"SUCCESS:{task_id}")
            return {"success": True, "reason": ""}

        else:
            # Step 5 — Interpret error with LLM if available
            raw_error = result["stderr"] or result["stdout"] or f"Exit code {result['exit_code']}"
            reason = self._interpret_error(task, command, result["stdout"], result["stderr"])
            self._publish_crash(task_id, reason, result["stdout"], result["stderr"], cycle)
            return {"success": False, "reason": reason}

    # ==========================================
    # STATIC REFERENCE CHECKING
    # ==========================================

    def _check_static_references(self, task: Dict[str, Any]) -> List[str]:
        """
        Checks HTML/JS/CSS files for broken references (src, href, import paths).
        Returns browser-style error strings for each broken reference.
        """
        errors = []
        for output_path in task.get("outputs", []):
            rel_path = (
                output_path.replace("workspace/", "", 1)
                if output_path.startswith("workspace/")
                else output_path
            )
            full_path = os.path.join(self.executor.workspace_dir, rel_path)
            if not os.path.exists(full_path):
                continue

            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue

            ext = os.path.splitext(rel_path)[1].lower()
            file_dir = os.path.dirname(rel_path)

            if ext == ".html":
                errors.extend(self._check_html_refs(rel_path, file_dir, content))
            elif ext in (".js", ".ts", ".mjs"):
                errors.extend(self._check_js_refs(rel_path, file_dir, content))

        return errors

    def _check_html_refs(self, file_path: str, file_dir: str, content: str) -> List[str]:
        errors = []
        # src and href attributes
        for attr, value in re.findall(r'(?:src|href)=["\']([^"\']+)["\']', content):
            errors.extend(self._validate_ref(file_path, file_dir, value))
        # also catch: src="..." href="..."
        for value in re.findall(r'(?:src|href)="([^"]+)"', content):
            errors.extend(self._validate_ref(file_path, file_dir, value))
        for value in re.findall(r"(?:src|href)='([^']+)'", content):
            errors.extend(self._validate_ref(file_path, file_dir, value))
        return errors

    def _check_js_refs(self, file_path: str, file_dir: str, content: str) -> List[str]:
        errors = []
        # import ... from './X' or require('./X')
        for value in re.findall(r"""(?:import\s+.*?from\s+|require\s*\(\s*)['"](\./[^'"]+)['"]""", content):
            errors.extend(self._validate_ref(file_path, file_dir, value))
        return errors

    def _validate_ref(self, file_path: str, file_dir: str, ref: str) -> List[str]:
        """Checks if a reference (src/href/import) resolves to an existing file."""
        # Skip external, anchor, data URIs, template literals
        if (ref.startswith("http") or ref.startswith("//") or
                ref.startswith("#") or ref.startswith("data:") or
                "${" in ref or ref == "/"):
            return []
        # Resolve relative path
        if ref.startswith("/"):
            resolved = ref.lstrip("/")
        else:
            resolved = os.path.normpath(os.path.join(file_dir, ref)).replace("\\", "/")
        full = os.path.join(self.executor.workspace_dir, resolved)
        if not os.path.exists(full):
            return [f"Failed to load resource: net::ERR_FILE_NOT_FOUND {ref} (referenced in {file_path})"]
        return []

    # ==========================================
    # COMMAND RESOLUTION
    # ==========================================

    def _resolve_command(self, task: Dict[str, Any]) -> Optional[str]:
        """
        Returns the command to run:
        1. Explicit run_command from task (highest priority)
        2. LLM-generated command (if LLM available and no run_command)
        3. None → file verification only
        """
        explicit = task.get("run_command") or None
        if explicit:
            return explicit

        if self.llm is None:
            return None

        # Ask LLM what command to run
        try:
            outputs = task.get("outputs", [])
            clean_outputs = [
                o.replace("workspace/", "", 1) if o.startswith("workspace/") else o
                for o in outputs
            ]
            user_prompt = (
                f"Task: {task.get('title', '')}\n"
                f"Description: {task.get('description', '')}\n"
                f"Output files: {clean_outputs}\n"
                f"Tags: {task.get('tags', [])}\n"
            )
            response = self.llm.ask_json(self.COMMAND_SYSTEM_PROMPT, user_prompt)
            if response.get("needs_execution") and response.get("command"):
                return response["command"]
        except Exception:
            pass

        return None

    # ==========================================
    # ERROR INTERPRETATION
    # ==========================================

    def _interpret_error(
        self, task: Dict[str, Any], command: str, stdout: str, stderr: str
    ) -> str:
        """
        Uses LLM to interpret execution errors into actionable feedback.
        Falls back to raw error if LLM unavailable or fails.
        """
        raw = stderr or stdout or f"Command '{command}' failed with no output."

        if self.llm is None:
            return raw

        try:
            user_prompt = (
                f"Task: {task.get('title', '')}\n"
                f"Command executed: {command}\n\n"
                f"STDOUT:\n{stdout}\n\n"
                f"STDERR:\n{stderr}"
            )
            response = self.llm.ask_json(self.ERROR_SYSTEM_PROMPT, user_prompt)
            feedback = response.get("feedback", "")
            missing = response.get("missing", [])
            error_type = response.get("error_type", "other")

            parts = [f"[{error_type.upper()}] {feedback}"]
            if missing:
                parts.append(f"Missing: {', '.join(missing)}")
            return "\n".join(parts) if any(parts) else raw
        except Exception:
            return raw

    # ==========================================
    # PRIVATE HELPERS
    # ==========================================

    def _get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        backlog = self.tasks.load_state()["backlog"]
        return next((t for t in backlog if t["id"] == task_id), None)

    def _check_outputs(self, task: Dict[str, Any]) -> List[str]:
        missing = []
        for output_path in task.get("outputs", []):
            rel_path = (
                output_path.replace("workspace/", "", 1)
                if output_path.startswith("workspace/")
                else output_path
            )
            full_path = os.path.join(self.executor.workspace_dir, rel_path)
            if not os.path.exists(full_path):
                missing.append(rel_path)
        return missing

    def _publish_crash(
        self,
        task_id: str,
        reason: str,
        stdout: str,
        stderr: str,
        cycle: int
    ):
        self.event_bus.publish(
            agent="Chris",
            event_type="EXECUTION_CRASH",
            target=task_id,
            payload={
                "task_id": task_id,
                "reason": reason,
                "stdout": stdout,
                "stderr": stderr
            },
            current_cycle=cycle
        )
        self.update_status("idle", current_task=None, last_action=f"CRASH:{task_id}")
