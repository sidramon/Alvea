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

_MODELS_FILE = "runtime/models.json"


# ─────────────────────────────────────────────────────────────
# SHARED STATE
# ─────────────────────────────────────────────────────────────

AGENTS = ["Derick", "Jef", "Zed", "Earl", "Chris"]


class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        self.running = False
        self.status = "idle"
        self.events: List[Dict] = []
        self.agent_status: Dict[str, Dict] = {
            a: {"status": "idle", "task": None} for a in AGENTS
        }
        self.agent_stream: Dict[str, str] = {a: "" for a in AGENTS}
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

    def set_agent_stream(self, agent: str, text: str):
        with self._lock:
            self.agent_stream[agent] = text

    def append_agent_stream(self, agent: str, chunk: str):
        with self._lock:
            self.agent_stream[agent] = self.agent_stream.get(agent, "") + chunk

    def get_snapshot(self, since: int = 0) -> Dict:
        with self._lock:
            return {
                "running": self.running,
                "status": self.status,
                "events": self.events[since:],
                "total_events": len(self.events),
                "agent_status": {k: dict(v) for k, v in self.agent_status.items()},
                "stats": dict(self.stats),
                "agent_stream": dict(self.agent_stream),
            }

    def reset(self):
        with self._lock:
            self.running = False
            self.status = "idle"
            self.events = []
            self.agent_status = {a: {"status": "idle", "task": None} for a in AGENTS}
            self.agent_stream = {a: "" for a in AGENTS}
            self.stats = {"cycle": 0, "completed": 0, "blocked": 0}


# Module-level singleton
state = AppState()
_thread: Optional[threading.Thread] = None
_start_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────

def start_run(config: Dict) -> bool:
    """
    Starts the agent loop. Returns False if already running.
    Auto-resets state and JSON files before each run.
    """
    global _thread
    with _start_lock:
        if state.running or (_thread is not None and _thread.is_alive()):
            return False

        # Auto-reset before every run
        state.reset()
        reset_files()

        state.running = True
        state.status = "running"
        _thread = threading.Thread(target=_run_system, args=(config,), daemon=True)
        _thread.start()

        # Persist model/url history for future sessions
        _save_model_history(config)

        return True


def stop_run():
    state.running = False
    state.status = "stopped"


def reset():
    stop_run()
    state.reset()
    reset_files()


