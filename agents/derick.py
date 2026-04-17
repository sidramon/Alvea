from typing import Dict, Any, List, Optional

from agents.base_agent import BaseAgent
from core.event_bus import EventBus
from core.planner_engine import PlannerEngine
from core.task_manager import TaskManager
from core.file_utils import load_json, save_json


class Derick(BaseAgent):
    """
    Orchestrator. Controls the full execution flow.

    Responsibilities:
    - Score and admit tasks from backlog to ready_queue
    - Dispatch tasks to the right agent
    - Handoff tasks between agents (Zed → Earl → Chris)
    - Mark tasks as completed
    - Manage cycle counter and engine state

    Does NOT write code, review, or execute commands.
    """

    def __init__(
        self,
        event_bus: EventBus,
        planner_engine: PlannerEngine,
        task_manager: TaskManager,
        state_file: str = "runtime/state.json"
    ):
        super().__init__("Derick", event_bus, state_file)
        self.planner = planner_engine
        self.tasks = task_manager

    # ==========================================
    # MAIN CYCLE
    # ==========================================

    def run_cycle(self):
        """
        Executes one full orchestration cycle:
        1. Admit eligible tasks to ready_queue
        2. Dispatch the highest-priority queued task
        3. Increment cycle counter
        """
        cycle = self.get_current_cycle()
        self.update_status("busy", last_action="CYCLE_START")

        self.event_bus.publish(
            agent="Derick",
            event_type="CYCLE_START",
            target="system",
            payload={"cycle": cycle},
            current_cycle=cycle
        )

        admitted = self.admit_eligible_tasks()
        dispatched = self.dispatch_next_task()

        self._increment_cycle()
        next_cycle = self.get_current_cycle()

        self.event_bus.publish(
            agent="Derick",
            event_type="CYCLE_END",
            target="system",
            payload={
                "admitted": admitted,
                "dispatched": dispatched,
                "next_cycle": next_cycle
            },
            current_cycle=next_cycle
        )

        self.update_status("idle", last_action="CYCLE_END")

    # ==========================================
    # TASK ADMISSION
    # ==========================================

    def admit_eligible_tasks(self) -> List[str]:
        """
        Scores pending tasks and admits eligible ones to the ready_queue.
        Respects max_parallel_tasks and admission_threshold.
        A task is eligible if:
          - status is 'pending'
          - not already queued, in_progress, or blocked
          - all dependencies are completed
          - score >= admission_threshold
        """
        plan = self.planner.load_plan()
        backlog = self.tasks.load_state()["backlog"]

        max_parallel = plan["scheduling"]["max_parallel_tasks"]
        threshold = plan["scheduling"]["admission_threshold"]
        currently_active = (
            len(plan["execution"]["in_progress"]) +
            len(plan["execution"]["ready_queue"])
        )

        slots_available = max_parallel - currently_active
        if slots_available <= 0:
            return []

        completed_ids = {t.get("id") for t in backlog if t.get("status") == "completed"}
        excluded_ids = (
            {t["task_id"] for t in plan["execution"]["ready_queue"]} |
            {t["task_id"] for t in plan["execution"]["in_progress"]} |
            {t["task_id"] for t in plan["execution"]["blocked"]}
        )

        candidates = [
            t for t in backlog
            if t.get("status", "pending") == "pending"
            and t.get("id") not in excluded_ids
            and self._deps_satisfied(t, completed_ids)
        ]

        scored = sorted(
            [(task, self._score_task(task)) for task in candidates],
            key=lambda x: x[1],
            reverse=True
        )

        admitted = []
        cycle = self.get_current_cycle()

        for task, score in scored[:slots_available]:
            if score < threshold:
                continue

            assigned_to = self._assign_agent(task)
            reason = (
                f"score={score:.2f} | "
                f"priority={task['priority_hint']} | "
                f"alignment={task['vision_alignment']} | "
                f"complexity={task['complexity']}"
            )

            self.planner.admit_task_to_ready_queue(
                task_id=task["id"],
                assigned_to=assigned_to,
                priority_score=round(score, 4),
                reason=reason
            )

            self.event_bus.publish(
                agent="Derick",
                event_type="TASK_ADMITTED",
                target=task["id"],
                payload={
                    "task_id": task["id"],
                    "assigned_to": assigned_to,
                    "priority_score": round(score, 4),
                    "reason": reason
                },
                current_cycle=cycle
            )

            admitted.append(task["id"])

        return admitted

    # ==========================================
    # TASK DISPATCH
    # ==========================================

    def dispatch_next_task(self) -> Optional[str]:
        """
        Moves the highest-priority task from ready_queue to in_progress.
        Returns the task_id dispatched, or None if the queue is empty.
        """
        plan = self.planner.load_plan()
        queue = plan["execution"]["ready_queue"]

        if not queue:
            return None

        next_entry = max(queue, key=lambda t: t["priority_score"])

        self.planner.move_to_in_progress(
            task_id=next_entry["task_id"],
            assigned_to=next_entry["assigned_to"]
        )

        cycle = self.get_current_cycle()
        self.event_bus.publish(
            agent="Derick",
            event_type="TASK_STARTED",
            target=next_entry["task_id"],
            payload={
                "task_id": next_entry["task_id"],
                "assigned_to": next_entry["assigned_to"]
            },
            current_cycle=cycle
        )

        return next_entry["task_id"]

    # ==========================================
    # TASK HANDOFF
    # ==========================================

    def handoff_back_to_coder(self, task_id: str):
        """
        Sends a task that failed Earl's review back to Zed for correction.
        Called when retry_count < retry_limit.
        """
        self._reassign_in_progress(task_id, "Zed")
        cycle = self.get_current_cycle()
        self.event_bus.publish(
            agent="Derick",
            event_type="TASK_STARTED",
            target=task_id,
            payload={"task_id": task_id, "assigned_to": "Zed", "retry": True},
            current_cycle=cycle
        )

    def handoff_to_reviewer(self, task_id: str):
        """
        Reassigns a task in in_progress from Zed to Earl (review phase).
        Called after Zed publishes CODE_WRITTEN.
        """
        self._reassign_in_progress(task_id, "Earl")
        cycle = self.get_current_cycle()
        self.event_bus.publish(
            agent="Derick",
            event_type="TASK_STARTED",
            target=task_id,
            payload={"task_id": task_id, "assigned_to": "Earl"},
            current_cycle=cycle
        )

    def handoff_to_executor(self, task_id: str):
        """
        Reassigns a task in in_progress from Earl to Chris (execution phase).
        Called after Earl publishes REVIEW_PASSED.
        """
        self._reassign_in_progress(task_id, "Chris")
        cycle = self.get_current_cycle()
        self.event_bus.publish(
            agent="Derick",
            event_type="TASK_STARTED",
            target=task_id,
            payload={"task_id": task_id, "assigned_to": "Chris"},
            current_cycle=cycle
        )

    def complete_task(self, task_id: str):
        """
        Marks a task as done in plan.json and tasks.json.
        Updates completion metrics.
        Called after Chris publishes EXECUTION_SUCCESS.
        """
        plan = self.planner.load_plan()
        plan["execution"]["in_progress"] = [
            t for t in plan["execution"]["in_progress"]
            if t["task_id"] != task_id
        ]
        plan["metrics"]["completed_tasks"] += 1
        self.planner.save_plan(plan)

        self.tasks.update_task_status(task_id, "completed")

        cycle = self.get_current_cycle()
        self.event_bus.publish(
            agent="Derick",
            event_type="TASK_COMPLETED",
            target=task_id,
            payload={"task_id": task_id},
            current_cycle=cycle
        )

    def fail_task(self, task_id: str, reason: str):
        """
        Blocks a task after a review failure or execution crash.
        Increments failed_tasks metric.
        """
        plan = self.planner.load_plan()
        plan["metrics"]["failed_tasks"] = plan["metrics"].get("failed_tasks", 0) + 1
        self.planner.save_plan(plan)

        self.planner.block_task(task_id, reason)
        self.tasks.update_task_status(task_id, "blocked")

        cycle = self.get_current_cycle()
        self.event_bus.publish(
            agent="Derick",
            event_type="TASK_BLOCKED",
            target=task_id,
            payload={"task_id": task_id, "reason": reason},
            current_cycle=cycle
        )

    # ==========================================
    # PRIVATE HELPERS
    # ==========================================

    def _score_task(self, task: Dict[str, Any]) -> float:
        """
        Multi-criteria score:
          priority_hint  × 0.40
          vision_alignment × 0.40
          (1 - complexity) × 0.20   (lower complexity → easier → higher score)
        """
        priority = task.get("priority_hint", 0.0)
        alignment = task.get("vision_alignment", 0.0)
        ease = 1.0 - task.get("complexity", 0.0)
        return round(priority * 0.4 + alignment * 0.4 + ease * 0.2, 4)

    def _deps_satisfied(self, task: Dict[str, Any], completed_ids: set) -> bool:
        """Returns True only when every declared dependency is completed."""
        return all(dep in completed_ids for dep in task.get("dependencies", []))

    def _assign_agent(self, task: Dict[str, Any]) -> str:
        """First assignee is always Zed (coder). Handoffs are managed separately."""
        return "Zed"

    def _reassign_in_progress(self, task_id: str, new_agent: str):
        """Updates the assigned_to field of a task currently in_progress."""
        plan = self.planner.load_plan()
        for entry in plan["execution"]["in_progress"]:
            if entry["task_id"] == task_id:
                entry["assigned_to"] = new_agent
                entry["attempt"] = entry.get("attempt", 1) + 1
                break
        self.planner.save_plan(plan)

    def _increment_cycle(self):
        """Bumps the cycle counter and updates engine status in state.json."""
        from datetime import datetime, timezone
        try:
            state = load_json(self.state_file)
            state["engine"]["current_cycle"] += 1
            state["engine"]["status"] = "running"
            state["last_sync"] = (
                datetime.now(timezone.utc)
                .isoformat(timespec='milliseconds')
                .replace('+00:00', 'Z')
            )
            save_json(self.state_file, state)
        except Exception as e:
            print(f"[ERROR] Derick: failed to increment cycle: {e}")
