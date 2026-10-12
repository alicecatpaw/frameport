"""One FramePort window at a time (core/instance.py)."""
import subprocess
import sys
import textwrap

from frameport.core import instance


def _hold_lock(path):
    """A separate process holding the GUI lock (like a running FramePort)."""
    code = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(instance.__file__.rsplit('/frameport/', 1)[0])!r})
        from pathlib import Path
        from frameport.core import instance
        assert instance.acquire(Path({str(path)!r}))
        print("locked", flush=True)
        time.sleep(30)
    """)
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "locked"
    return p


def test_second_start_is_refused_while_a_window_is_open(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAMEPORT_HOME", str(tmp_path))
    holder = _hold_lock(instance.lock_file())
    try:
        assert instance.holder() == holder.pid
        assert not instance.acquire()
        assert instance.claim(lambda: True) is False  # a window answers: it's asked to come to the front
        assert instance.take_focus_request() and not instance.take_focus_request()
        # no window answers, but the holder isn't a FramePort GUI (or is still starting): it's left alone
        assert instance.claim(lambda: False, retries=1) is False
        assert holder.poll() is None
    finally:
        holder.kill()
        holder.wait()
    assert instance.acquire()  # released by the OS when the holder ends


def test_leftover_frameport_gui_is_ended(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAMEPORT_HOME", str(tmp_path))
    holder = _hold_lock(instance.lock_file())
    monkeypatch.setattr(instance, "_is_frameport_gui", lambda pid: pid == holder.pid)
    monkeypatch.setattr(instance, "STARTUP_GRACE", 0.0)
    try:
        assert instance.claim(lambda: False) is True  # no window: the leftover process is ended, the lock taken
        assert holder.wait(5) is not None
    finally:
        if holder.poll() is None:
            holder.kill()
