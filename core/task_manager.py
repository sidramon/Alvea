from typing import Dict, List, Any

from core.file_utils import load_json, save_json, ensure_file


class TaskManager:
    """Backlog manager (tasks.json). Jef's primary tool."""

    _INIT_STRUCT = {
        "project_id": "Axoloop Alvea",
        "version": "0.1",
        "generated_by": "System",
        "task_model": {
            "granularity": "atomic",
            "definition_of_done": "task produces verifiable output in workspace + passes tests if applicable"
        },
        "backlog": [],
        "metadata": {"total_tasks": 0, "generated_at": "", "last_updated": ""}
    }

    def __init__(self, tasks_file: str = "tasks/tasks.json"):
        self.tasks_file = tasks_file
        ensure_file(self.tasks_file, self._INIT_STRUCT)

    # ==========================================
    # READ / WRITE
    # ==========================================
    def load_state(self) -> Dict[str, Any]:
        return load_json(self.tasks_file)

    def save_state(self, data: Dict[str, Any]):
        save_json(self.tasks_file, data)

    # ==========================================
    # TASK OPERATIONS
    # ==========================================
    # Guaranteed defaults for any field the LLM might omit
    _TASK_DEFAULTS: Dict[str, Any] = {
        "status":           "pending",
        "priority_hint":    0.5,
        "complexity":       0.5,
        "vision_alignment": 0.5,
        "dependencies":     [],
        "outputs":          [],
        "tags":             [],
        "run_command":      None,
        "retry_count":      0,
        "correction_feedback": "",
    }

    def add_task(self, task_data: Dict[str, Any]) -> str:
        """Saves a task after filling in any missing fields with safe defaults."""
        normalized = {**self._TASK_DEFAULTS, **task_data}
        state = self.load_state()
        state["backlog"].append(normalized)
        state["metadata"]["total_tasks"] = len(state["backlog"])
        self.save_state(state)
        return normalized["id"]

    def update_task_status(self, task_id: str, new_status: str):
        state = self.load_state()
        for task in state["backlog"]:
            if task.get("id") == task_id:
                task["status"] = new_status
                break
        self.save_state(state)

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        state = self.load_state()
        return [t for t in state["backlog"] if t.get("status", "pending") == "pending"]

    def set_correction_feedback(self, task_id: str, feedback: str):
        """Stores Earl's review feedback on the task and increments retry_count."""
        state = self.load_state()
        for task in state["backlog"]:
            if task["id"] == task_id:
                task["correction_feedback"] = feedback
                task["retry_count"] = task.get("retry_count", 0) + 1
                break
        self.save_state(state)

    def get_retry_count(self, task_id: str) -> int:
        state = self.load_state()
        task = next((t for t in state["backlog"] if t["id"] == task_id), None)
        return task.get("retry_count", 0) if task else 0
