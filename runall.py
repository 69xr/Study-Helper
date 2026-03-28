"""
Launch the bot and dashboard together for local production-style operation.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _spawn(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, *args],
        cwd=ROOT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )


def main() -> int:
    procs = [
        ("bot", _spawn(["main.py"])),
        ("dashboard", _spawn(["dashboard/app.py"])),
    ]
    print("Started bot and dashboard. Press Ctrl+C to stop both.")

    try:
        while True:
            for name, proc in procs:
                code = proc.poll()
                if code is not None:
                    print(f"{name} exited with code {code}. Stopping the remaining process.")
                    raise RuntimeError
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutdown requested.")
    except RuntimeError:
        pass
    finally:
        for _, proc in procs:
            if proc.poll() is None:
                if os.name == "nt":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.terminate()
        for _, proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
