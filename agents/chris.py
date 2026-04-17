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

    # Chris never assumes a default command.
    # Tasks must declare an explicit 'run_command' field if execution is needed.
    # Without it, Chris only verifies that output files exist, then succeeds.

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

    def execute_task(self, task_id: str) -> dict:
        """
        Verifies outputs exist and runs the task's execution command.
        Returns {"success": bool, "reason": str} — reason is empty on success.
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
            return {"success": False, "reason": reason}

        # Step 2 — Determine which command to run (None = verification only)
        command = self._resolve_command(task)

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
            return {"success": True, "reason": ""}

        else:
            reason = result["stderr"] or f"Command exited with code {result['exit_code']}"
            self._publish_crash(task_id, reason, result["stdout"], result["stderr"], cycle)
            return {"success": False, "reason": reason}

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

    def _resolve_command(self, task: Dict[str, Any]) -> str | None:
        """
        Returns the command to run, or None if no execution is needed.
        Only tasks that explicitly declare 'run_command' trigger a shell command.
        """
        return task.get("run_command") or None

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
