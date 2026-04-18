import shutil
import subprocess
import os
from typing import Dict, Any, List

class ExecutorRuntime:
    """Physical execution engine. Chris's and Zed's primary tool."""

    # Tools to probe at runtime — used by Zed to choose safe setup_commands
    _TOOL_PROBES = [
        "python3", "python", "pip3", "pip",
        "node", "npm", "npx",
        "sqlite3",
        "git", "curl", "wget",
        "docker", "docker-compose",
    ]

    def __init__(self, workspace_dir: str = "workspace"):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self._ensure_workspace()

    # ==========================================
    # INITIALIZATION
    # ==========================================

    def _ensure_workspace(self):
        os.makedirs(self.workspace_dir, exist_ok=True)

    # ==========================================
    # TOOL DETECTION
    # ==========================================

    def detect_tools(self) -> Dict[str, bool]:
        """
        Returns a dict {tool_name: available} for common execution tools.
        Uses shutil.which — fast, cross-platform, no subprocess overhead.
        """
        return {tool: shutil.which(tool) is not None for tool in self._TOOL_PROBES}

    def tools_summary(self) -> str:
        """
        Returns a human-readable, newline-separated summary of available tools.
        Designed to be injected into Zed's prompt.
        """
        availability = self.detect_tools()
        available   = [t for t, ok in availability.items() if ok]
        unavailable = [t for t, ok in availability.items() if not ok]

        lines = ["Execution environment (tools available in workspace):"]
        lines.append(f"  ✓ Available : {', '.join(available) or 'none'}")
        if unavailable:
            lines.append(f"  ✗ Missing   : {', '.join(unavailable)}")

        # Actionable hints for common missing tools
        if not availability.get("node") and not availability.get("npm"):
            lines.append(
                "  → Node.js/npm/npx are NOT installed. "
                "Do NOT use npx or npm in setup_commands. "
                "For JS/TS projects, write all files manually. "
                "For Next.js / React scaffolding, write the file tree by hand."
            )
        if not availability.get("sqlite3"):
            py = "python3" if availability.get("python3") else "python"
            lines.append(
                f"  → sqlite3 CLI is NOT installed. "
                f"Use Python's built-in sqlite3 module instead: "
                f"write an init_db.py script and add '{py} init_db.py' to setup_commands."
            )

        return "\n".join(lines)

    # ==========================================
    # COMMAND EXECUTION
    # ==========================================

    def run_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Executes a shell command strictly within the workspace directory.
        """
        try:
            result = subprocess.run(
                command,
                cwd=self.workspace_dir,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return {
                "success":   result.returncode == 0,
                "exit_code": result.returncode,
                "stdout":    result.stdout.strip(),
                "stderr":    result.stderr.strip(),
            }
        except subprocess.TimeoutExpired:
            return {
                "success":   False,
                "exit_code": -1,
                "stdout":    "",
                "stderr":    f"Timeout exceeded after {timeout} seconds.",
            }
        except Exception as e:
            return {
                "success":   False,
                "exit_code": -2,
                "stdout":    "",
                "stderr":    str(e),
            }

    # ==========================================
    # FILE MANIPULATION
    # ==========================================

    def write_file(self, relative_path: str, content: str):
        full_path = os.path.join(self.workspace_dir, relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    def list_files(self) -> List[str]:
        """Returns all file paths in workspace/, relative to workspace/."""
        result = []
        for root, _, files in os.walk(self.workspace_dir):
            for name in files:
                full = os.path.join(root, name)
                rel  = os.path.relpath(full, self.workspace_dir).replace("\\", "/")
                result.append(rel)
        return sorted(result)

    def read_file(self, relative_path: str) -> str:
        full_path = os.path.join(self.workspace_dir, relative_path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File {relative_path} does not exist in the workspace.")
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
