import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Callable, List

from core.file_utils import ensure_file


class EventBus:
    """
    Central event manager for Axoloop Alvea.
    Ensures immutability of the events.log file and message routing.
    """

    ALLOWED_AGENTS = {"System", "Derick", "Jef", "Zed", "Earl", "Chris"}

    ALLOWED_EVENTS = {
        "CYCLE_START", "CYCLE_END",
        "TASK_ADMITTED", "TASK_STARTED", "TASK_COMPLETED", "TASK_BLOCKED",
        "CODE_WRITTEN", "CODE_MODIFIED",
        "REVIEW_PASSED", "REVIEW_FAILED",
        "EXECUTION_SUCCESS", "EXECUTION_CRASH",
        "SYSTEM_ERROR"
    }

    def __init__(self, log_path: str = "runtime/events.log"):
        self.log_path = log_path
        self._subscribers: Dict[str, List[Callable]] = {event: [] for event in self.ALLOWED_EVENTS}
        ensure_file(self.log_path)

    def subscribe(self, event_type: str, callback: Callable[[Dict[str, Any]], None]):
        """Allows an agent to subscribe to a specific event type."""
        if event_type not in self.ALLOWED_EVENTS:
            raise ValueError(f"Event type not allowed for subscription: {event_type}")
        self._subscribers[event_type].append(callback)

    def publish(self, agent: str, event_type: str, target: str, payload: Dict[str, Any], current_cycle: int) -> Dict[str, Any]:
        """
        Publishes an event, writes it immutably to the log,
        and alerts subscribed agents.
        """
        # 1. Strict validation
        if agent not in self.ALLOWED_AGENTS:
            raise ValueError(f"Unknown agent: {agent}")
        if event_type not in self.ALLOWED_EVENTS:
            raise ValueError(f"Illegal event detected: {event_type}")

        # 2. ISO 8601 formatting (with milliseconds and 'Z')
        timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

        # 3. Build event object
        event_obj = {
            "timestamp": timestamp,
            "cycle": current_cycle,
            "agent": agent,
            "event_type": event_type,
            "target": target,
            "payload": payload
        }

        # 4. Persistence (Append-only, JSONL)
        self._write_to_log(event_obj)

        # 5. Broadcast to subscribers (Event-Driven)
        self._notify_subscribers(event_type, event_obj)

        return event_obj

    def _write_to_log(self, event_obj: Dict[str, Any]):
        """Writes the event on a single line (JSONL) in append-only mode."""
        # Note: Mode 'a' ensures we cannot overwrite history
        with open(self.log_path, 'a', encoding='utf-8') as f:
            # separators=(',', ':') removes spaces for pure, dense JSONL
            json_string = json.dumps(event_obj, ensure_ascii=False, separators=(',', ':'))
            f.write(json_string + '\n')

    def _notify_subscribers(self, event_type: str, event_obj: Dict[str, Any]):
        """Triggers callbacks of agents listening to this event."""
        for callback in self._subscribers.get(event_type, []):
            try:
                callback(event_obj)
            except Exception as e:
                # Write directly to log to avoid recursive publish() calls
                error_event = {
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                    "cycle": event_obj["cycle"],
                    "agent": "System",
                    "event_type": "SYSTEM_ERROR",
                    "target": f"callback_{callback.__name__}",
                    "payload": {"error": str(e), "original_event": event_obj}
                }
                self._write_to_log(error_event)

    def replay_history(self) -> List[Dict[str, Any]]:
        """Loads the entire history to reconstruct state (useful for startup or crash recovery)."""
        history = []
        with open(self.log_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    history.append(json.loads(line))
        return history
