import os
import re
import json
from typing import Dict, Any, List

from agents.base_agent import BaseAgent
from core.event_bus import EventBus
from core.task_manager import TaskManager
from core.executor_runtime import ExecutorRuntime
from core.llm_client import LocalLLM
from core.file_utils import load_json

# Standard Python library modules — not expected in workspace
_STDLIB = {
    "os", "sys", "re", "json", "math", "io", "time", "datetime", "pathlib",
    "typing", "collections", "itertools", "functools", "copy", "abc",
    "threading", "subprocess", "shutil", "tempfile", "hashlib", "base64",
    "urllib", "http", "socket", "logging", "unittest", "dataclasses",
    "contextlib", "enum", "random", "string", "struct", "traceback",
    "inspect", "ast", "argparse", "csv", "sqlite3", "pickle", "uuid",
    "warnings", "weakref", "operator", "textwrap", "pprint",
}

# Common third-party packages — not in workspace
_THIRD_PARTY = {
    "flask", "django", "fastapi", "requests", "httpx", "aiohttp",
    "sqlalchemy", "pydantic", "pytest", "numpy", "pandas", "openai",
    "anthropic", "boto3", "celery", "redis", "pymongo", "psycopg2",
    "dotenv", "click", "typer", "uvicorn", "starlette", "jinja2",
    "werkzeug", "marshmallow", "alembic", "tortoise", "beanie",
    "motor", "pymysql", "peewee", "attrs", "dacite",
}


