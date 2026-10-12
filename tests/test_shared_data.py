"""A data folder shared by a Windows copy and WSL source runs (FRAMEPORT_WINDOWS_DATA)."""
import json

from frameport.core import paths
from frameport.tools import cpp2il, toolchain


def test_local_path_on_windows(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    assert paths.local_path("/mnt/d/Games/X/a.apk") == "D:\\Games\\X\\a.apk"
    assert paths.local_path("/mnt/c") == "C:\\"
    assert paths.local_path("/home/steamos/Applications/x") == "/home/steamos/Applications/x"  # Frame paths stay
    assert paths.local_path("D:\\Games") == "D:\\Games"


def test_local_path_on_wsl(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(paths, "shares_windows_data", lambda: True)
    assert paths.local_path("D:\\Games\\X\\a.apk") == "/mnt/d/Games/X/a.apk"
    assert paths.local_path("C:/Users/A") == "/mnt/c/Users/A"
    assert paths.local_path("/mnt/d/Games") == "/mnt/d/Games"
    monkeypatch.setattr(paths, "shares_windows_data", lambda: False)
    assert paths.local_path("D:\\Games") == "D:\\Games"  # own data folder: left alone


def test_localize_walks_json(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    data = {"games": {"a": {"apk": "/mnt/d/x.apk", "build": {"checks": [{"detail": "see /mnt/d/x"}]},
                            "list": ["/mnt/e/y"], "n": 3, "title": "Cool"}}}
    paths.localize(data)
    g = data["games"]["a"]
    assert g["apk"] == "D:\\x.apk" and g["list"] == ["E:\\y"]
    assert g["build"]["checks"][0]["detail"] == "see /mnt/d/x"  # only whole-string paths
    assert g["n"] == 3 and g["title"] == "Cool"


def test_windows_data_only_when_asked(monkeypatch):
    monkeypatch.delenv("FRAMEPORT_WINDOWS_DATA", raising=False)
    assert not paths.shares_windows_data()
    monkeypatch.setenv("FRAMEPORT_WINDOWS_DATA", "1")
    assert not paths.shares_windows_data()  # FRAMEPORT_HOME (set by the test fixtures) wins


def test_java_entry_per_os(monkeypatch, tmp_path):
    monkeypatch.setattr(toolchain, "tools_dir", lambda: tmp_path)
    monkeypatch.delenv("FRAMEPORT_JAVA", raising=False)
    monkeypatch.setattr(toolchain.sys, "platform", "linux")
    linux_java = tmp_path / "jre-21" / "bin" / "java"
    linux_java.parent.mkdir(parents=True)
    linux_java.write_text("")
    # a legacy single entry written by Windows isn't this OS's java
    (tmp_path / "tools.json").write_text(json.dumps({"java": {"version": "21", "path": "C:\\\\x\\\\java.exe"}}))
    assert toolchain.java_path() is None
    (tmp_path / "tools.json").write_text(json.dumps({"java": {"version": "21", "path": str(linux_java)}}))
    assert toolchain.java_path() == linux_java
    (tmp_path / "tools.json").write_text(json.dumps({
        "java": {"version": "21", "path": "C:\\\\x\\\\java.exe"},
        toolchain._java_key(): {"version": "21", "path": str(linux_java)}}))
    assert toolchain.java_path() == linux_java


def test_cpp2il_picks_this_os_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(cpp2il, "tools_dir", lambda: tmp_path)
    monkeypatch.delenv("FRAMEPORT_CPP2IL", raising=False)
    d = tmp_path / "cpp2il-2022.1"
    d.mkdir()
    (d / "Cpp2IL.exe").write_text("")
    monkeypatch.setattr(cpp2il.sys, "platform", "linux")
    assert cpp2il.path() is None
    (d / "Cpp2IL").write_text("")
    assert cpp2il.path() == d / "Cpp2IL"
    monkeypatch.setattr(cpp2il.sys, "platform", "win32")
    assert cpp2il.path() == d / "Cpp2IL.exe"
