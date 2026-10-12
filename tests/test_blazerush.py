"""BlazeRush (GitHub #57, Klownicle's guide): frame.blazerush's exact-match library edits, the GL shim's integer
attributes and highp markers, the VrApi bridge's saved FOV, device.config_sync in the agent, and the catalog recipe."""
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest

from frameport.analysis import elf
from frameport.core.models import Analysis
from frameport.patches import base
from frameport.patches.frame import artifact
from frameport.patches.frame import blazerush as br
from frameport.patches.settings import adapter_settings
from frameport.validate.triage import triage

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).with_name("fixtures")
AGENT = ROOT / "agent" / "frameport_agent.py"
MARKERS = "in uvec2 inBoneIndices;|uniform InstanceData|void main()"


def _analysis(**kw):
    d = dict(package=br.PACKAGE, version="1.0.349", label="BlazeRush", abis=["arm64-v8a"], engine="Other", xr="VrApi",
             graphics="GLES or unknown (no Vulkan declaration)", direct_vrapi=True,
             libs=["libtargemapp.so", "libvrapi.so", "libovravatarloader.so", "libovrplatformloader.so"],
             launcher_activity="ru.targem.BootstrappedNativeActivity", has_info_category=False, meta_permissions=[],
             uses_glad_gl=False, unity_msaa_levels=0, oculus_os_classes=False, is_overport_output=False,
             debuggable=True, extra={})
    d.update(kw)
    return Analysis(**d)


# ---- a small AArch64 shared object laid out like libtargemapp.so: read-only data first (vaddr == file offset), code
# in a second PT_LOAD whose virtual addresses are 0x1000 above its file offsets
TEXT_OFF, TEXT_VA, TEXT_SIZE = 0x2000, 0x3000, 0x1000
SITE_A, SITE_B, CACHE_VA = 0x3100, 0x3200, 0x1100


