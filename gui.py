"""
Axoloop Alvea — Graphical Interface

Launch:
    python gui.py
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import queue
import json
import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional

# ─────────────────────────────────────────────────────────────
# COLOR PALETTE  (GitHub-dark inspired)
# ─────────────────────────────────────────────────────────────
C = {
    "bg":       "#0d1117",
    "bg2":      "#161b22",
    "bg3":      "#21262d",
    "border":   "#30363d",
    "text":     "#c9d1d9",
    "dim":      "#8b949e",
    "accent":   "#388bfd",
    "btn_green":"#238636",
    "btn_red":  "#b62324",
    # Agent colors
    "Derick":   "#388bfd",
    "Jef":      "#d2a8ff",
    "Zed":      "#3fb950",
    "Earl":     "#e3b341",
    "Chris":    "#f78166",
    "System":   "#f85149",
    # Event type colors
    "CYCLE_START":        "#388bfd",
    "CYCLE_END":          "#8b949e",
    "TASK_ADMITTED":      "#d2a8ff",
    "TASK_STARTED":       "#79c0ff",
    "TASK_COMPLETED":     "#3fb950",
    "TASK_BLOCKED":       "#f85149",
    "CODE_WRITTEN":       "#3fb950",
    "CODE_MODIFIED":      "#e3b341",
    "REVIEW_PASSED":      "#3fb950",
    "REVIEW_FAILED":      "#f85149",
    "EXECUTION_SUCCESS":  "#3fb950",
    "EXECUTION_CRASH":    "#f85149",
    "SYSTEM_ERROR":       "#f85149",
}

AGENTS = ["Derick", "Jef", "Zed", "Earl", "Chris"]
STATUS_DOT = {"idle": "⬤", "busy": "⬤", "error": "⬤"}
STATUS_COLOR = {"idle": C["dim"], "busy": C["btn_green"], "error": C["btn_red"]}


# ─────────────────────────────────────────────────────────────
# MAIN GUI CLASS
# ─────────────────────────────────────────────────────────────

class AlveaGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Axoloop Alvea")
        self.root.geometry("1280x800")
        self.root.minsize(1100, 700)
        self.root.configure(bg=C["bg"])

        self.log_queue: queue.Queue = queue.Queue()
        self.running = False
        self._agent_thread: Optional[threading.Thread] = None

        # ── Form variables ──────────────────────────────────
        self.arch_var   = tk.StringVar(value="Hexagonal")
        self.db_var     = tk.StringVar(value="Aucune")
        self.llm_url    = tk.StringVar(value="http://localhost:11434/v1")
        self.llm_model  = tk.StringVar(value="llama3")
        self.max_cycles = tk.IntVar(value=20)

        self.components: Dict[str, tk.BooleanVar] = {
            "Docker":              tk.BooleanVar(value=True),
            "Tests unitaires":     tk.BooleanVar(value=True),
            "Linting":             tk.BooleanVar(value=True),
            "Tests d'intégration": tk.BooleanVar(value=False),
            "CI/CD (GitHub Actions)": tk.BooleanVar(value=False),
            "REST API":            tk.BooleanVar(value=False),
            "GraphQL":             tk.BooleanVar(value=False),
            "Authentification JWT": tk.BooleanVar(value=False),
            "Documentation OpenAPI": tk.BooleanVar(value=False),
        }

        # ── Runtime state ────────────────────────────────────
        self._agent_status: Dict[str, Dict] = {
            a: {"status": "idle", "task": None, "action": None} for a in AGENTS
        }
        self._stats = {"cycle": 0, "completed": 0, "blocked": 0}

        self._build_ui()
        self._poll_queue()
        self.root.mainloop()

    # ─────────────────────────────────────────────────────────
    # UI CONSTRUCTION
    # ─────────────────────────────────────────────────────────

    def _build_ui(self):
        self._apply_ttk_style()

        # Header
        header = tk.Frame(self.root, bg=C["bg2"], height=48)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        tk.Label(
            header, text="🧠  AXOLOOP ALVEA",
            bg=C["bg2"], fg=C["text"],
            font=("Consolas", 16, "bold")
        ).pack(side="left", padx=20, pady=10)
        tk.Label(
            header, text="Multi-Agent Workflow Engine",
            bg=C["bg2"], fg=C["dim"],
            font=("Consolas", 10)
        ).pack(side="left", padx=0, pady=14)

        # Main paned layout
        paned = tk.PanedWindow(
            self.root, orient="horizontal",
            bg=C["border"], sashwidth=4, sashrelief="flat"
        )
        paned.pack(fill="both", expand=True, padx=0, pady=0)

        left = self._build_left_panel(paned)
        right = self._build_right_panel(paned)

        paned.add(left, minsize=340, width=390)
        paned.add(right, minsize=600)

    def _build_left_panel(self, parent) -> tk.Frame:
        frame = tk.Frame(parent, bg=C["bg"], padx=0, pady=0)

        # Scrollable canvas for the config form
        canvas = tk.Canvas(frame, bg=C["bg"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=C["bg"], padx=16, pady=12)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_window, width=event.width)

        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_configure)
        inner.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * int(e.delta / 120), "units"))

        # ── Sections ─────────────────────────────────────────

        self._section_label(inner, "📝  Description du projet")
        self.desc_text = tk.Text(
            inner, height=7, wrap="word",
            bg=C["bg3"], fg=C["text"], insertbackground=C["text"],
            relief="flat", bd=0, padx=8, pady=6,
            font=("Consolas", 10)
        )
        self.desc_text.pack(fill="x", pady=(0, 14))
        self.desc_text.insert("1.0", "Décris ici l'objectif de ton projet...")

        self._section_label(inner, "🏗  Architecture")
        arch_frame = tk.Frame(inner, bg=C["bg"])
        arch_frame.pack(fill="x", pady=(0, 14))
        for arch in ["Hexagonal", "Clean Architecture", "MVC", "Layered", "Microservices"]:
            tk.Radiobutton(
                arch_frame, text=arch, variable=self.arch_var, value=arch,
                bg=C["bg"], fg=C["text"], selectcolor=C["bg3"],
                activebackground=C["bg"], activeforeground=C["text"],
                font=("Consolas", 10)
            ).pack(anchor="w")

        self._section_label(inner, "📦  Composants")
        for label, var in self.components.items():
            tk.Checkbutton(
                inner, text=label, variable=var,
                bg=C["bg"], fg=C["text"], selectcolor=C["bg3"],
                activebackground=C["bg"], activeforeground=C["text"],
                font=("Consolas", 10)
            ).pack(anchor="w")
        tk.Frame(inner, bg=C["bg"], height=14).pack()

        self._section_label(inner, "🗄  Base de données")
        db_frame = tk.Frame(inner, bg=C["bg"])
        db_frame.pack(fill="x", pady=(0, 14))
        for db in ["Aucune", "PostgreSQL", "SQLite", "MongoDB", "Redis"]:
            tk.Radiobutton(
                db_frame, text=db, variable=self.db_var, value=db,
                bg=C["bg"], fg=C["text"], selectcolor=C["bg3"],
                activebackground=C["bg"], activeforeground=C["text"],
                font=("Consolas", 10)
            ).pack(anchor="w")

        self._section_label(inner, "🤖  LLM")
        self._form_row(inner, "URL", self.llm_url)
        self._form_row(inner, "Modèle", self.llm_model)
        tk.Frame(inner, bg=C["bg"], height=8).pack()
        self._form_row(inner, "Max cycles", self.max_cycles, width=6)
        tk.Frame(inner, bg=C["bg"], height=20).pack()

        # Launch button
        self.launch_btn = tk.Button(
            inner,
            text="▶  LANCER LES AGENTS",
            bg=C["btn_green"], fg="white",
            activebackground="#2ea043", activeforeground="white",
            font=("Consolas", 12, "bold"),
            relief="flat", bd=0, pady=10, cursor="hand2",
            command=self._toggle_run
        )
        self.launch_btn.pack(fill="x", pady=(0, 8))

        self.reset_btn = tk.Button(
            inner,
            text="↺  RESET",
            bg=C["bg3"], fg=C["dim"],
            activebackground=C["border"], activeforeground=C["text"],
            font=("Consolas", 10),
            relief="flat", bd=0, pady=6, cursor="hand2",
            command=self._reset
        )
        self.reset_btn.pack(fill="x")

        return frame

    def _build_right_panel(self, parent) -> tk.Frame:
        frame = tk.Frame(parent, bg=C["bg"])

        # ── Agent status grid ─────────────────────────────────
        agents_frame = tk.Frame(frame, bg=C["bg2"], pady=12, padx=16)
        agents_frame.pack(fill="x", padx=0, pady=0)

        tk.Label(
            agents_frame, text="AGENTS",
            bg=C["bg2"], fg=C["dim"],
            font=("Consolas", 9, "bold")
        ).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 8))

        self._agent_dot_labels: Dict[str, tk.Label] = {}
        self._agent_name_labels: Dict[str, tk.Label] = {}
        self._agent_task_labels: Dict[str, tk.Label] = {}

        for i, agent in enumerate(AGENTS):
            col_frame = tk.Frame(agents_frame, bg=C["bg3"], padx=12, pady=8)
            col_frame.grid(row=1, column=i, padx=(0, 8), sticky="nsew")
            agents_frame.columnconfigure(i, weight=1)

            dot = tk.Label(
                col_frame, text="⬤",
                bg=C["bg3"], fg=C["dim"],
                font=("Consolas", 14)
            )
            dot.pack()

            name = tk.Label(
                col_frame, text=agent,
                bg=C["bg3"], fg=C[agent],
                font=("Consolas", 11, "bold")
            )
            name.pack()

            task = tk.Label(
                col_frame, text="idle",
                bg=C["bg3"], fg=C["dim"],
                font=("Consolas", 8), wraplength=120
            )
            task.pack()

            self._agent_dot_labels[agent] = dot
            self._agent_name_labels[agent] = name
            self._agent_task_labels[agent] = task

        # ── Stats bar ─────────────────────────────────────────
        stats_frame = tk.Frame(frame, bg=C["bg2"], padx=16, pady=6)
        stats_frame.pack(fill="x")

        self._stat_labels: Dict[str, tk.Label] = {}
        for key, label in [("cycle", "Cycle"), ("completed", "Terminées"), ("blocked", "Bloquées")]:
            grp = tk.Frame(stats_frame, bg=C["bg2"])
            grp.pack(side="left", padx=(0, 24))
            tk.Label(grp, text=label.upper(), bg=C["bg2"], fg=C["dim"], font=("Consolas", 8)).pack(side="left", padx=(0, 6))
            lbl = tk.Label(grp, text="0", bg=C["bg2"], fg=C["text"], font=("Consolas", 11, "bold"))
            lbl.pack(side="left")
            self._stat_labels[key] = lbl

        # Status label (right-aligned)
        self._status_label = tk.Label(
            stats_frame, text="● EN ATTENTE",
            bg=C["bg2"], fg=C["dim"],
            font=("Consolas", 9)
        )
        self._status_label.pack(side="right")

        # ── Event log ─────────────────────────────────────────
        log_header = tk.Frame(frame, bg=C["bg2"], padx=16, pady=6)
        log_header.pack(fill="x")
        tk.Label(
            log_header, text="EVENTS LOG",
            bg=C["bg2"], fg=C["dim"],
            font=("Consolas", 9, "bold")
        ).pack(side="left")

        self.clear_btn = tk.Button(
            log_header, text="Vider",
            bg=C["bg2"], fg=C["dim"],
            activebackground=C["bg3"], activeforeground=C["text"],
            font=("Consolas", 8), relief="flat", bd=0, cursor="hand2",
            command=self._clear_log
        )
        self.clear_btn.pack(side="right")

        self.log_text = tk.Text(
            frame, wrap="word", state="disabled",
            bg=C["bg"], fg=C["text"],
            insertbackground=C["text"],
            relief="flat", bd=0, padx=12, pady=8,
            font=("Consolas", 10),
            selectbackground=C["bg3"]
        )
        log_scroll = ttk.Scrollbar(frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

        # Configure text tags (colors per agent / event type)
        for agent in AGENTS + ["System"]:
            self.log_text.tag_configure(f"agent_{agent}", foreground=C[agent], font=("Consolas", 10, "bold"))
        for event_type, color in C.items():
            if event_type.isupper():
                self.log_text.tag_configure(f"evt_{event_type}", foreground=color)
        self.log_text.tag_configure("ts", foreground=C["dim"])
        self.log_text.tag_configure("target", foreground=C["dim"])
        self.log_text.tag_configure("payload", foreground=C["text"])
        self.log_text.tag_configure("sep", foreground=C["border"])

        return frame

    # ─────────────────────────────────────────────────────────
    # UI HELPERS
    # ─────────────────────────────────────────────────────────

    def _section_label(self, parent, text: str):
        tk.Label(
            parent, text=text,
            bg=C["bg"], fg=C["dim"],
            font=("Consolas", 9, "bold")
        ).pack(anchor="w", pady=(8, 4))
        tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", pady=(0, 8))

    def _form_row(self, parent, label: str, var, width: int = 28):
        row = tk.Frame(parent, bg=C["bg"])
        row.pack(fill="x", pady=2)
        tk.Label(
            row, text=label, width=12, anchor="w",
            bg=C["bg"], fg=C["dim"], font=("Consolas", 10)
        ).pack(side="left")
        tk.Entry(
            row, textvariable=var, width=width,
            bg=C["bg3"], fg=C["text"], insertbackground=C["text"],
            relief="flat", bd=4, font=("Consolas", 10)
        ).pack(side="left")

    def _apply_ttk_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Vertical.TScrollbar",
                         background=C["bg3"],
                         troughcolor=C["bg2"],
                         bordercolor=C["bg"],
                         arrowcolor=C["dim"],
                         relief="flat")

    # ─────────────────────────────────────────────────────────
    # LAUNCH / STOP / RESET
    # ─────────────────────────────────────────────────────────

    def _toggle_run(self):
        if self.running:
            self._stop()
        else:
            self._launch()

    def _launch(self):
        description = self.desc_text.get("1.0", "end").strip()
        if not description or description == "Décris ici l'objectif de ton projet...":
            messagebox.showwarning("Champ requis", "Décris le projet avant de lancer.")
            return

        self.running = True
        self.launch_btn.configure(text="■  ARRÊTER", bg=C["btn_red"], activebackground="#da3633")
        self._set_status("● EN COURS", C["btn_green"])
        self._append_log("─" * 72 + "\n", "sep")
        self._append_log(
            f"[{self._now()}]  Démarrage — objectif : {description[:80]}\n",
            "ts"
        )

        self._agent_thread = threading.Thread(
            target=self._run_system,
            args=(description,),
            daemon=True
        )
        self._agent_thread.start()

    def _stop(self):
        self.running = False
        self.launch_btn.configure(text="▶  LANCER LES AGENTS", bg=C["btn_green"], activebackground="#2ea043")
        self._set_status("● ARRÊTÉ", C["btn_red"])

    def _reset(self):
        if self.running:
            self._stop()
        self._clear_log()
        for agent in AGENTS:
            self._update_agent_ui(agent, "idle", None, None)
        for key in self._stats:
            self._stats[key] = 0
            self._stat_labels[key].configure(text="0")
        self._set_status("● EN ATTENTE", C["dim"])

    # ─────────────────────────────────────────────────────────
    # BACKGROUND AGENT THREAD
    # ─────────────────────────────────────────────────────────

    def _run_system(self, description: str):
        """Runs in a background thread. Drives the full agent loop."""
        try:
            from core.event_bus import EventBus
            from core.planner_engine import PlannerEngine
            from core.task_manager import TaskManager
            from core.executor_runtime import ExecutorRuntime
            from core.llm_client import LocalLLM
            from agents.derick import Derick
            from agents.jef import Jef
            from agents.zed import Zed
            from agents.earl import Earl
            from agents.chris import Chris
            from core.file_utils import load_json, save_json

            # ── Build system ────────────────────────────────
            bus      = EventBus(log_path="runtime/events.log")
            planner  = PlannerEngine(plan_file="plan/plan.json")
            task_mgr = TaskManager(tasks_file="tasks/tasks.json")
            executor = ExecutorRuntime(workspace_dir="workspace")
            llm      = LocalLLM(base_url=self.llm_url.get(), model=self.llm_model.get())

            derick = Derick(bus, planner, task_mgr)
            jef    = Jef(bus, task_mgr, llm)
            zed    = Zed(bus, task_mgr, executor, llm)
            earl   = Earl(bus, task_mgr, executor, llm)
            chris  = Chris(bus, task_mgr, executor)

            # ── Subscribe ALL events to the queue ───────────
            for event_type in EventBus.ALLOWED_EVENTS:
                bus.subscribe(event_type, self._on_event)

            # ── Update vision.json from form ─────────────────
            self._update_vision(save_json)

            # ── Phase 1: Planning ────────────────────────────
            objective = self._build_objective(description)
            self._push_log_msg("Jef", f"Décomposition de l'objectif en cours...")
            task_ids = jef.plan_objective(objective)
            self._push_log_msg("Jef", f"{len(task_ids)} tâches créées : {task_ids}")

            # ── Phase 2: Orchestration loop ──────────────────
            for _ in range(self.max_cycles.get()):
                if not self.running:
                    break

                backlog = task_mgr.load_state()["backlog"]
                all_resolved = all(t["status"] in ("completed", "blocked") for t in backlog)
                if all_resolved:
                    self._push_log_msg("System", "Toutes les tâches sont résolues.")
                    break

                derick.run_cycle()
                self._sync_stats(planner, task_mgr)

                plan = planner.load_plan()
                for entry in plan["execution"]["in_progress"]:
                    if not self.running:
                        break

                    task_id = entry["task_id"]
                    assigned = entry["assigned_to"]

                    if assigned == "Zed":
                        try:
                            zed.implement_task(task_id)
                            derick.handoff_to_reviewer(task_id)
                        except Exception as e:
                            derick.fail_task(task_id, str(e))

                    elif assigned == "Earl":
                        try:
                            passed = earl.review_task(task_id)
                            if passed:
                                derick.handoff_to_executor(task_id)
                            else:
                                derick.fail_task(task_id, "Review échouée.")
                        except Exception as e:
                            derick.fail_task(task_id, str(e))

                    elif assigned == "Chris":
                        try:
                            success = chris.execute_task(task_id)
                            if success:
                                derick.complete_task(task_id)
                            else:
                                derick.fail_task(task_id, "Exécution échouée.")
                        except Exception as e:
                            derick.fail_task(task_id, str(e))

                self._sync_stats(planner, task_mgr)

            self.log_queue.put({"_type": "done"})

        except Exception as e:
            self.log_queue.put({"_type": "error", "message": str(e)})

    # ─────────────────────────────────────────────────────────
    # EVENT CALLBACK  (called from agent thread)
    # ─────────────────────────────────────────────────────────

    def _on_event(self, event: Dict[str, Any]):
        """EventBus callback — runs in agent thread. Safely pushes to queue."""
        self.log_queue.put({"_type": "event", "event": event})

    def _push_log_msg(self, agent: str, msg: str):
        """Push a plain text message from the agent thread."""
        self.log_queue.put({"_type": "msg", "agent": agent, "msg": msg})

    # ─────────────────────────────────────────────────────────
    # LOG RENDERING
    # ─────────────────────────────────────────────────────────

    def _render_event(self, ev: Dict[str, Any]):
        """Renders a structured EventBus event in the log."""
        agent      = ev.get("agent", "System")
        event_type = ev.get("event_type", "")
        target     = ev.get("target", "")
        payload    = ev.get("payload", {})
        cycle      = ev.get("cycle", 0)
        ts         = ev.get("timestamp", self._now())

        # Update agent status widget
        status = "busy" if event_type not in ("CYCLE_END", "TASK_COMPLETED", "REVIEW_PASSED", "EXECUTION_SUCCESS") else "idle"
        task_label = target if target not in ("system", "") else None
        self.log_queue.put({"_type": "_ui_agent", "agent": agent, "status": status, "task": task_label})

        # Compose log line
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts[11:23]}] ", "ts")
        self.log_text.insert("end", f"C{cycle:02d}  ", "ts")
        self.log_text.insert("end", f"{agent:<8}", f"agent_{agent}")
        self.log_text.insert("end", f"  {event_type:<22}", f"evt_{event_type}")
        if target and target != "system":
            self.log_text.insert("end", f"  → {target}", "target")
        # Show first meaningful payload field
        payload_hint = self._payload_hint(payload)
        if payload_hint:
            self.log_text.insert("end", f"  {payload_hint}", "payload")
        self.log_text.insert("end", "\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _render_msg(self, agent: str, msg: str):
        """Renders a plain informational message."""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{self._now()[11:23]}] ", "ts")
        self.log_text.insert("end", f"{agent:<8}", f"agent_{agent}")
        self.log_text.insert("end", f"  {msg}\n", "payload")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _payload_hint(self, payload: Dict) -> str:
        """Extracts a short readable hint from the payload dict."""
        for key in ("reason", "summary", "feedback", "error", "files", "issues"):
            val = payload.get(key)
            if val:
                text = val if isinstance(val, str) else str(val)
                return f"({text[:60]}…)" if len(text) > 60 else f"({text})"
        return ""

    # ─────────────────────────────────────────────────────────
    # AGENT STATUS UI UPDATE
    # ─────────────────────────────────────────────────────────

    def _update_agent_ui(self, agent: str, status: str, task: Optional[str], action: Optional[str]):
        dot = self._agent_dot_labels.get(agent)
        lbl = self._agent_task_labels.get(agent)
        if dot:
            dot.configure(fg=STATUS_COLOR.get(status, C["dim"]))
        if lbl:
            label_text = task or status
            lbl.configure(text=label_text[:18] if label_text else "idle")

    # ─────────────────────────────────────────────────────────
    # STATS SYNC
    # ─────────────────────────────────────────────────────────

    def _sync_stats(self, planner, task_mgr):
        """Reads plan.json and tasks.json to refresh the stats bar."""
        try:
            plan    = planner.load_plan()
            backlog = task_mgr.load_state()["backlog"]

            cycle     = plan.get("state", {}).get("cycle", plan.get("metrics", {}).get("completed_tasks", 0))
            completed = sum(1 for t in backlog if t["status"] == "completed")
            blocked   = sum(1 for t in backlog if t["status"] == "blocked")

            self.log_queue.put({"_type": "_stats",
                                 "cycle": cycle,
                                 "completed": completed,
                                 "blocked": blocked})
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────
    # QUEUE POLL  (GUI thread, every 100 ms)
    # ─────────────────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                kind = item.get("_type")

                if kind == "event":
                    self._render_event(item["event"])
                elif kind == "msg":
                    self._render_msg(item["agent"], item["msg"])
                elif kind == "_ui_agent":
                    self._update_agent_ui(item["agent"], item["status"], item.get("task"), None)
                elif kind == "_stats":
                    for key in ("cycle", "completed", "blocked"):
                        self._stat_labels[key].configure(text=str(item[key]))
                elif kind == "done":
                    self._stop()
                    self._append_log("\n✓  Exécution terminée.\n", "payload")
                    for a in AGENTS:
                        self._update_agent_ui(a, "idle", None, None)
                elif kind == "error":
                    self._stop()
                    self._append_log(f"\n✗  Erreur fatale : {item['message']}\n", "evt_SYSTEM_ERROR")

        except Exception:
            pass  # queue empty — normal

        self.root.after(100, self._poll_queue)

    # ─────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────

    def _append_log(self, text: str, tag: str = "payload"):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text, tag)
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_status(self, text: str, color: str):
        self._status_label.configure(text=text, fg=color)

    def _now(self) -> str:
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

    def _build_objective(self, description: str) -> str:
        """Builds the enriched objective string sent to Jef."""
        lines = [description.strip(), "", "Contraintes techniques :"]
        lines.append(f"- Architecture : {self.arch_var.get()}")

        selected = [k for k, v in self.components.items() if v.get()]
        if selected:
            for comp in selected:
                lines.append(f"- {comp} : oui")

        db = self.db_var.get()
        if db != "Aucune":
            lines.append(f"- Base de données : {db}")

        return "\n".join(lines)

    def _update_vision(self, save_json):
        """Writes selected options into vision.json before launch."""
        try:
            from core.file_utils import load_json
            vision = load_json("vision/vision.json")
            vision["architecture"]["style"] = self.arch_var.get()
            db = self.db_var.get()
            if db != "Aucune":
                vision["architecture"]["modules"] = [db]
            qc = vision.setdefault("quality_constraints", {})
            qc["tests_required"] = self.components["Tests unitaires"].get()
            qc["require_linting"] = self.components["Linting"].get()
            save_json("vision/vision.json", vision)
        except Exception:
            pass  # non-blocking


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Ensure we run from the project root
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    AlveaGUI()
