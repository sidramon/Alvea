import os
from typing import Dict, Any, List
from datetime import datetime, timezone

from core.file_utils import load_json, save_json, ensure_file


class PlannerEngine:
    """Orchestration engine (plan.json). Derick's primary tool."""

    _INIT_STRUCT = {
        "execution": {
            "ready_queue": [],
            "in_progress": [],
            "blocked": []
        },
        "decisions": []
    }

    def __init__(self, plan_file: str = "plan/plan.json"):
        self.plan_file = plan_file
        ensure_file(self.plan_file, self._INIT_STRUCT)

    # ==========================================
    # READ / WRITE
    # ==========================================
    def load_plan(self) -> Dict[str, Any]:
        return load_json(self.plan_file)

    def save_plan(self, data: Dict[str, Any]):
        save_json(self.plan_file, data)

    # ==========================================
    # QUEUE MANAGEMENT
    # ==========================================
    def admit_task_to_ready_queue(self, task_id: str, assigned_to: str, priority_score: float, reason: str):
        plan = self.load_plan()
        plan["execution"]["ready_queue"].append({
            "task_id": task_id,
            "assigned_to": assigned_to,
            "priority_score": priority_score,
            "reason": reason,
            "status": "queued"
        })
        self._log_decision(plan, "ADMIT_TASK", task_id, reason)
        self.save_plan(plan)

    def move_to_in_progress(self, task_id: str, assigned_to: str):
        plan = self.load_plan()

        # Remove from ready_queue
        task_entry = next((t for t in plan["execution"]["ready_queue"] if t["task_id"] == task_id), None)
        if task_entry:
            plan["execution"]["ready_queue"].remove(task_entry)

        # Add to in_progress
        plan["execution"]["in_progress"].append({
            "task_id": task_id,
            "assigned_to": assigned_to,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "attempt": 1
        })
        self.save_plan(plan)

    def block_task(self, task_id: str, reason: str):
        plan = self.load_plan()

        # Remove from in_progress
        plan["execution"]["in_progress"] = [
            t for t in plan["execution"]["in_progress"] if t["task_id"] != task_id
        ]

        # Add to blocked
        plan["execution"]["blocked"].append({
            "task_id": task_id,
            "reason": reason
        })
        self._log_decision(plan, "BLOCK_TASK", task_id, reason)
        self.save_plan(plan)

    # ==========================================
    # INTERNAL LOGGING
    # ==========================================
    def _log_decision(self, plan: Dict[str, Any], action: str, task_id: str, reason: str):
        plan["decisions"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "task_id": task_id,
            "reason": reason
        })
