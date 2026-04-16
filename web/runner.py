"""
Alvea — Orchestration logic.

Runs in a background thread. Exposes a shared AppState singleton that the
HTTP server reads to serve status/events to the browser.
"""

import threading
from datetime import datetime
from typing import Dict, Any, List, Optional


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


# ─────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────

def start_run(config: Dict):
    global _thread
    if state.running:
        return
    state.running = True
    state.status = "running"
    _thread = threading.Thread(target=_run_system, args=(config,), daemon=True)
    _thread.start()


def stop_run():
    state.running = False
    state.status = "stopped"


def reset():
    stop_run()
    state.reset()


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

            plan = planner.load_plan()
            for entry in plan["execution"]["in_progress"]:
                if not state.running:
                    break

                task_id  = entry["task_id"]
                assigned = entry["assigned_to"]

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
                        passed = earl.review_task(task_id)
                        if passed:
                            derick.handoff_to_executor(task_id)
                        else:
                            derick.fail_task(task_id, "Review échouée.")
                    except Exception as e:
                        derick.fail_task(task_id, str(e))
                    state.set_agent("Earl", "idle")

                elif assigned == "Chris":
                    state.set_agent("Chris", "busy", task_id)
                    try:
                        success = chris.execute_task(task_id)
                        if success:
                            derick.complete_task(task_id)
                        else:
                            derick.fail_task(task_id, "Exécution échouée.")
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
