"""Filesystem locations: bundled data (catalog, artifacts, agent) and the per-user data directory."""
from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent
# Installed wheel: data is force-included under frameport/_data. Source checkout: repo root.
_REPO = _PKG.parent.parent
DATA_ROOT = _PKG / "_data" if (_PKG / "_data").is_dir() else _REPO


def catalog_dir() -> Path:
    return DATA_ROOT / "catalog"


def artifacts_dir() -> Path:
    return DATA_ROOT / "artifacts"


def agent_dir() -> Path:
    return DATA_ROOT / "agent"


AGENT_SOURCE_COPY = "frameport_agent.py.txt"  # scripts/package.py stages this next to the .py


def agent_file() -> Path:
    """The Frame agent's source (uploaded to the Frame and run there with python3). `flet build` compiles every .py
    of the app to .pyc and drops the source, bundled data included (issue #2: no connection from the release
    bundles), so bundles also carry a copy under a non-.py name."""
    path = agent_dir() / "frameport_agent.py"
    return path if path.exists() else agent_dir() / AGENT_SOURCE_COPY


def bootstrap_dir() -> Path:
    return DATA_ROOT / "bootstrap"


def _on_frame() -> bool:
    from ..frame.local import on_frame

    return on_frame()


def shares_windows_data() -> bool:
    """WSL with FRAMEPORT_WINDOWS_DATA=1: use the Windows FramePort's data folder (one library for a Windows copy and
    WSL source runs; paths the other side saved are translated by `localize`)."""
    if not os.environ.get("FRAMEPORT_WINDOWS_DATA") or os.environ.get("FRAMEPORT_HOME"):
        return False
    from .winhost import is_wsl

    return is_wsl()


_win_data: list = []  # cached: finding %LOCALAPPDATA% from WSL starts cmd.exe


def _windows_data_dir() -> Path | None:
    if not _win_data:
        from .winhost import env_path

        local = env_path("LOCALAPPDATA")
        _win_data.append(local / "FramePort" if local else None)
    return _win_data[0]


def user_data_dir() -> Path:
    """Tools, keystores, work dirs and settings. Override with FRAMEPORT_HOME."""
    if os.environ.get("FRAMEPORT_HOME"):
        base = Path(os.environ["FRAMEPORT_HOME"])
    elif shares_windows_data() and _windows_data_dir() is not None:
        base = _windows_data_dir()
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "FramePort"
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support/FramePort"
    else:
        # on the Frame itself ~/.local/share/frameport is the agent's folder (and its purge removes it): the app's own
        # data (library, tools, game signing keys) lives next to it
        name = "frameport-app" if _on_frame() else "frameport"
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / name
    if not _removed.is_set():
        base.mkdir(parents=True, exist_ok=True)
    return base


_WSL_DRIVE = re.compile(r"^/mnt/([a-zA-Z])(?:/(.*))?$")
_WIN_DRIVE = re.compile(r"^([a-zA-Z]):[\\/](.*)$")


def local_path(p: str) -> str:
    """A path saved by FramePort on the other side of WSL in this side's spelling: /mnt/d/X -> D:\\X on Windows, and
    D:\\X -> /mnt/d/X in WSL runs on the Windows copy's data (`shares_windows_data`); anything else unchanged.
    Plain string mapping (drive letters only), so it is cheap enough for whole files."""
    if sys.platform == "win32":
        m = _WSL_DRIVE.match(p)
        return f"{m[1].upper()}:\\" + (m[2] or "").replace("/", "\\") if m else p
    if shares_windows_data():
        m = _WIN_DRIVE.match(p)
        if m:
            return f"/mnt/{m[1].lower()}" + ("/" + m[2].replace("\\", "/") if m[2] else "")
    return p


def localize(obj):
    """`local_path` applied to every string in loaded JSON (library.json, deployment records, tools.json): a data
    folder shared by a Windows copy and WSL source runs holds paths from both."""
    if isinstance(obj, str):
        return local_path(obj) if obj[:1] in "/" or obj[1:3] in (":\\", ":/") else obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = localize(v)
    elif isinstance(obj, list):
        obj[:] = [localize(v) for v in obj]
    return obj


_removed = threading.Event()


def mark_removed() -> None:
    """FramePort is being uninstalled: from now on nothing may (re)create files in the data folder."""
    _removed.set()


def removed() -> bool:
    return _removed.is_set()


def tools_dir() -> Path:
    return _sub("tools")


def work_dir() -> Path:
    return _sub("work")


def output_dir() -> Path:
    return _sub("output")


def ssh_dir() -> Path:
    return _sub("ssh")


def _sub(name: str) -> Path:
    path = user_data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_atomic(path: Path, text: str) -> None:
    """Replace a file in one step: a reader never sees it half written, and a crash leaves the old one."""
    path = Path(path)
    if removed():
        return
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
