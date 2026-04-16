import json
import os
from typing import Any, Dict, Optional


def load_json(path: str) -> Dict[str, Any]:
    """Loads a JSON file and returns its content as a dict."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path: str, data: Dict[str, Any]):
    """Writes data to a JSON file with pretty formatting."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def ensure_file(path: str, init_content: Optional[Dict[str, Any]] = None):
    """Ensures the directory and file exist. Optionally writes initial JSON content."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        if init_content is not None:
            save_json(path, init_content)
        else:
            with open(path, 'a', encoding='utf-8'):
                pass