def reset_files():
    """Resets all JSON state files and clears the events log."""
    def write(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    write("tasks/tasks.json",   _DEFAULT_TASKS)
    write("plan/plan.json",     _DEFAULT_PLAN)
    write("runtime/state.json", _DEFAULT_RUNTIME_STATE)
    write("vision/vision.json", _DEFAULT_VISION)
    open("runtime/events.log", "w").close()


def load_model_history() -> Dict:
    """Returns {models: [...], urls: [...]} from runtime/models.json."""
    try:
        with open(_MODELS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"models": [], "urls": []}


def _save_model_history(config: Dict):
    """
    Appends the used global model/url and any per-agent model/url to the history file.
    Keeps the 10 most recent unique values.
    """
    try:
        history = load_model_history()
        models = history.get("models", [])
        urls   = history.get("urls", [])

        def _add(lst, val):
            if val and val not in lst:
                lst.insert(0, val)
            return lst[:10]

        _add(urls,   config.get("llm_url", ""))
        _add(models, config.get("llm_model", ""))

        for agent_cfg in config.get("agent_llm", {}).values():
            if agent_cfg.get("url"):
                _add(urls,   agent_cfg["url"])
            if agent_cfg.get("model"):
                _add(models, agent_cfg["model"])

        os.makedirs("runtime", exist_ok=True)
        with open(_MODELS_FILE, "w", encoding="utf-8") as f:
            json.dump({"models": models, "urls": urls}, f, indent=2)
    except Exception:
        pass


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

        global_url   = config["llm_url"]
        global_model = config["llm_model"]
        agent_llm_cfg = config.get("agent_llm", {})

        def _make_llm(agent_name: str) -> LocalLLM:
            cfg   = agent_llm_cfg.get(agent_name, {})
            url   = cfg.get("url")   or global_url
            model = cfg.get("model") or global_model
            return LocalLLM(base_url=url, model=model)

        workspace_path = config.get("workspace_path", "workspace") or "workspace"

        bus      = EventBus(log_path="runtime/events.log")
        planner  = PlannerEngine(plan_file="plan/plan.json")
        task_mgr = TaskManager(tasks_file="tasks/tasks.json")
        executor = ExecutorRuntime(workspace_dir=workspace_path)

        llm_jef   = _make_llm("Jef")
        llm_zed   = _make_llm("Zed")
        llm_earl  = _make_llm("Earl")
        llm_chris = _make_llm("Chris")

        derick = Derick(bus, planner, task_mgr)
        jef    = Jef(bus, task_mgr, llm_jef)
        zed    = Zed(bus, task_mgr, executor, llm_zed)
        earl   = Earl(bus, task_mgr, executor, llm_earl)
        chris  = Chris(bus, task_mgr, executor, llm_chris)

        # Forward all bus events into the shared state
        terminal_events = {
            "CYCLE_END", "TASK_COMPLETED", "REVIEW_PASSED", "EXECUTION_SUCCESS"
        }

        def on_event(event: Dict):
            state.push_event(event)
            agent      = event.get("agent", "System")
            event_type = event.get("event_type", "")
            target     = event.get("target")
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
            qc["tests_required"]  = config["components"].get("Tests unitaires", False)
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

        def stream_for(agent_name: str):
            def _cb(chunk: str):
                state.append_agent_stream(agent_name, chunk)
            return _cb

        def with_stream(agent_name: str, agent_llm: "LocalLLM", fn):
            """Clears the stream buffer, attaches callback, calls fn, detaches."""
            state.set_agent_stream(agent_name, "")
            agent_llm.on_chunk = stream_for(agent_name)
            try:
                return fn()
            finally:
                agent_llm.on_chunk = None

        # Phase 1: Planning
        state.push_msg("Jef", "Décomposition de l'objectif en cours...")
        state.set_agent("Jef", "busy")
        task_ids = with_stream("Jef", llm_jef, lambda: jef.plan_objective(objective))
        state.push_msg("Jef", f"{len(task_ids)} tâches créées : {task_ids}")
        state.set_agent("Jef", "idle")

        # Phase 2: Orchestration loop
        for _ in range(config["max_cycles"]):
            if not state.running:
                break

            backlog = task_mgr.load_state()["backlog"]
            if all(t.get("status", "pending") in ("completed", "blocked") for t in backlog):
                state.push_msg("System", "Toutes les tâches sont résolues.")
                break

            derick.run_cycle()
            _sync_stats(planner, task_mgr)

            snapshot = planner.load_plan()["execution"]["in_progress"]

            for entry in snapshot:
                if not state.running:
                    break

                task_id = entry["task_id"]

                # Idempotency guard
                current_plan = planner.load_plan()
                current_entry = next(
                    (e for e in current_plan["execution"]["in_progress"]
                     if e["task_id"] == task_id),
                    None
                )
                if current_entry is None:
                    continue

                assigned = current_entry["assigned_to"]

                if assigned == "Zed":
                    state.set_agent("Zed", "busy", task_id)
                    try:
                        with_stream("Zed", llm_zed, lambda: zed.implement_task(task_id))
                        derick.handoff_to_reviewer(task_id)
                    except Exception as e:
                        derick.fail_task(task_id, str(e))
                    state.set_agent("Zed", "idle")

                elif assigned == "Earl":
                    state.set_agent("Earl", "busy", task_id)
                    try:
                        result = with_stream("Earl", llm_earl, lambda: earl.review_task(task_id))
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
                                state.push_msg("Derick", f"{task_id} renvoyé à Zed (tentative {retry_count + 1}/{retry_limit}).")
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
    try:
        with open("vision/vision.json", encoding="utf-8") as f:
            vision = json.load(f)
        limit = vision.get("execution_policy", {}).get("retry_limit", 0)
        return limit if limit > 0 else 3
    except Exception:
        return 3


def _format_chris_feedback(reason: str) -> str:
    if "Missing output files" in reason:
        return (
            f"Chris could not find the following declared output files in workspace/:\n"
            f"{reason}\n"
            f"You MUST create every file listed in the task's 'outputs' field."
        )
    if "net::ERR_FILE_NOT_FOUND" in reason or "Static reference errors" in reason:
        return (
            f"Chris detected broken file references:\n{reason}\n"
            f"Ensure every file referenced via src/href/import actually exists in workspace/."
        )
    return (
        f"Chris ran the task command and it crashed:\n{reason}\n"
        f"Fix the code so that the command completes successfully."
    )


def _format_review_feedback(result: dict) -> str:
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
        completed = sum(1 for t in backlog if t.get("status") == "completed")
        blocked   = sum(1 for t in backlog if t.get("status") == "blocked")
        state.set_stats(cycle, completed, blocked)
    except Exception:
        pass
