"""Cpp2IL (SamboyCoding/Cpp2IL, MIT): reads an IL2CPP Unity game's libil2cpp.so + global-metadata.dat and lists every
method with its address. FramePort needs it only for Unity games whose text fields it fixes (frame.unity_text_input),
so it is downloaded on first use into <user data>/tools/ (a self-contained executable per OS; no .NET install).

Its current releases are all pre-releases (the 2022.1 line is the one that reads Unity 6 / metadata v31), so the
newest release with an asset for this computer is used. Override: FRAMEPORT_CPP2IL=<path to the executable>."""
from __future__ import annotations

import os
import platform
import stat
import sys
from pathlib import Path

from ..core import cache
from ..core.paths import tools_dir

RELEASES = "https://api.github.com/repos/SamboyCoding/Cpp2IL/releases"


def asset_suffix() -> str:
    """Release asset suffix for this computer, e.g. Linux, Linux-ARM64, OSX-ARM64, Windows.exe."""
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if sys.platform == "win32":
        return "Windows-ARM64.exe" if arm else "Windows.exe"
    if sys.platform == "darwin":
        return "OSX-ARM64" if arm else "OSX"
    return "Linux-ARM64" if arm else "Linux"


def _exe_name() -> str:
    return "Cpp2IL.exe" if sys.platform == "win32" else "Cpp2IL"


def pick_release(releases: list[dict], suffix: str) -> tuple[str, str] | None:
    """(version, download url) of the newest release that has an executable for this computer."""
    for rel in releases:
        for asset in rel.get("assets", []):
            if asset.get("name", "").endswith("-" + suffix):
                return rel.get("tag_name", "?"), asset["browser_download_url"]
    return None


def path() -> Path | None:
    if os.environ.get("FRAMEPORT_CPP2IL"):
        return Path(os.environ["FRAMEPORT_CPP2IL"])
    found = sorted(tools_dir().glob(f"cpp2il-*/{_exe_name()}"))  # the data folder may hold other OSes' copies too
    return found[-1] if found else None


def installed_version() -> str | None:
    p = path()
    return p.parent.name.removeprefix("cpp2il-") if p is not None and p.parent.name.startswith("cpp2il-") else None


def ensure(progress=None) -> Path:
    """The Cpp2IL executable, downloading it first if needed."""
    existing = path()
    if existing is not None and existing.exists():
        return existing
    releases = cache.cached_json("cpp2il-releases.json", RELEASES, max_age=7 * 86400, fallback=[]) or []
    picked = pick_release(releases, asset_suffix())
    if picked is None:
        raise RuntimeError("couldn't find a Cpp2IL download for this computer")
    version, url = picked
    exe = tools_dir() / f"cpp2il-{version}" / _exe_name()
    cache.download(url, exe, progress)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return exe