def _fake_lib(word_a=0x36000AE0, word_b=0xF0002368, cache=br.OLD_CACHE, extra_cache=False):
    data = bytearray(TEXT_OFF + TEXT_SIZE)
    phoff, phnum = 64, 2
    data[:16] = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into("<HHIQQQIHHHHHH", data, 16, 3, br.EM_AARCH64, 1, 0, phoff, 0, 0, 64, 56, phnum, 64, 0, 0)
    struct.pack_into("<IIQQQQQQ", data, phoff, 1, 4, 0, 0, 0, 0x2000, 0x2000, 0x1000)  # R
    struct.pack_into("<IIQQQQQQ", data, phoff + 56, 1, 5, TEXT_OFF, TEXT_VA, TEXT_VA, TEXT_SIZE, TEXT_SIZE, 0x1000)
    for i in range(TEXT_SIZE // 4):  # some code
        struct.pack_into("<I", data, TEXT_OFF + 4 * i, 0xD503201F ^ (i * 2654435761 & 0xFFFF))
    struct.pack_into("<I", data, SITE_A - TEXT_VA + TEXT_OFF, word_a)
    struct.pack_into("<I", data, SITE_B - TEXT_VA + TEXT_OFF, word_b)
    data[CACHE_VA:CACHE_VA + len(cache)] = cache
    if extra_cache:
        data[0x1800:0x1800 + len(br.OLD_CACHE)] = br.OLD_CACHE
    return bytes(data)


@pytest.fixture
def fake_build(monkeypatch):
    lib = _fake_lib()
    code = lib[TEXT_OFF:TEXT_OFF + TEXT_SIZE]
    build = br.Build("1.0.349", hashlib.sha256(code).hexdigest(),
                     ((SITE_A, 0x36000AE0, br.NOP, "wait"), (SITE_B, 0xF0002368, br.RET, "render")), CACHE_VA)
    monkeypatch.setattr(br, "BUILDS", (build,))
    return lib


def test_edits_use_the_segments_file_offsets(fake_build):
    new, site = br.patch_library(fake_build)
    assert site and site["build"] == "1.0.349" and not site["done"]
    # file offset = vaddr - 0x1000 here: computed from PT_LOAD, not assumed
    assert struct.unpack_from("<I", new, SITE_A - 0x1000)[0] == br.NOP
    assert struct.unpack_from("<I", new, SITE_B - 0x1000)[0] == br.RET
    assert new[CACHE_VA:CACHE_VA + len(br.NEW_CACHE)] == br.NEW_CACHE and br.OLD_CACHE not in new
    assert sum(a != b for a, b in zip(new, fake_build, strict=True)) <= 8 + len(br.NEW_CACHE)  # only the edits
    again, site2 = br.patch_library(new)  # an already patched library is recognised and left alone
    assert again == new and site2["done"] and site2["pending"] == []


def test_partly_patched_library_is_completed(fake_build):
    half = bytearray(fake_build)
    struct.pack_into("<I", half, SITE_A - 0x1000, br.NOP)
    new, site = br.patch_library(bytes(half))
    assert site["pending"] == ["render", "shader cache namespace"]
    assert br.find_sites(new)["done"]


@pytest.mark.parametrize("kw", [dict(word_a=0x12345678), dict(word_b=br.NOP), dict(cache=b"cache/shader_cachX\0"),
                                dict(extra_cache=True)])
def test_anything_unexpected_is_refused(fake_build, kw):
    lib = _fake_lib(**kw)
    assert br.find_sites(lib) is None
    assert br.patch_library(lib) == (lib, None)


def test_other_code_is_refused(fake_build):
    lib = bytearray(fake_build)
    lib[TEXT_OFF + 0x800] ^= 1  # another build: same words at the sites, different code
    assert br.find_sites(bytes(lib)) is None
    assert br.find_sites(fake_build.replace(b"\xb7\x00", b"\x3e\x00", 1)) is None  # not AArch64


class _Ws:
    abi = "arm64-v8a"

    def __init__(self, libs):
        self.files = {f"lib/arm64-v8a/{k}": v for k, v in libs.items()}

    def lib(self, name):
        return f"lib/arm64-v8a/{name}"

    def has(self, path):
        return path in self.files

    def read_lib(self, name):
        return self.files[self.lib(name)]

    def put(self, path, data):
        self.files[path] = data


def test_patch_apply_and_validate(fake_build):
    from types import SimpleNamespace

    p = base.get("frame.blazerush")
    ctx = SimpleNamespace(ws=_Ws({br.LIB: fake_build}), notes=[])
    assert p.apply(ctx) and "cache/br_shader_v1" in ctx.notes[0]
    assert p.validate(ctx) == [("BlazeRush avatar wait skipped and own shader cache", True, "")]
    assert not p.apply(ctx)  # nothing left to do
    other = SimpleNamespace(ws=_Ws({br.LIB: _fake_lib(word_a=0)}), notes=[])
    assert not p.apply(other) and "left unchanged" in other.notes[0]
    assert other.ws.read_lib(br.LIB) == _fake_lib(word_a=0)


def test_detect_and_applies():
    p = base.get("frame.blazerush")
    assert p.applies(_analysis()) and p.detect(_analysis()).recommended
    assert p.detect(_analysis(version="1.0.350")) is None  # another build: not suggested (apply would refuse it)
    assert not p.applies(_analysis(package="com.other.game"))
    assert not p.applies(_analysis(abis=["armeabi-v7a"]))


def test_known_build_fingerprint_is_the_shipped_library():
    """The fingerprint and sites come from the shipped 1.0.349 library (SHA-256 89686ffc...): its code segment is
    0x2c29d0 + 0x606230 in the file, the edit sites at 0x4b1dbc / 0x4b1adc, the string at 0x13af70."""
    (build,) = br.BUILDS
    assert build.version == "1.0.349" and build.cache_va == 0x13AF70
    assert [s[:3] for s in build.sites] == [(0x4B2DBC, 0x36000AE0, br.NOP), (0x4B2ADC, 0xF0002368, br.RET)]
    assert len(br.OLD_CACHE) == len(br.NEW_CACHE) == 19


def _blazerush_apk():
    root = os.environ.get("FRAMEPORT_GAMES")
    if not root:
        pytest.skip("set FRAMEPORT_GAMES")
    found = sorted(Path(root).glob("**/ru.targem.blazerush.apk"))
    if not found:
        pytest.skip("no BlazeRush APK in FRAMEPORT_GAMES")
    return found[0]


@pytest.mark.games
def test_real_library(tmp_path):
    with zipfile.ZipFile(_blazerush_apk()) as z:
        lib = z.read("lib/arm64-v8a/libtargemapp.so")
    assert hashlib.sha256(lib).hexdigest() == "89686ffc5105f5149adf9bf08d88eafdd4e8e99a3cd14d1ac9cc0d3317dfe568"
    new, site = br.patch_library(lib)
    assert [e[0] for e in site["edits"]] == [0x4B1DBC, 0x4B1ADC] and site["cache_offset"] == 0x13AF70
    # still recognised after the GL shim's DT_NEEDED entry (a new segment; nothing that exists moves)
    shimmed = elf.add_needed(new, "libglshim.so")
    assert br.find_sites(shimmed)["done"] and elf.needed(shimmed)[0] == "libglshim.so"


# ---- recipe
def test_catalog_recipe():
    from frameport.core.library import recipe_to_dict
    from frameport.install.installer import install_context
    from frameport.recommend import catalog
    from frameport.recommend.engine import suggest

    entry = catalog.lookup(br.PACKAGE)
    assert entry.status == "works" and "Klownicle" in entry.notes and entry.min_app == "1.0.0"
    recipe = suggest(_analysis())
    for pid in ("frame.vrapi_bridge", "frame.avatar_stub", "frame.gl_shim", "frame.blazerush", "device.config_sync"):
        assert pid in recipe.patches, pid
    s = adapter_settings(recipe.patches)
    assert s["scale"] == 1.7 and s["gl_int_attribs"] == 1 and s["gl_highp_markers"] == MARKERS
    assert s["gl_hide_multiview"] == 0 and s["gl_hide_msrtt"] == 0  # the game's GL extensions stay as tested
    ctx = install_context(recipe)
    assert ctx.config_sync == {"user_config.xml": {"r_3dwidth": "w", "r_3dheight": "h", "r_width": "h*16/9",
                                                    "r_height": "h"}}
    shared = catalog.entry_from_library({"package": br.PACKAGE, "title": "BlazeRush", "recipe": recipe_to_dict(recipe),
                                         "analysis": {"version": "1.0.349"}})
    assert shared.config_sync == entry.config_sync and catalog.unusable_reason(
        {**entry.to_dict(), "min_app": ""}) is None


def test_issue_validator_accepts_config_sync():
    spec = importlib.util.spec_from_file_location("catalog_from_issue", ROOT / "scripts" / "catalog_from_issue.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    d = {"package": br.PACKAGE, "title": "BlazeRush", "config_sync": {"user_config.xml": {"r_width": "h*16/9"}}}
    assert mod.validate(d).config_sync == d["config_sync"]
    with pytest.raises(mod.Invalid):
        mod.validate({**d, "config_sync": {"../x.xml": {"a": "w"}}})


def test_new_settings_need_a_rebuild():
    assert base.get("adapter.gl_int_attribs").revision == 2 and base.get("adapter.gl_highp_markers").revision == 2


def test_triage_signatures():
    log = ("10-10 10:00:00.000 1 1 I OVRPortVrApi: FOV properties: 90.00 x 90.00 degrees (default, nothing known "
           "before tracking)\n10-10 10:00:01.000 1 1 I GLShim: int attribs: program 12 location 3: floats -> "
           "glVertexAttribIPointer (vao 4 buffer 9 size 4 type 0x1401 stride 32 offset 0x18)\n")
    ids = {f.id for f in triage(log).findings}
    assert {"vrapi-fov-before-tracking", "gl-integer-attribs"} <= ids
    saved = "I OVRPortVrApi: FOV properties: 118.14 x 119.55 degrees (saved by an earlier session)\n"
    assert "vrapi-fov-before-tracking" not in {f.id for f in triage(saved).findings}


# ---- native code built for the host
def _cc():
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc or os.name == "nt" or not Path("/proc").exists():
        pytest.skip("needs a Linux host C compiler")
    return cc


def _khronos_headers(dest: Path) -> Path:
    candidates = [Path("/usr/include")]
    candidates += sorted((ROOT / "native/.cache").glob("ndk-*/toolchains/llvm/prebuilt/*/sysroot/usr/include"))
    for inc in candidates:
        if all((inc / d).is_dir() for d in ("GLES3", "EGL", "KHR")):
            for d in ("GLES3", "EGL", "KHR"):
                shutil.copytree(inc / d, dest / d)
            return dest
    pytest.skip("needs the GLES3/EGL/KHR headers (libgles-dev, or the NDK in native/.cache)")


def test_gl_shim_fixes_against_a_stand_in_gl(tmp_path):
    """glshim.c itself, built for the host: BlazeRush's particle shader source gets highp calculations (interface
    lines and other shaders untouched); an integer input fed with glVertexAttribPointer is set up again with
    glVertexAttribIPointer before direct and eglGetProcAddress draws (same buffer/offset, GL_ARRAY_BUFFER restored),
    back to normalized floats for a float input, typed default when disabled, re-reflected after a relink or a program
    binary, cached per context. With the settings off, nothing changes."""
    cc = _cc()
    inc = _khronos_headers(tmp_path / "include")
    src, out = FIXTURES / "src", tmp_path / "lib"
    out.mkdir()
    warn = ["-Wall", "-Wextra", "-Werror"]
    subprocess.run([cc, "-std=gnu11", *warn, "-shared", "-fPIC", "-fvisibility=hidden", "-I", str(inc),
                    str(src / "glshim_fake_gles.c"), "-Wl,-soname,libglshim_fake.so", "-ldl",
                    "-o", str(out / "libglshim_fake.so")], check=True)
    subprocess.run([cc, "-std=gnu11", *warn, "-Wno-unused-function", "-Wno-unused-variable",
                    "-Wno-unused-but-set-variable", "-Wno-incompatible-pointer-types", "-shared", "-fPIC",
                    "-fvisibility=hidden", "-DEGL_NO_X11", '-DGLSHIM_GLES_LIB="libglshim_fake.so"',
                    '-DGLSHIM_EGL_LIB="libglshim_fake.so"', "-I", str(src / "host_include"), "-I", str(inc),
                    str(ROOT / "native/glshim/glshim.c"), "-Wl,--no-as-needed", "-L", str(out), "-lglshim_fake",
                    "-Wl,--as-needed", "-Wl,-rpath,$ORIGIN", "-ldl", "-lpthread",
                    "-o", str(out / "libglshim_host.so")], check=True)
    subprocess.run([cc, "-std=gnu11", *warn, "-I", str(inc), str(src / "glshim_host_test.c"), "-ldl",
                    "-o", str(out / "glshim_host_test")], check=True)
    conf = tmp_path / "settings.conf"
    conf.write_text(f"scale=1.7\ngl_hide_multiview=0\ngl_hide_msrtt=0\ngl_int_attribs=1\ngl_highp_markers={MARKERS}\n")
    env = {k: v for k, v in os.environ.items() if k != "FRAMEBRIDGE_CONFIG"}
    cmd = [str(out / "glshim_host_test"), str(out / "libglshim_host.so"), str(out / "libglshim_fake.so")]
    run = subprocess.run([*cmd, "on"], capture_output=True, text=True, env={**env, "FRAMEBRIDGE_CONFIG": str(conf)})
    assert run.returncode == 0, run.stdout + run.stderr
    assert f"GL shim per-game fixes: gl_int_attribs=1 gl_highp_markers={MARKERS}" in run.stderr
    assert "GLShim: highp: vertex shader 1: 3 mediump -> highp" in run.stderr
    assert "GLShim: int attribs: program 1 has integer input inBoneIndices (unsigned) at location 3" in run.stderr
    assert "location 3: floats -> glVertexAttribIPointer" in run.stderr and "location 3: back to floats" in run.stderr
    run = subprocess.run([*cmd, "off"], capture_output=True, text=True, env=env)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "per-game fixes" not in run.stderr and "int attribs" not in run.stderr


def test_bridge_fov_cache_helpers(tmp_path):
    cxx = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if not cxx or os.name == "nt":
        pytest.skip("needs a host C++ compiler")
    test = tmp_path / "fov.cpp"
    test.write_text(r'''
#include "fov_cache.h"
#include <cstdio>
using namespace ovp::fovcache;
#define CHECK(c) do { if (!(c)) { std::printf("FAIL %d\n", __LINE__); return 1; } } while (0)
int main() {
    float fov[2], none[2] = {0, 0};
    CHECK(parse("fov_h=118.140\nfov_v=119.550\n", fov) && fov[0] > 118.13f && fov[1] < 119.56f);
    CHECK(parse("# x\nfov_v=100\r\nfov_h=101\n", fov) && fov[0] == 101 && fov[1] == 100);
    CHECK(!parse("fov_h=118\n", fov));                 // both needed
    CHECK(!parse("fov_h=30\nfov_v=118\n", fov));      // implausible
    CHECK(!parse("fov_h=nan\nfov_v=118\n", fov));
    char text[96];
    const float live[2] = {118.14f, 119.55f};
    format(text, sizeof(text), live);
    CHECK(parse(text, fov) && fov[0] > 118.13f && fov[0] < 118.15f);
    CHECK(changed(false, none, live) && !changed(true, live, live));
    const float near[2] = {118.145f, 119.55f}, far[2] = {118.2f, 119.55f};
    CHECK(!changed(true, live, near) && changed(true, live, far));
    char buf[300];
    CHECK(path("ru.targem.blazerush", buf, sizeof(buf)) &&
          !std::strcmp(buf, "/sdcard/Android/data/ru.targem.blazerush/files/framebridge-vrapi-fov.txt"));
    CHECK(path("com.x.y:remote", buf, sizeof(buf)) && std::strstr(buf, "/com.x.y/files/"));
    CHECK(!path("", buf, sizeof(buf)) && !path("/system/bin/app_process", buf, sizeof(buf)) &&
          !path("..", buf, sizeof(buf)));
    std::printf("ok\n");
    return 0;
}
''')
    subprocess.run([cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "native/vrapi-bridge"),
                    str(test), "-o", str(tmp_path / "fov")], check=True)
    run = subprocess.run([str(tmp_path / "fov")], capture_output=True, text=True)
    assert run.returncode == 0 and run.stdout.strip() == "ok", run.stdout


def test_artifacts_carry_the_fixes():
    shim = artifact("arm64-v8a", "libglshim.so")
    exports = elf.dyn_symbols(shim, True)
    assert {"glShaderSource", "glDrawArrays", "glDrawElements", "glLinkProgram", "glProgramBinary",
            "glDeleteProgram", "eglGetProcAddress"} <= exports
    assert not {s for s in exports if not s.startswith(("gl", "egl"))}
    for text in (b"gl_int_attribs=", b"gl_highp_markers=", b"glDrawElementsBaseVertexOES"):
        assert text in shim
    bridge = artifact("arm64-v8a", "libvrapi.so")
    assert b"framebridge-vrapi-fov.txt" in bridge and b"FOV properties: %.2f x %.2f degrees (%s)" in bridge
    adapter = artifact("arm64-v8a", "libopenxr_loader_generic.so")
    assert b"runtime recommended eye size %ux%u" in adapter


# ---- agent: device.config_sync
def _agent(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("frameport_agent", AGENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


USER_CONFIG = """<?xml version="1.0" encoding="utf-8"?>\r
<config>\r
\t<cvar name="r_3dwidth" value="1728" />\r
\t<cvar value="1728" name="r_3dheight"/>\r
\t<cvar name="r_width" type="int" value="3072" />\r
\t<r_height>1728</r_height>\r
\t<cvar name="snd_volume" value="0.8" />\r
\t<save slot="1" name="Ünïcode \xff" />\r
</config>\r
"""
RULES = {"user_config.xml": {"r_3dwidth": "w", "r_3dheight": "h", "r_width": "h*16/9", "r_height": "h",
                             "r_missing": "w"}}


def _installed(a, tmp_path, log_lines, scale="1.7"):
    pkg = br.PACKAGE
    base = tmp_path / "Applications/quest-frame" / pkg
    files = base / "lepton-data/external/Android/data" / pkg / "files"
    files.mkdir(parents=True)
    (files / "user_config.xml").write_bytes(USER_CONFIG.encode("utf-8", "surrogateescape"))
    os.chmod(files / "user_config.xml", 0o640)
    (base / "settings.conf").write_text(f"scale={scale}\nfoveation_fix=1\ncontroller_fix=1\n")
    (base / "launch.log").write_text("".join(f"\x1b[38;5;40m10-10 12:00:00.000 1 1 I {x}\x1b[0m\n" for x in log_lines))
    dep = {"package": pkg, "appid": 123, "base": str(base), "config_sync": RULES}
    (base / "deployment.json").write_text(json.dumps(dep))
    return pkg, base, files


def test_config_value_expressions(monkeypatch, tmp_path):
    a = _agent(monkeypatch, tmp_path)
    assert a.config_value("w", 2938, 2938) == 2938 and a.config_value("h*16/9", 2938, 2938) == 5223
    assert a.config_value(" h * 16 / 9 ", 1728, 1728) == 3072 and a.config_value("w/2", 2938, 10) == 1469
    for bad in ("__import__('os')", "w+1", "x", "h*0", ""):
        with pytest.raises(a.AgentError):
            a.config_value(bad, 2938, 2938)


def test_runtime_eye_size_from_the_last_start(monkeypatch, tmp_path):
    a = _agent(monkeypatch, tmp_path)
    (tmp_path / "launch.log").write_text(
        "I FrameBridge: scale=1.70 foveation_fix=1 controller_fix=1\nI FrameBridge: runtime recommended eye size "
        "1728x1728 (max 4096x4096, scale 1.70)\nI OVRPortVrApi: Initialized Vulkan/GLES OpenXR adapter (gles=1), "
        "stereo=2938x2938\n")
    assert a.runtime_eye_size(str(tmp_path)) == (1728, 1728)
    # builds before the new FrameBridge line: the bridge's (scaled) size divided by the logged scale
    (tmp_path / "launch.log").write_text(
        "I FrameBridge: scale=1.70 foveation_fix=1 controller_fix=1 swapchain_fix=1\nI OVRPortVrApi: Initialized "
        "Vulkan/GLES OpenXR adapter (gles=1), stereo=2938x2938\n")
    assert a.runtime_eye_size(str(tmp_path)) == (1728, 1728)
    (tmp_path / "launch.log").write_text("nothing\n")
    assert a.runtime_eye_size(str(tmp_path)) is None


def test_config_sync_writes_the_eye_size(monkeypatch, tmp_path):
    a = _agent(monkeypatch, tmp_path)
    monkeypatch.setattr(a, "container_running", lambda appid: False)
    pkg, base, files = _installed(a, tmp_path, ["FrameBridge: runtime recommended eye size 1728x1728 (max 4096x4096, "
                                                "scale 1.00)"])
    report = a.cmd_config_sync({"package": pkg})
    assert report["eye"] == [2938, 2938] and report["runtime"] == [1728, 1728] and report["scale"] == 1.7
    assert report["changed"] == {"r_3dwidth": ("1728", "2938"), "r_3dheight": ("1728", "2938"),
                                 "r_width": ("3072", "5223"), "r_height": ("1728", "2938")}
    assert report["missing"] == ["user_config.xml:r_missing"]
    text = (files / "user_config.xml").read_bytes()
    expected = (USER_CONFIG.replace('"r_3dwidth" value="1728"', '"r_3dwidth" value="2938"')
                .replace('value="1728" name="r_3dheight"', 'value="2938" name="r_3dheight"')
                .replace('type="int" value="3072"', 'type="int" value="5223"')
                .replace("<r_height>1728<", "<r_height>2938<"))
    assert text == expected.encode("utf-8", "surrogateescape")  # everything else byte for byte (CRLF, bytes)
    assert (files / "user_config.xml.frameport-backup").read_bytes() == USER_CONFIG.encode("utf-8", "surrogateescape")
    assert (files / "user_config.xml").stat().st_mode & 0o777 == 0o640
    assert not list(files.glob("*.frameport-tmp"))
    assert json.loads((base / "deployment.json").read_text())["eye_base"] == [1728, 1728]
    # nothing to do the second time; the learned size is used once launch.log is gone
    (base / "launch.log").unlink()
    assert a.cmd_config_sync({"package": pkg})["changed"] == {}
    (base / "settings.conf").write_text("scale=1.0\n")
    assert a.cmd_config_sync({"package": pkg})["changed"]["r_width"] == ("5223", "3072")


def test_config_sync_waits_for_a_stopped_game_and_a_known_size(monkeypatch, tmp_path):
    a = _agent(monkeypatch, tmp_path)
    pkg, base, files = _installed(a, tmp_path, ["nothing about sizes"])
    monkeypatch.setattr(a, "container_running", lambda appid: True)
    assert "running" in a.cmd_config_sync({"package": pkg})["skipped"]
    monkeypatch.setattr(a, "container_running", lambda appid: False)
    assert "isn't known yet" in a.cmd_config_sync({"package": pkg})["skipped"]
    assert (files / "user_config.xml").read_bytes() == USER_CONFIG.encode("utf-8", "surrogateescape")
    # outside the game's files folder: never written
    dep = json.loads((base / "deployment.json").read_text())
    dep["config_sync"] = {"../../../../x.xml": {"a": "w"}}
    (base / "deployment.json").write_text(json.dumps(dep))
    (base / "launch.log").write_text("I FrameBridge: runtime recommended eye size 1728x1728 (max 1x1, scale 1.0)\n")
    assert a.cmd_config_sync({"package": pkg})["missing"] == ["../../../../x.xml"]


def test_launcher_line_and_upgrade(monkeypatch, tmp_path):
    a = _agent(monkeypatch, tmp_path)
    pkg, base, files = _installed(a, tmp_path, ["FrameBridge: runtime recommended eye size 1728x1728 (x)"])
    a.write_launcher(str(base), str(base), pkg, "BlazeRush", 123, "/lepton", {}, config_sync=True)
    script = (base / "launch.sh").read_text()
    line = next(x for x in script.splitlines() if " _config_sync " in x)
    assert line.endswith(f"_config_sync {pkg} >\"$app_dir/config-sync.log\" 2>&1 9>&- || true")
    assert script.index(" _config_sync ") < script.index("\nsetsid ")  # before Lepton starts
    assert script.index(".launch.lock") < script.index(" _config_sync ")  # after the single-launch lock
    a.write_launcher(str(base), str(base), pkg, "BlazeRush", 123, "/lepton", {})
    assert " _config_sync " not in (base / "launch.sh").read_text()
    # older launchers get the line from upgrade_launchers when the deployment has rules
    assert pkg in a.upgrade_launchers()
    assert (base / "launch.sh").read_text().count(" _config_sync ") == 1
    assert pkg not in a.upgrade_launchers()
    # the launcher's call: the game isn't running (no podman call)
    monkeypatch.setattr(a, "container_running", lambda appid: pytest.fail("no podman call from the launcher"))
    a.config_sync_worker(pkg)
    assert b'value="2938"' in (files / "user_config.xml").read_bytes()


def test_finalize_and_set_settings_sync(monkeypatch, tmp_path):
    a = _agent(monkeypatch, tmp_path)
    monkeypatch.setattr(a, "container_running", lambda appid: False)
    pkg, base, files = _installed(a, tmp_path, ["FrameBridge: runtime recommended eye size 1728x1728 (x)"])
    app = base / "lepton-app"
    app.mkdir()
    (app / "game.apk").write_bytes(b"APK")
    monkeypatch.setattr(a, "cmd_prepare", lambda args: {"base": str(base), "anchor": str(base), "appid": 123,
                                                         "incoming": str(base / "incoming"), "lepton": "/lepton"})
    monkeypatch.setattr(a, "install_controller_models", lambda *x: {})
    r = a.cmd_finalize({"package": pkg, "title": "BlazeRush", "settings": {"scale": 1.7}, "config_sync": RULES,
                        "recipe": {"patches": ["device.config_sync"]}})
    assert r["config_sync"]["changed"]["r_3dwidth"] == ("1728", "2938")
    dep = json.loads((base / "deployment.json").read_text())
    assert dep["config_sync"] == RULES and dep["eye_base"] == [1728, 1728] and dep["agent_version"] >= 78
    assert " _config_sync " in (base / "launch.sh").read_text()
    r = a.cmd_set_settings({"package": pkg, "settings": {"scale": 1.0}})
    assert r["config_sync"]["changed"]["r_width"] == ("5223", "3072")
