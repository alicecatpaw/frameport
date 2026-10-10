"""The app's own log (<data>/logs/app.log, rotated) and saved job logs (<data>/logs/jobs/), for diagnostics bundles."""
from __future__ import annotations

import logging
import logging.handlers
import re
import sys
import time
from pathlib import Path

from .paths import user_data_dir

log = logging.getLogger("frameport")
KEEP_JOB_LOGS = 30


def logs_dir() -> Path:
    path = user_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def jobs_dir() -> Path:
    path = logs_dir() / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_log_path() -> Path:
    return logs_dir() / "app.log"


def setup(component: str = "app") -> None:
    """Log to <data>/logs/app.log (2 MB × 3). Safe to call more than once; also records uncaught exceptions."""
    from .paths import removed

    if removed() or any(getattr(h, "_frameport", False) for h in log.handlers):
        return
    try:
        handler = logging.handlers.RotatingFileHandler(app_log_path(), maxBytes=2 << 20, backupCount=3,
                                                       encoding="utf-8")
    except OSError:
        return
    handler._frameport = True
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    flet_log = logging.getLogger("flet")
    flet_log.addHandler(handler)
    flet_log.setLevel(logging.INFO)
    root_log = logging.getLogger()
    if not any(getattr(h, "_frameport", False) for h in root_log.handlers):
        root_log.addHandler(handler)
    log.info("start %s: %s (python %s, %s)", component, _version(), sys.version.split()[0], sys.platform)
    previous = sys.excepthook

    def hook(kind, exc, tb):
        log.error("uncaught exception", exc_info=(kind, exc, tb))
        previous(kind, exc, tb)
    sys.excepthook = hook


def _version() -> str:
    from .. import __version__

    return __version__


def shutdown() -> None:
    """Close the log file (uninstall: an open file can't be deleted on Windows)."""
    for l in (log, logging.getLogger("flet"), logging.getLogger()):
        for h in [h for h in l.handlers if getattr(h, "_frameport", False)]:
            l.removeHandler(h)
            h.close()


def save_job_log(kind: str, package: str | None, state: str, text: str) -> Path | None:
    """Keep a finished job's log (the GUI only holds it in memory); the last KEEP_JOB_LOGS are kept."""
    from .paths import removed

    if removed():
        return None
    try:
        d = jobs_dir()
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{kind}-{package or 'app'}-{state}")[:120]
        path = d / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}.log"
        path.write_text(text, encoding="utf-8", errors="replace")
        for old in sorted(d.glob("*.log"))[:-KEEP_JOB_LOGS]:
            old.unlink(missing_ok=True)
        return path
    except OSError:
        return None
