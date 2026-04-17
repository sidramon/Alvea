"""
Alvea — Orchestration logic.

Runs in a background thread. Exposes a shared AppState singleton that the
HTTP server reads to serve status/events to the browser.
"""

import json
import os
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

# ─────────────────────────────────────────────────────────────
# DEFAULT JSON STATES  (used by reset_files)
# ─────────────────────────────────────────────────────────────

_DEFAULT_TASKS = {
    "project_id": "Axoloop Alvea",
    "version": "0.1",
    "generated_by": "Jef",
    "task_model": {
        "granularity": "atomic",
        "definition_of_done": "task produces verifiable output in workspace + passes tests if applicable"
    },
    "backlog": [],
    "metadata": {
        "total_tasks": 0,
        "generated_at": "",
        "last_updated": ""
    }
}

_DEFAULT_PLAN = {
    "project_id": "Axoloop Alvea",
    "version": "0.1",
    "state": {"status": "idle", "cycle": 0},
    "execution": {"ready_queue": [], "in_progress": [], "blocked": []},
    "scheduling": {
        "max_parallel_tasks": 1,
        "selection_policy": "highest_score_first",
        "admission_threshold": 0.65
    },
    "decisions": [],
    "metrics": {"completed_tasks": 0, "failed_tasks": 0, "avg_completion_time": 0}
}

_DEFAULT_RUNTIME_STATE = {
    "project_id": "Axoloop Alvea",
    "last_sync": "",
    "engine": {
        "status": "idle",
        "current_cycle": 0,
        "global_stage": "vision",
        "health_check": "nominal"
    },
    "agents_activity": {
        a: {"status": "idle", "current_task": None, "last_action": None}
        for a in ["Derick", "Jef", "Zed", "Earl", "Chris"]
    },
    "workflow_context": {
        "active_session_id": None,
        "total_tasks_completed": 0,
        "blockers_count": 0,
        "last_error": None
    }
}

_DEFAULT_VISION = {
    "project_name": "Axoloop Alvea",
    "version": "0.1",
    "goal": {"primary_objective": "", "secondary_objectives": []},
    "architecture": {"style": "Hexagonal", "layers": [], "modules": []},
    "dependency_rules": [{"from": "", "to": ""}],
    "agents_contract": {
        a: {"role": r, "rules": []}
        for a, r in [
            ("Derick", "orchestrator"), ("Jef", "planner"),
            ("Zed", "coder"), ("Earl", "reviewer"), ("Chris", "executor")
        ]
    },
    "quality_constraints": {
        "tests_required": True,
        "max_function_length": 0,
        "max_file_complexity": 0,
        "require_linting": True
    },
    "forbidden_patterns": [""],
    "allowed_patterns": [""],
    "execution_policy": {
        "max_parallel_tasks": 1,
        "retry_limit": 0,
        "admission_strategy": "score_based"
    },
    "definitions": {"task_granularity": "", "done_definition": ""}
}


# ─────────────────────────────────────────────────────────────
# SHARED STATE
# ─────────────────────────────────────────────────────────────

AGENTS = ["Derick", "Jef", "Zed", "Earl", "Chris"]


class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        self.running = False
        self.status = "idle"          # idle | running | stopped | done | error
        self.events: List[Dict] = []
        self.agent_status: Dict[str, Dict] = {
            a: {"status": "idle", "task": None} for a in AGENTS
        }
        self.stats = {"cycle": 0, "completed": 0, "blocked": 0}

    def push_event(self, event: Dict):
        with self._lock:
            self.events.append(event)

    def push_msg(self, agent: str, msg: str):
        with self._lock:
            self.events.append({
                "_msg": True,
                "agent": agent,
                "msg": msg,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
            })

    def set_agent(self, agent: str, status: str, task: Optional[str] = None):
        with self._lock:
            self.agent_status[agent] = {"status": status, "task": task}

    def set_stats(self, cycle: int, completed: int, blocked: int):
        with self._lock:
            self.stats = {"cycle": cycle, "completed": completed, "blocked": blocked}

    def get_snapshot(self, since: int = 0) -> Dict:
        with self._lock:
            return {
                "running": self.running,
                "status": self.status,
                "events": self.events[since:],
                "total_events": len(self.events),
                "agent_status": {k: dict(v) for k, v in self.agent_status.items()},
                "stats": dict(self.stats),
            }

    def reset(self):
        with self._lock:
            self.running = False
            self.status = "idle"
            self.events = []
            self.agent_status = {a: {"status": "idle", "task": None} for a in AGENTS}
            self.stats = {"cycle": 0, "completed": 0, "blocked": 0}


# Module-level singleton
state = AppState()
_thread: Optional[threading.Thread] = None
_start_lock = threading.Lock()   # guards the check-and-set in start_run


# ─────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────

