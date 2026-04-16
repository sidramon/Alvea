import os
from typing import Dict, Any, List

from agents.base_agent import BaseAgent
from core.event_bus import EventBus
from core.task_manager import TaskManager
from core.executor_runtime import ExecutorRuntime


class Chris(BaseAgent):
    """
    Executor. Runs and validates the code produced by Zed and approved by Earl.

    Responsibilities:
    - Verify that all declared output files exist in workspace/
    - Run the appropriate command for each task type (install, test, lint, script)
    - Publish EXECUTION_SUCCESS or EXECUTION_CRASH with stdout/stderr
    - Never write or modify code

    Does NOT orchestrate, plan, write code, or review.
    """

    # Maps task type to the shell command to run inside workspace/
    # These are overridable per-task via the 'run_command' field (if present)
    DEFAULT_COMMANDS: Dict[str, str] = {
        "setup": "pip install -r requirements.txt",
        "feature": "python -m pytest --tb=short -q",
        "fix": "python -m pytest --tb=short -q",
        "refactor": "python -m pytest --tb=short -q",
    }

    def __init__(
        self,
        event_bus: EventBus,
        task_manager: TaskManager,
        executor: ExecutorRuntime,
        state_file: str = "runtime/state.json"
    ):
        super().__init__("Chris", event_bus, state_file)
        self.tasks = task_manager
        self.executor = executor

    # ==========================================
    # MAIN ACTION
    # ==========================================

    def execute_task(self, task_id: str) -> bool:
        """
        Verifies outputs exist and runs the task's execution command.
        Returns True on success, False on crash.
        Publishes EXECUTION_SUCCESS or EXECUTION_CRASH.
        """
        task = self._get_task(task_id)
        if not task:
            raise ValueError(f"Chris: task '{task_id}' not found in backlog.")

        self.update_status("busy", current_task=task_id, last_action="EXECUTING")
        cycle = self.get_current_cycle()

        # Step 1 — Verify all output files are present
        missing = self._check_outputs(task)
        if missing:
            reason = f"Missing output files: {missing}"
            self._publish_crash(task_id, reason, "", reason, cycle)
            return False

        # Step 2 — Determine which command to run
        command = self._resolve_command(task)

        # Step 3 — Execute
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
            return True

        else:
            reason = result["stderr"] or f"Command exited with code {result['exit_code']}"
            self._publish_crash(task_id, reason, result["stdout"], result["stderr"], cycle)
            return False

    # ==========================================
    # PRIVATE HELPERS
    # ==========================================

    def _get_task(self, task_id: str) -> Dict[str, Any] | None:
        """Retrieves a task from the backlog by ID."""
        backlog = self.tasks.load_state()["backlog"]
        return next((t for t in backlog if t["id"] == task_id), None)

    def _check_outputs(self, task: Dict[str, Any]) -> List[str]:
        """
        Returns a list of declared output paths that are missing from workspace/.
        An empty list means all outputs are present.
        """
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

    def _resolve_command(self, task: Dict[str, Any]) -> str:
        """
        Determines what command to run.
        Priority: task['run_command'] field > DEFAULT_COMMANDS[type] > pytest fallback.
        """
        # Allow tasks to declare an explicit command
        if task.get("run_command"):
            return task["run_command"]

        task_type = task.get("type", "feature")
        return self.DEFAULT_COMMANDS.get(task_type, "python -m pytest --tb=short -q")

    def _publish_crash(
        self,
        task_id: str,
        reason: str,
        stdout: str,
        stderr: str,
        cycle: int
    ):
        """Publishes EXECUTION_CRASH and resets agent status."""
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
