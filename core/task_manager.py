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
    def add_task(self, task_data: Dict[str, Any]) -> str:
        state = self.load_state()
        state["backlog"].append(task_data)
        state["metadata"]["total_tasks"] = len(state["backlog"])
        self.save_state(state)
        return task_data["id"]

    def update_task_status(self, task_id: str, new_status: str):
        state = self.load_state()
        for task in state["backlog"]:
            if task["id"] == task_id:
                task["status"] = new_status
                break
        self.save_state(state)

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        state = self.load_state()
        return [t for t in state["backlog"] if t["status"] == "pending"]