class Earl(BaseAgent):
    """
    Reviewer. Validates code produced by Zed against quality and vision constraints.

    Now also performs:
    - Static import verification (Python, JS, HTML references)
    - Workspace folder structure check (all declared outputs exist)
    """

    SYSTEM_PROMPT = """You are Earl, a strict senior code reviewer inside a multi-agent system.

Your ONLY job is to review code produced by Zed and determine if it meets all quality constraints.

Evaluation criteria (ALL must pass — any single failure = passed: false):
1. Correctness: Does the code logically accomplish what the task describes?
2. Completeness: Are all expected output files present and fully implemented?
3. Architecture: Does the code respect single responsibility and clean separation of concerns?
4. Quality: No dead code, no obvious bugs, no hardcoded secrets, no bare except clauses.
5. Conformance: Does the code respect any constraints declared in vision_constraints?
6. No placeholders: REJECT immediately if any file contains:
   - Empty function or method bodies (only a comment or only "pass")
   - "# Your code here", "# TODO", "# implement this", "# test code here", or similar
   - Imports from fictional modules ("your_module", "my_module", "xxx_module")
   - Test methods with no assertions (just comments or pass)
   - Any stub that is not real, working code
7. Integration: If integration constraints are listed, verify every required reference/import/link is present.
8. Relevance: Does the implementation match the project type? A pure frontend task must not introduce unnecessary server-side code. Tests must import real symbols that exist in the project.

If PRE-DETECTED STATIC ISSUES are listed above the code, treat each one as a confirmed failure — do not re-evaluate them, just include them in your issues list.

Respond ONLY with a valid JSON object in this exact format:
{
  "passed": true,
  "issues": [],
  "feedback": "Brief summary of the review outcome"
}

If passed is false, 'issues' must be a non-empty list of specific, actionable problem descriptions.
Be precise: name the file, the offending pattern, and what the correct implementation should be."""

    def __init__(
        self,
        event_bus: EventBus,
        task_manager: TaskManager,
        executor: ExecutorRuntime,
        llm: LocalLLM,
        vision_file: str = "vision/vision.json",
        state_file: str = "runtime/state.json"
    ):
        super().__init__("Earl", event_bus, state_file)
        self.tasks = task_manager
        self.executor = executor
        self.llm = llm
        self.vision_file = vision_file

    # ==========================================
    # MAIN ACTION
    # ==========================================

    def review_task(self, task_id: str) -> dict:
        """
        Reviews all files produced for the given task.
        Returns {"passed": bool, "issues": list, "feedback": str}.
        """
        task = self._get_task(task_id)
        if not task:
            raise ValueError(f"Earl: task '{task_id}' not found in backlog.")

        self.update_status("busy", current_task=task_id, last_action="REVIEWING")
        cycle = self.get_current_cycle()

        code_files = self._read_output_files(task)
        if not code_files:
            reason = "No output files found in workspace — Zed may not have written anything."
            self._publish_failed(task_id, [reason], reason, cycle)
            return {"passed": False, "issues": [reason], "feedback": reason}

        try:
            vision = load_json(self.vision_file)
        except Exception:
            vision = {}

        try:
            existing_files = self.executor.list_files()
        except Exception:
            existing_files = []

        # Static import + structure verification (before LLM)
        static_issues = self._check_static_imports(code_files, existing_files)
        static_issues += self._check_folder_structure(task, existing_files)

        user_prompt = self._build_prompt(task, code_files, vision, existing_files, static_issues)
        response = self.llm.ask_json(self.SYSTEM_PROMPT, user_prompt)

        passed = response.get("passed", False)
        issues = response.get("issues", [])
        feedback = response.get("feedback", "")

        # If static issues were found, force failed regardless of LLM
        if static_issues and passed:
            passed = False
            issues = static_issues + issues
            feedback = f"Static analysis detected {len(static_issues)} issue(s). " + feedback

        if passed:
            self.event_bus.publish(
                agent="Earl",
                event_type="REVIEW_PASSED",
                target=task_id,
                payload={"task_id": task_id, "feedback": feedback},
                current_cycle=cycle
            )
            self.update_status("idle", current_task=None, last_action=f"REVIEW_PASSED:{task_id}")
        else:
            self._publish_failed(task_id, issues, feedback, cycle)

        return {"passed": passed, "issues": issues, "feedback": feedback}

    # ==========================================
    # STATIC ANALYSIS
    # ==========================================

    def _check_static_imports(
        self, code_files: List[Dict[str, str]], existing_files: List[str]
    ) -> List[str]:
        """
        Checks that all imports and references in code files point to
        files that exist in workspace/ or are known third-party packages.
        Returns list of error strings.
        """
        errors = []
        existing_set = set(existing_files)

        for file_entry in code_files:
            path = file_entry["path"]
            content = file_entry["content"]
            if content == "[FILE NOT FOUND]":
                continue

            ext = os.path.splitext(path)[1].lower()
            file_dir = os.path.dirname(path)

            if ext == ".py":
                errors.extend(self._check_python_imports(path, content, existing_set))
            elif ext in (".js", ".ts", ".mjs"):
                errors.extend(self._check_js_imports(path, file_dir, content, existing_set))
            elif ext == ".html":
                errors.extend(self._check_html_refs(path, file_dir, content, existing_set))

        return errors

    def _check_python_imports(
        self, file_path: str, content: str, existing_files: set
    ) -> List[str]:
        errors = []
        for line in content.splitlines():
            line = line.strip()

            # from X import Y  →  check X as a local module
            m = re.match(r"^from\s+([\w.]+)\s+import", line)
            if m:
                module = m.group(1).split(".")[0]
                if module not in _STDLIB and module not in _THIRD_PARTY:
                    candidate_py = f"{module}.py"
                    candidate_pkg = f"{module}/__init__.py"
                    if candidate_py not in existing_files and candidate_pkg not in existing_files:
                        errors.append(
                            f"{file_path}: imports from '{module}' but '{candidate_py}' "
                            f"does not exist in workspace/"
                        )
                continue

            # import X  →  simple top-level import
            m = re.match(r"^import\s+([\w.]+)", line)
            if m:
                module = m.group(1).split(".")[0]
                if module not in _STDLIB and module not in _THIRD_PARTY:
                    candidate_py = f"{module}.py"
                    candidate_pkg = f"{module}/__init__.py"
                    if candidate_py not in existing_files and candidate_pkg not in existing_files:
                        errors.append(
                            f"{file_path}: imports '{module}' but '{candidate_py}' "
                            f"does not exist in workspace/"
                        )

        return errors

    def _check_js_imports(
        self, file_path: str, file_dir: str, content: str, existing_files: set
    ) -> List[str]:
        errors = []
        # import ... from './X' or require('./X') — relative only
        pattern = re.compile(
            r"""(?:import\s+.*?from\s+|require\s*\(\s*)['"](\./[^'"]+|\.\.\/[^'"]+)['"]""",
            re.DOTALL
        )
        for ref in pattern.findall(content):
            resolved = os.path.normpath(os.path.join(file_dir, ref)).replace("\\", "/")
            # Try with and without .js extension
            candidates = [resolved, resolved + ".js", resolved + ".ts"]
            if not any(c in existing_files for c in candidates):
                errors.append(
                    f"{file_path}: imports '{ref}' but the file does not exist in workspace/"
                )
        return errors

    def _check_html_refs(
        self, file_path: str, file_dir: str, content: str, existing_files: set
    ) -> List[str]:
        errors = []
        for value in re.findall(r'(?:src|href)=["\']([^"\']+)["\']', content):
            if (value.startswith("http") or value.startswith("//") or
                    value.startswith("#") or value.startswith("data:") or
                    "${" in value or value == "/"):
                continue
            if value.startswith("/"):
                resolved = value.lstrip("/")
            else:
                resolved = os.path.normpath(os.path.join(file_dir, value)).replace("\\", "/")
            if resolved and resolved not in existing_files:
                errors.append(
                    f"{file_path}: references '{value}' "
                    f"(→ {resolved}) which does not exist in workspace/"
                )
        return errors

    def _check_folder_structure(
        self, task: Dict[str, Any], existing_files: List[str]
    ) -> List[str]:
        """
        Verifies that all declared output files for this task are present in workspace/.
        """
        errors = []
        existing_set = set(existing_files)
        for output in task.get("outputs", []):
            rel = output.replace("workspace/", "", 1) if output.startswith("workspace/") else output
            if rel and rel not in existing_set:
                errors.append(
                    f"Declared output '{rel}' is missing from workspace/ "
                    f"(folder structure incomplete)"
                )
        return errors

    # ==========================================
    # PRIVATE HELPERS
    # ==========================================

    def _get_task(self, task_id: str) -> Dict[str, Any] | None:
        backlog = self.tasks.load_state()["backlog"]
        return next((t for t in backlog if t["id"] == task_id), None)

    def _read_output_files(self, task: Dict[str, Any]) -> List[Dict[str, str]]:
        result = []
        for output_path in task.get("outputs", []):
            rel_path = (
                output_path.replace("workspace/", "", 1)
                if output_path.startswith("workspace/")
                else output_path
            )
            try:
                content = self.executor.read_file(rel_path)
                result.append({"path": rel_path, "content": content})
            except FileNotFoundError:
                result.append({"path": rel_path, "content": "[FILE NOT FOUND]"})
        return result

    def _build_prompt(
        self,
        task: Dict[str, Any],
        code_files: List[Dict[str, str]],
        vision: Dict[str, Any],
        existing_files: List[str] = None,
        static_issues: List[str] = None,
    ) -> str:
        lines = [
            "=== TASK TO REVIEW ===",
            f"ID: {task['id']}",
            f"Title: {task['title']}",
            f"Description: {task['description']}",
            f"Expected outputs: {task.get('outputs', [])}",
            "",
        ]

        # Pre-detected static issues — injected before the code so LLM treats them as confirmed
        if static_issues:
            lines.append("=== PRE-DETECTED STATIC ISSUES (confirmed failures) ===")
            lines.append(
                "The following issues were detected by static analysis BEFORE the LLM review. "
                "Treat each as a confirmed bug — include all of them in the 'issues' list and set passed=false."
            )
            for issue in static_issues:
                lines.append(f"  ✗ {issue}")
            lines.append("")

        if existing_files:
            lines.append("=== EXISTING WORKSPACE FILES ===")
            lines.append("Imports and references must point to files in this list:")
            for f in existing_files:
                lines.append(f"  - {f}")
            lines.append("")

        quality = vision.get("quality_constraints", {})
        forbidden = [p for p in vision.get("forbidden_patterns", []) if p]
        if quality or forbidden:
            lines.append("=== VISION CONSTRAINTS ===")
            if quality.get("require_linting"):
                lines.append("- Linting is required (no unused imports, correct style)")
            if quality.get("tests_required"):
                lines.append("- Tests are required for all logic")
            if quality.get("max_function_length") and quality["max_function_length"] > 0:
                lines.append(f"- Max function length: {quality['max_function_length']} lines")
            for pattern in forbidden:
                lines.append(f"- Forbidden pattern: {pattern}")
            lines.append("")

        try:
            all_tasks = self.tasks.load_state()["backlog"]
            dependents = [t for t in all_tasks if task["id"] in t.get("dependencies", [])]
            if dependents:
                lines.append("=== INTEGRATION CONSTRAINTS ===")
                lines.append(
                    "This task has dependents. The code under review MUST reference/import/link these files:"
                )
                for dep in dependents:
                    for output in dep.get("outputs", []):
                        clean = output.replace("workspace/", "", 1) if output.startswith("workspace/") else output
                        lines.append(f"  - {clean}  ({dep['id']}: {dep['title']})")
                lines.append("If any of these references are missing, mark passed=false.")
                lines.append("")
        except Exception:
            pass

        lines.append("=== CODE TO REVIEW ===")
        for file_entry in code_files:
            lines.append(f"\n--- {file_entry['path']} ---")
            lines.append(file_entry["content"])

        return "\n".join(lines)

    def _publish_failed(self, task_id: str, issues: List[str], feedback: str, cycle: int):
        self.event_bus.publish(
            agent="Earl",
            event_type="REVIEW_FAILED",
            target=task_id,
            payload={"task_id": task_id, "issues": issues, "feedback": feedback},
            current_cycle=cycle
        )
        self.update_status("idle", current_task=None, last_action=f"REVIEW_FAILED:{task_id}")
