import json
from datetime import datetime, timezone
from typing import List, Dict, Any

from agents.base_agent import BaseAgent
from core.event_bus import EventBus
from core.task_manager import TaskManager
from core.llm_client import LocalLLM


class Jef(BaseAgent):
    """
    Planner. Transforms a raw objective into an ordered task backlog.

    Responsibilities:
    - Decompose a goal into atomic, dependency-aware tasks
    - Estimate priority, complexity, and vision alignment per task
    - Write tasks to tasks.json via TaskManager
    - Publish one TASK_ADMITTED event per task created

    Does NOT orchestrate, write code, review, or execute.
    """

    SYSTEM_PROMPT = """You are Jef, an expert software project planner operating inside a multi-agent system.

Your ONLY job is to decompose a software objective into a list of atomic, ordered tasks.

Rules:
- Each task must be the smallest unit of work that produces a verifiable output.
- Every task must have explicit 'outputs' (file paths relative to workspace/).
- If task B depends on task A, list A's ID in B's 'dependencies'.
- Priority, complexity, and vision_alignment must be between 0.0 and 1.0.
- 'type' must be one of: setup, feature, fix, refactor.
- IDs must follow the pattern TASK-001, TASK-002, etc.

About 'run_command' (validation command run by Chris after code review):
- OPTIONAL. Only include when the task genuinely requires shell validation (running tests, checking a script).
- Examples of when to set: "python -m pytest --tb=short -q", "node index.js".
- Examples of when to omit: creating HTML/CSS/JS/JSON files, config files — file presence is enough.

About scaffolding and binary generation tasks:
- If the project requires initializing a framework (Next.js, Django, etc.), create a dedicated 'setup' task with a clear description telling Zed to scaffold the project (e.g. "Run npx create-next-app to initialize the project").
- If the project requires a database file (SQLite, etc.), create a task describing the schema; Zed will create the schema SQL file AND run the init command.
- List the expected generated files/folders in 'outputs' so Chris can verify they exist after setup.
- These scaffold/binary tasks should come first (dependencies=[]) so all other tasks depend on them.

Respond ONLY with a valid JSON object in this exact format:
{
  "tasks": [
    {
      "id": "TASK-001",
      "title": "Short action title",
      "description": "Clear description of what must be done and why",
      "layer": "core | api | ui | infrastructure | test",
      "type": "setup | feature | fix | refactor",
      "priority_hint": 0.0,
      "complexity": 0.0,
      "vision_alignment": 0.0,
      "dependencies": [],
      "outputs": ["workspace/relative/path.ext"],
      "run_command": null,
      "status": "pending",
      "tags": []
    }
  ]
}"""

    def __init__(
        self,
        event_bus: EventBus,
        task_manager: TaskManager,
        llm: LocalLLM,
        state_file: str = "runtime/state.json"
    ):
        super().__init__("Jef", event_bus, state_file)
        self.tasks = task_manager
        self.llm = llm

    # ==========================================
    # MAIN ACTION
    # ==========================================

    def plan_objective(self, objective: str) -> List[str]:
        """
        Decomposes 'objective' into atomic tasks and writes them to the backlog.
        Returns the list of task IDs created.
        """
        self.update_status("busy", last_action="PLANNING", current_task=objective[:80])
        cycle = self.get_current_cycle()

        user_prompt = f"Objective to decompose:\n\n{objective}"

        response = self.llm.ask_json(self.SYSTEM_PROMPT, user_prompt)
        raw_tasks = response.get("tasks", [])

        if not raw_tasks:
            self.update_status("idle", last_action="PLAN_FAILED")
            raise ValueError("Jef: LLM returned no tasks for this objective.")

        now = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

        # Update metadata
        state = self.tasks.load_state()
        state["generated_by"] = "Jef"
        state["metadata"]["generated_at"] = now
        state["metadata"]["last_updated"] = now
        self.tasks.save_state(state)

        created_ids = []
        for task in raw_tasks:
            task_id = self.tasks.add_task(task)
            created_ids.append(task_id)

            self.event_bus.publish(
                agent="Jef",
                event_type="TASK_ADMITTED",
                target=task_id,
                payload={
                    "task_id": task_id,
                    "title": task.get("title", ""),
                    "type": task.get("type", ""),
                    "priority_hint": task.get("priority_hint", 0.0),
                    "complexity": task.get("complexity", 0.0),
                    "dependencies": task.get("dependencies", [])
                },
                current_cycle=cycle
            )

        self.update_status(
            "idle",
            last_action=f"PLANNED_{len(created_ids)}_TASKS"
        )

        return created_ids
