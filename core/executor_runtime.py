import subprocess
import os
from typing import Dict, Any

class ExecutorRuntime:
    """Physical execution engine. Chris's primary tool."""

    def __init__(self, workspace_dir: str = "workspace"):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self._ensure_workspace()

    # ==========================================
    # INITIALIZATION
    # ==========================================
    def _ensure_workspace(self):
        os.makedirs(self.workspace_dir, exist_ok=True)

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
                "success": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()
            }
            
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Timeout exceeded after {timeout} seconds."
            }
        except Exception as e:
            return {
                "success": False,
                "exit_code": -2,
                "stdout": "",
                "stderr": str(e)
            }

    # ==========================================
    # SIMPLE FILE MANIPULATION
    # ==========================================
    def write_file(self, relative_path: str, content: str):
        """Fallback tool or for Zed if direct writing is needed."""
        full_path = os.path.join(self.workspace_dir, relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)

    def read_file(self, relative_path: str) -> str:
        """Useful for Earl during code review."""
        full_path = os.path.join(self.workspace_dir, relative_path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File {relative_path} does not exist in the workspace.")
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()