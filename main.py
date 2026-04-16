"""
Axoloop Alvea — Entry point.

Launches a local web interface on http://localhost:5000

Usage:
    python main.py
"""

import os
import threading
import webbrowser

from web.server import PORT, start_server


def _open_browser():
    import time
    time.sleep(0.8)
    webbrowser.open(f"http://localhost:{PORT}")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    threading.Thread(target=_open_browser, daemon=True).start()
    start_server()
