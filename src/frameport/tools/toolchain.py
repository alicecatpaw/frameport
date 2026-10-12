"""Portable toolchain: FramePort manages its own Java, OVRPort CLI and apksigner (no admin rights, no PATH edits).

Everything is resolved dynamically (latest versions from their official sources, checksummed) and installed into
<user data>/tools/. Overrides for development: FRAMEPORT_JAVA, FRAMEPORT_OVERPORT_JAR, FRAMEPORT_APKSIGNER_JAR.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from ..core import cache
from ..core.paths import localize, tools_dir, write_atomic

ADOPTIUM = "https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture={arch}&image_type=jre&os={os}"
# overport's CLI: maintained in the downstream fork Android-XR-Bridge/OVRPort since 1.2.5 (stable channel = plain
# vX.Y.Z tags with an `OVRPort-<ver>-stable-cli.jar`); the original ovrport/app (`cli-jar.zip`) is the fallback.
OVERPORT_RELEASES = [("overport-release-ovrport.json",
                      "https://api.github.com/repos/Android-XR-Bridge/OVRPort/releases/latest"),
                     ("overport-release.json", "https://api.github.com/repos/ovrport/app/releases/latest")]
ANDROID_REPO = "https://dl.google.com/android/repository/"


@dataclass
class ToolStatus:
    name: str
    installed: bool
    version: str | None
    path: Path | None
    latest: str | None = None
    detail: str = ""
    optional: bool = False  # only needed for some games (Revive: Rift/PC VR games)


def _os_arch() -> tuple[str, str]:
    osname = {"win32": "windows", "darwin": "mac"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x64"
    return osname, arch


def _state_file() -> Path:
    return tools_dir() / "tools.json"


def _state() -> dict:
    try:
        return localize(json.loads(_state_file().read_text()))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    write_atomic(_state_file(), json.dumps(state, indent=2))


# ------------------------------------------------------------------------------------------ Java
def _java_key() -> str:
    """The Java entry of tools.json: one per OS, since a data folder can be shared by Windows and WSL."""
    return "java-{}-{}".format(*_os_arch())


def java_path() -> Path | None:
    if os.environ.get("FRAMEPORT_JAVA"):
        return Path(os.environ["FRAMEPORT_JAVA"])
    state = _state()
    st = state.get(_java_key())
    if not st and state.get("java"):  # before 1.0.4: one entry; it's this OS's if it has this OS's java name
        st = state["java"] if Path(state["java"]["path"]).name == _java_exe() else None
    if st and Path(st["path"]).exists():
        return Path(st["path"])
    return None


def _java_exe() -> str:
    return "java.exe" if sys.platform == "win32" else "java"


def install_java(progress=None) -> ToolStatus:
    osname, arch = _os_arch()
    info = cache.http_get(ADOPTIUM.format(os=osname, arch=arch)).json()[0]
    pkg = info["binary"]["package"]
    version = info["version"]["semver"]
    dest = tools_dir() / f"jre-{version}-{osname}-{arch}"
    if not dest.exists():
        archive = cache.download(pkg["link"], tools_dir() / pkg["name"], progress, expected_sha256=pkg["checksum"])
        tmp = tools_dir() / f".jre-{version}-{osname}-{arch}.extract"
        shutil.rmtree(tmp, ignore_errors=True)
        _extract(archive, tmp)
        top = next(tmp.iterdir())
        top.rename(dest)
        shutil.rmtree(tmp, ignore_errors=True)
        archive.unlink(missing_ok=True)
    exe = _java_exe()
    candidates = [dest / "bin" / exe, dest / "Contents/Home/bin" / exe]
    java = next(p for p in candidates if p.exists())
    if sys.platform != "win32":
        java.chmod(0o755)
    state = _state()
    state[_java_key()] = {"version": version, "path": str(java)}
    _save_state(state)
    return ToolStatus("java", True, version, java)


def _extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="tar") if hasattr(tarfile, "data_filter") else t.extractall(dest)


# ------------------------------------------------------------------------------------------ overport
def overport_jar() -> Path | None:
    if os.environ.get("FRAMEPORT_OVERPORT_JAR"):
        return Path(os.environ["FRAMEPORT_OVERPORT_JAR"])
    st = _state().get("overport")
    if st and Path(st["path"]).exists():
        return Path(st["path"])
    return None


def _overport_asset(rel: dict) -> dict | None:
    """The CLI asset of a release: a stable `*-cli.jar` (fork) or `cli-jar.zip` (ovrport/app)."""
    assets = rel.get("assets", [])
    return (next((a for a in assets if a["name"].endswith("-stable-cli.jar")), None)
            or next((a for a in assets if a["name"].endswith("-cli.jar")), None)
            or next((a for a in assets if a["name"] == "cli-jar.zip"), None))


def latest_overport() -> tuple[str, str] | None:
    """(version, download url) of the newest OVRPort CLI, from the first source that has one."""
    for cache_name, url in OVERPORT_RELEASES:
        rel = cache.cached_json(cache_name, url, max_age=6 * 3600)
        if not rel or rel.get("draft") or rel.get("prerelease"):
            continue
        asset = _overport_asset(rel)
        if asset:
            return rel["tag_name"].removeprefix("v"), asset["browser_download_url"]
    return None


def install_overport(progress=None) -> ToolStatus:
    latest = latest_overport()
    if not latest:
        raise RuntimeError("could not reach GitHub to find the latest OVRPort release")
    version, url = latest
    dest = tools_dir() / f"overport-{version}"
    jar = next(dest.glob("*.jar"), None) if dest.exists() else None
    if not jar:
        name = url.rsplit("/", 1)[1]
        if name.endswith(".jar"):
            dest.mkdir(parents=True, exist_ok=True)
            jar = cache.download(url, dest / name, progress)
        else:
            archive = cache.download(url, tools_dir() / f"overport-{version}.zip", progress)
            with zipfile.ZipFile(archive) as z:
                members = [m for m in z.namelist() if m.endswith(".jar")]
                dest.mkdir(parents=True, exist_ok=True)
                for m in members:
                    (dest / Path(m).name).write_bytes(z.read(m))
            archive.unlink(missing_ok=True)
            jar = next(dest.glob("*.jar"))
    state = _state()
    state["overport"] = {"version": version, "path": str(jar)}
    _save_state(state)
    return ToolStatus("overport", True, version, jar)


# ------------------------------------------------------------------------------------------ apksigner
def apksigner_jar() -> Path | None:
    if os.environ.get("FRAMEPORT_APKSIGNER_JAR"):
        return Path(os.environ["FRAMEPORT_APKSIGNER_JAR"])
    st = _state().get("apksigner")
    if st and Path(st["path"]).exists():
        return Path(st["path"])
    return None


def latest_build_tools() -> tuple[str, str, str] | None:
    """(version, zip url, sha1) of the newest stable Android build-tools (the apksigner jar is OS-independent)."""
    text = cache.cached_text("android-repository2-3.xml", ANDROID_REPO + "repository2-3.xml", max_age=7 * 86400)
    if not text:
        return None
    root = ElementTree.fromstring(text)
    best = None
    for pkg in root.iter("remotePackage"):
        path = pkg.get("path", "")
        if not path.startswith("build-tools;") or "rc" in path:
            continue
        chan = pkg.find("channelRef")
        if chan is not None and chan.get("ref") != "channel-0":
            continue
        version = path.split(";")[1]
        for archive in pkg.iter("archive"):
            host = archive.findtext("host-os")
            if host not in (None, "linux"):
                continue
            url = archive.findtext("complete/url")
            sha1 = archive.findtext("complete/checksum")
            key = tuple(int(x) for x in re.findall(r"\d+", version))
            if url and (best is None or key > best[0]):
                best = (key, version, ANDROID_REPO + url, sha1)
    return best[1:] if best else None


def install_apksigner(progress=None) -> ToolStatus:
    latest = latest_build_tools()
    if not latest:
        raise RuntimeError("could not read Google's Android repository index")
    version, url, sha1 = latest
    dest = tools_dir() / f"apksigner-{version}.jar"
    if not dest.exists():
        archive = cache.download(url, tools_dir() / f"build-tools-{version}.zip", progress, expected_sha1=sha1)
        with zipfile.ZipFile(archive) as z:
            member = next(m for m in z.namelist() if m.endswith("lib/apksigner.jar"))
            dest.write_bytes(z.read(member))
        archive.unlink(missing_ok=True)
    state = _state()
    state["apksigner"] = {"version": version, "path": str(dest)}
    _save_state(state)
    return ToolStatus("apksigner", True, version, dest)


# ------------------------------------------------------------------------------------------ status / all
def status(check_latest: bool = False, include_optional: bool = True) -> list[ToolStatus]:
    st = _state()
    out = []
    for name, getter in (("java", java_path), ("overport", overport_jar), ("apksigner", apksigner_jar)):
        path = getter()
        version = (st.get(name) or {}).get("version") if path else None
        if path and name == "java" and os.environ.get("FRAMEPORT_JAVA"):
            version = "external"
        latest = None
        if check_latest:
            try:
                latest = {"overport": lambda: (latest_overport() or (None,))[0],
                          "apksigner": lambda: (latest_build_tools() or (None,))[0],
                          "java": lambda: None}[name]()
            except Exception:
                latest = None
        out.append(ToolStatus(name, bool(path and path.exists()), version, path, latest))
    if not include_optional:
        return out
    from . import revive

    rdir = revive.revive_dir()
    latest = None
    if check_latest:
        try:
            latest = (revive.latest() or (None,))[0]
        except Exception:
            latest = None
    where = {"system": "your installed Revive", "env": "FRAMEPORT_REVIVE_DIR", "managed": "FramePort's copy"}.get(
        revive.source() or "", "")
    out.append(ToolStatus("revive", rdir is not None, revive.installed_version(), rdir, latest,
                          "Revive (LibreVR): runs Oculus Rift games on OpenXR/SteamVR"
                          + (f" · using {where}" if where else ""), optional=True))
    return out


def revive_is_users() -> bool:
    from . import revive

    return revive.source() in ("env", "system")


def install_revive(progress=None) -> ToolStatus:
    from . import revive

    path = revive.install(progress)
    return ToolStatus("revive", True, revive.installed_version(), path, optional=True)


def ensure_all(progress=None, update: bool = False, optional: bool = False) -> list[ToolStatus]:
    """Install whatever is missing (or outdated when update=True). Optional tools only with optional=True or when
    already installed (then they are updated like the others)."""
    results = []
    for s in status(check_latest=update):
        if s.optional and not optional and not s.installed:
            results.append(s)
            continue
        if s.name == "revive" and s.installed and revive_is_users():
            results.append(s)  # never replace a Revive the user installed themselves
            continue
        if s.installed and not (update and s.latest and s.version and s.latest != s.version
                                and s.version != "external"):
            results.append(s)
            continue
        installer = {"java": install_java, "overport": install_overport, "apksigner": install_apksigner,
                     "revive": install_revive}[s.name]
        results.append(installer(progress))
    return results


def java_cmd(*args: str) -> list[str]:
    java = java_path()
    if not java:
        raise RuntimeError("Java is not installed; run `frameport tools install`")
    return [str(java), "-Djava.awt.headless=true", *args]


def run_java(args: list[str], cwd: Path | None = None, timeout: float | None = None) -> subprocess.CompletedProcess:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(java_cmd(*args), cwd=cwd, capture_output=True, text=True, errors="replace",
                          timeout=timeout, **kwargs)
