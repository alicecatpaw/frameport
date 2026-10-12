"""One FramePort window at a time (no Flet).

Two GUI processes on one data folder fought over library.json and both re-analysed the library and triaged the same
play sessions (the Library flickered under a stream of pop-ups). The GUI holds an exclusive lock on
`<data>/gui.lock` for its lifetime (released by the OS when the process ends, also after a crash). A second start:
- the window is there (fresh `gui.alive` heartbeat): asks it to come to the front (`gui.focus`) and exits;
- the lock is held but no window answers (a process left over after its window went away): ends that process (only
  when it is a FramePort GUI) and takes over.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .paths import user_data_dir

_held = None  # the open lock file (kept for the process lifetime)


def lock_file() -> Path:
    return user_data_dir() / "gui.lock"


def focus_file() -> Path:
    return user_data_dir() / "gui.focus"


def _try_lock(f) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def acquire(path: Path | None = None) -> bool:
    """Take the GUI lock; False when another process holds it."""
    global _held
    path = path or lock_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")  # noqa: SIM115 (kept open on purpose)
    if not _try_lock(f):
        f.close()
        return False
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    _held = f
    return True


def holder(path: Path | None = None) -> int | None:
    try:
        return int((path or lock_file()).read_text().strip() or 0) or None
    except (OSError, ValueError):
        return None


def _is_frameport_gui(pid: int) -> bool:
    try:
        import psutil

        cmd = " ".join(psutil.Process(pid).cmdline()).lower()
    except Exception:  # noqa: BLE001 (gone, or not ours to inspect)
        return False
    return "frameport" in cmd


STARTUP_GRACE = 30.0  # a GUI this young may still be opening its window (no heartbeat yet): never end it


def end_leftover(pid: int, wait: float = 5.0) -> bool:
    """End a FramePort GUI process that has no window any more; True when it's gone."""
    if pid == os.getpid() or not _is_frameport_gui(pid):
        return False
    import psutil

    try:
        p = psutil.Process(pid)
        if time.time() - p.create_time() < STARTUP_GRACE:
            return False
        p.terminate()
        try:
            p.wait(wait)
        except psutil.TimeoutExpired:
            p.kill()
            p.wait(wait)
    except psutil.NoSuchProcess:
        pass
    except Exception:  # noqa: BLE001
        return False
    return True


def ask_focus() -> None:
    try:
        focus_file().touch()
    except OSError:
        pass


def take_focus_request() -> bool:
    """True once after another start asked the window to come to the front."""
    try:
        focus_file().unlink()
        return True
    except OSError:
        return False


def claim(window_open, retries: int = 20) -> bool:
    """Called at GUI start: True = this process is the GUI; False = another window is open (it was asked to come to
    the front). `window_open()` says whether a window answers (urlhandler.app_running)."""
    if acquire():
        return True
    if window_open():
        ask_focus()
        return False
    pid = holder()
    if pid:
        end_leftover(pid)
    for _ in range(retries):  # the OS releases the lock when the process is gone
        if acquire():
            return True
        time.sleep(0.25)
    if window_open():
        ask_focus()
    return False