def start_run(config: Dict) -> bool:
    """Starts the agent loop. Returns False if already running (idempotent)."""
    global _thread
    with _start_lock:
        # Double-check: refuse if thread is alive even if flag drifted
        if state.running or (_thread is not None and _thread.is_alive()):
            return False
        state.running = True
        state.status = "running"
        _thread = threading.Thread(target=_run_system, args=(config,), daemon=True)
        _thread.start()
        return True


def stop_run():
    state.running = False
    state.status = "stopped"


def reset():
    stop_run()
    state.reset()
    reset_files()


def reset_files():
    """Resets all JSON state files and clears the events log to their default empty state."""
    def write(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    write("tasks/tasks.json",   _DEFAULT_TASKS)
    write("plan/plan.json",     _DEFAULT_PLAN)
    write("runtime/state.json", _DEFAULT_RUNTIME_STATE)
    write("vision/vision.json", _DEFAULT_VISION)

    # Clear events log
    open("runtime/events.log", "w").close()


# ─────────────────────────────────────────────────────────────
# ORCHESTRATION LOOP  (background thread)
# ─────────────────────────────────────────────────────────────

def _run_system(config: Dict):
    try:
        from core.event_bus import EventBus
        from core.planner_engine import PlannerEngine
        from core.task_manager import TaskManager
        from core.executor_runtime import ExecutorRuntime
        from core.llm_client import LocalLLM
        from core.file_utils import load_json, save_json
        from agents.derick import Derick
        from agents.jef import Jef
        from agents.zed import Zed
        from agents.earl import Earl
        from agents.chris import Chris

        bus      = EventBus(log_path="runtime/events.log")
        planner  = PlannerEngine(plan_file="plan/plan.json")
        task_mgr = TaskManager(tasks_file="tasks/tasks.json")
        executor = ExecutorRuntime(workspace_dir="workspace")
        llm      = LocalLLM(base_url=config["llm_url"], model=config["llm_model"])

        derick = Derick(bus, planner, task_mgr)
        jef    = Jef(bus, task_mgr, llm)
        zed    = Zed(bus, task_mgr, executor, llm)
        earl   = Earl(bus, task_mgr, executor, llm)
        chris  = Chris(bus, task_mgr, executor)

        # Forward all bus events into the shared state
        terminal_events = {
            "CYCLE_END", "TASK_COMPLETED", "REVIEW_PASSED", "EXECUTION_SUCCESS"
        }

        def on_event(event: Dict):
            state.push_event(event)
            agent = event.get("agent", "System")
            event_type = event.get("event_type", "")
            target = event.get("target")
            if agent in state.agent_status:
                st = "idle" if event_type in terminal_events else "busy"
                state.set_agent(agent, st, target if target != "system" else None)

        for event_type in EventBus.ALLOWED_EVENTS:
            bus.subscribe(event_type, on_event)

        # Persist form choices into vision.json
        try:
            vision = load_json("vision/vision.json")
            vision["architecture"]["style"] = config["arch"]
            if config["db"] != "Aucune":
                vision["architecture"]["modules"] = [config["db"]]
            qc = vision.setdefault("quality_constraints", {})
            qc["tests_required"] = config["components"].get("Tests unitaires", False)
            qc["require_linting"] = config["components"].get("Linting", False)
            save_json("vision/vision.json", vision)
        except Exception:
            pass

        # Build enriched objective string
        lines = [config["description"].strip(), "", "Contraintes techniques :"]
        lines.append(f"- Architecture : {config['arch']}")
        for comp, enabled in config["components"].items():
            if enabled:
                lines.append(f"- {comp} : oui")
        if config["db"] != "Aucune":
            lines.append(f"- Base de données : {config['db']}")
        objective = "\n".join(lines)

        # Phase 1: Planning
        state.push_msg("Jef", "Décomposition de l'objectif en cours...")
        state.set_agent("Jef", "busy")
        task_ids = jef.plan_objective(objective)
        state.push_msg("Jef", f"{len(task_ids)} tâches créées : {task_ids}")
        state.set_agent("Jef", "idle")

        # Phase 2: Orchestration loop
        for _ in range(config["max_cycles"]):
            if not state.running:
                break

            backlog = task_mgr.load_state()["backlog"]
            if all(t["status"] in ("completed", "blocked") for t in backlog):
                state.push_msg("System", "Toutes les tâches sont résolues.")
                break

            derick.run_cycle()
            _sync_stats(planner, task_mgr)

            # Snapshot the in_progress list at this moment
            snapshot = planner.load_plan()["execution"]["in_progress"]

            for entry in snapshot:
                if not state.running:
                    break

                task_id = entry["task_id"]

                # ── Idempotency guard ─────────────────────────────────────
                # Reload the plan right before processing — the entry may have
                # been mutated by a previous iteration or a concurrent write.
                current_plan = planner.load_plan()
                current_entry = next(
                    (e for e in current_plan["execution"]["in_progress"]
                     if e["task_id"] == task_id),
                    None
                )
                if current_entry is None:
                    # Already completed or blocked since snapshot was taken
                    continue

                assigned = current_entry["assigned_to"]
                # ─────────────────────────────────────────────────────────

                if assigned == "Zed":
                    state.set_agent("Zed", "busy", task_id)
                    try:
                        zed.implement_task(task_id)
                        derick.handoff_to_reviewer(task_id)
                    except Exception as e:
                        derick.fail_task(task_id, str(e))
                    state.set_agent("Zed", "idle")

                elif assigned == "Earl":
                    state.set_agent("Earl", "busy", task_id)
                    try:
                        result = earl.review_task(task_id)
                        if result["passed"]:
                            derick.handoff_to_executor(task_id)
                        else:
                            retry_count = task_mgr.get_retry_count(task_id)
                            retry_limit = _get_retry_limit()
                            if retry_count >= retry_limit:
                                derick.fail_task(
                                    task_id,
                                    f"Review échouée après {retry_count} correction(s)."
                                )
                                state.push_msg("Derick", f"{task_id} bloqué — limite de retries atteinte ({retry_limit}).")
                            else:
                                feedback = _format_review_feedback(result)
                                task_mgr.set_correction_feedback(task_id, feedback)
                                derick.handoff_back_to_coder(task_id)
                                state.push_msg("Derick", f"{task_id} renvoyé à Zed pour correction (tentative {retry_count + 1}/{retry_limit}).")
                    except Exception as e:
                        derick.fail_task(task_id, str(e))
                    state.set_agent("Earl", "idle")

                elif assigned == "Chris":
                    state.set_agent("Chris", "busy", task_id)
                    try:
                        result = chris.execute_task(task_id)
                        if result["success"]:
                            derick.complete_task(task_id)
                        else:
                            retry_count = task_mgr.get_retry_count(task_id)
                            retry_limit = _get_retry_limit()
                            if retry_count >= retry_limit:
                                derick.fail_task(
                                    task_id,
                                    f"Exécution échouée après {retry_count} correction(s)."
                                )
                                state.push_msg("Derick", f"{task_id} bloqué — limite de retries atteinte ({retry_limit}).")
                            else:
                                feedback = _format_chris_feedback(result["reason"])
                                task_mgr.set_correction_feedback(task_id, feedback)
                                derick.handoff_back_to_coder(task_id)
                                state.push_msg("Derick", f"{task_id} renvoyé à Zed — {result['reason'][:60]} (tentative {retry_count + 1}/{retry_limit}).")
                    except Exception as e:
                        derick.fail_task(task_id, str(e))
                    state.set_agent("Chris", "idle")

            _sync_stats(planner, task_mgr)

        state.running = False
        state.status = "done"
        state.push_msg("System", "Exécution terminée.")
        for agent in AGENTS:
            state.set_agent(agent, "idle")

    except Exception as e:
        state.running = False
        state.status = "error"
        state.push_msg("System", f"Erreur fatale : {e}")


def _get_retry_limit() -> int:
    """Reads retry_limit from vision.json. Falls back to 3 if unset or 0."""
    try:
        with open("vision/vision.json", encoding="utf-8") as f:
            vision = json.load(f)
        limit = vision.get("execution_policy", {}).get("retry_limit", 0)
        return limit if limit > 0 else 3
    except Exception:
        return 3


def _format_chris_feedback(reason: str) -> str:
    """Builds Zed-readable feedback from a Chris execution failure."""
    if "Missing output files" in reason:
        # Extract the file list from "Missing output files: ['foo.py', 'bar.js']"
        return (
            f"Chris could not find the following declared output files in workspace/:\n"
            f"{reason}\n"
            f"You MUST create every file listed in the task's 'outputs' field. "
            f"Do not omit any file, even if it would be empty."
        )
    return (
        f"Chris ran the task command and it crashed:\n{reason}\n"
        f"Fix the code so that the command completes successfully."
    )


def _format_review_feedback(result: dict) -> str:
    """Builds a readable correction string from Earl's review result."""
    parts = []
    if result.get("feedback"):
        parts.append(result["feedback"])
    issues = result.get("issues", [])
    if issues:
        parts.append("Issues to fix:")
        parts.extend(f"- {issue}" for issue in issues)
    return "\n".join(parts)


def _sync_stats(planner, task_mgr):
    try:
        plan    = planner.load_plan()
        backlog = task_mgr.load_state()["backlog"]
        cycle     = plan.get("state", {}).get("cycle", 0)
        completed = sum(1 for t in backlog if t["status"] == "completed")
        blocked   = sum(1 for t in backlog if t["status"] == "blocked")
        state.set_stats(cycle, completed, blocked)
    except Exception:
        pass
