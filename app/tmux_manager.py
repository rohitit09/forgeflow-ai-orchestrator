import subprocess
import time
from typing import Optional


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def is_installed() -> bool:
    return _run(["which", "tmux"]).returncode == 0


def has_session(name: str) -> bool:
    return _run(["tmux", "has-session", "-t", name]).returncode == 0


def create_session(name: str, working_dir: Optional[str] = None, extra_env: Optional[dict] = None) -> bool:
    args = ["tmux", "new-session", "-d", "-s", name, "-x", "220", "-y", "50"]
    if working_dir:
        args += ["-c", working_dir]
    for k, v in (extra_env or {}).items():
        args += ["-e", f"{k}={v}"]
    return _run(args).returncode == 0


def kill_session(name: str) -> bool:
    return _run(["tmux", "kill-session", "-t", name]).returncode == 0


_CHUNK_SIZE = 400  # tmux send-keys -l stalls on large strings; chunk to stay under terminal input buffer limits

def send_keys(name: str, keys: str, enter: bool = True) -> bool:
    # -l sends the string literally so URL characters (://) don't get mis-interpreted
    if keys:
        for i in range(0, len(keys), _CHUNK_SIZE):
            chunk = keys[i:i + _CHUNK_SIZE]
            if _run(["tmux", "send-keys", "-t", name, "-l", chunk]).returncode != 0:
                return False
            if i + _CHUNK_SIZE < len(keys):
                time.sleep(0.05)  # let the terminal input buffer drain between chunks
    if enter:
        return _run(["tmux", "send-keys", "-t", name, "Enter"]).returncode == 0
    return True


def list_sessions() -> list[str]:
    result = _run(["tmux", "list-sessions", "-F", "#S"])
    if result.returncode != 0:
        return []
    return [s.strip() for s in result.stdout.splitlines() if s.strip()]


def capture_pane(name: str, lines: int = 30) -> str:
    """Return current pane text."""
    result = _run(["tmux", "capture-pane", "-t", name, "-p", "-S", f"-{lines}"])
    return result.stdout if result.returncode == 0 else ""


def resize_window(name: str, cols: int, rows: int) -> bool:
    return _run(["tmux", "resize-window", "-t", name, "-x", str(cols), "-y", str(rows)]).returncode == 0
