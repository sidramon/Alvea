import json
from core.event_bus import EventBus
from core.file_utils import load_json, save_json


class BaseAgent:
    """Base class for all Axoloop Alvea agents."""

    def __init__(self, name: str, event_bus: EventBus, state_file: str = "runtime/state.json"):
        self.name = name
        self.event_bus = event_bus
        self.state_file = state_file

    def update_status(self, status: str, current_task: str = None, last_action: str = None):
        """Updates the agent's status in state.json."""
        try:
            state = load_json(self.state_file)
            state["agents_activity"][self.name].update({
                "status": status,
                "current_task": current_task,
                "last_action": last_action
            })
            save_json(self.state_file, state)
        except FileNotFoundError:
            print(f"[ERROR] {self.name}: state file not found at '{self.state_file}'")
        except json.JSONDecodeError as e:
            print(f"[ERROR] {self.name}: corrupted JSON in state file: {e}")
        except KeyError:
            print(f"[ERROR] {self.name}: agent key not found in agents_activity")

    def get_current_cycle(self) -> int:
        """Retrieves the current cycle for logging purposes."""
        try:
            state = load_json(self.state_file)
            return state.get("engine", {}).get("current_cycle", 0)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return 0
