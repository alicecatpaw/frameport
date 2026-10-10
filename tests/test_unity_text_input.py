"""Unity text fields on the Frame: Cpp2IL output parsing, the release pick, the byte patch and the detection."""
from pathlib import Path

import pytest

from frameport.analysis.detect import unity_text_fields, unity_version
from frameport.analysis.il2cpp import _plain_version, parse_methods
from frameport.patches.frame import unity_text_input as U
from frameport.tools.cpp2il import pick_release

CS = '''public class TMP_InputField : Selectable
{
	[Address(RVA = "0x71946E0", Offset = "0x71946E0", Length = "0x98")]
	[Token(Token = "0x6000305")]
	public bool get_shouldHideMobileInput() { }

	[Address(RVA = "0x7194A78", Offset = "0x7194A78", Length = "0x10C")]
	[Token(Token = "0x6000383")]
	private bool isKeyboardUsingEvents() { }

	[Address(RVA = "0x71988F0", Offset = "0x71988F0", Length = "0xB8")]
	[Token(Token = "0x6000386")]
	private bool TouchScreenKeyboardShouldBeUsed() { }
}
'''


def test_parse_methods_reads_file_offsets():
    found = parse_methods(CS, ["TouchScreenKeyboardShouldBeUsed", "isKeyboardUsingEvents", "Missing"])
    assert found == {"TouchScreenKeyboardShouldBeUsed": (0x71988F0, 0xB8), "isKeyboardUsingEvents": (0x7194A78, 0x10C)}
    assert _plain_version("6000.2.7f2") == "6000.2.7" and _plain_version("2021.3.45f1") == "2021.3.45"


def test_pick_release_takes_the_newest_with_an_asset_for_this_computer():
    releases = [{"tag_name": "2022.1.0-pre-release.21", "assets": [
                    {"name": "Cpp2IL-2022.1.0-pre-release.21-Linux", "browser_download_url": "u/linux"},
                    {"name": "Cpp2IL-2022.1.0-pre-release.21-Linux-ARM64", "browser_download_url": "u/arm"},
                    {"name": "Cpp2IL-2022.1.0-pre-release.21-Windows.exe", "browser_download_url": "u/win"}]},
                {"tag_name": "old", "assets": [{"name": "Cpp2IL-old-OSX", "browser_download_url": "u/osx"}]}]
    assert pick_release(releases, "Linux") == ("2022.1.0-pre-release.21", "u/linux")
    assert pick_release(releases, "Linux-ARM64")[1] == "u/arm"
    assert pick_release(releases, "Windows.exe")[1] == "u/win"
    assert pick_release(releases, "OSX") == ("old", "u/osx")
    assert pick_release(releases, "OSX-ARM64") is None


def _lib(tmp_path) -> bytes:
    """A small arm64 ELF with an executable segment (tests/fixtures), padded to hold the fake methods."""
    fx = sorted(Path(__file__).parent.joinpath("fixtures").glob("libfake*_arm64.so"))[0]
    return fx.read_bytes()


def test_patch_methods_writes_return_values_once(tmp_path):
    lib = _lib(tmp_path)
    (lo, hi), = U._executable(lib)[:1]
    a, b = (lo + 0x40) & ~3, (lo + 0x80) & ~3
    assert b + 8 <= hi
    found = {"Unity.TextMeshPro/TMPro/TMP_InputField.cs": {"TouchScreenKeyboardShouldBeUsed": (a, 0xB8),
                                                          "isKeyboardUsingEvents": (b, 0x10C)}}
    patched, notes = U.patch_methods(lib, found)
    assert patched[a:a + 8] == U.RET_FALSE and patched[b:b + 8] == U.RET_TRUE and len(patched) == len(lib)
    assert len(notes) == 2 and "TMP_InputField.isKeyboardUsingEvents -> true" in notes[1]
    again, notes2 = U.patch_methods(patched, found)  # idempotent
    assert again is None and all("already patched" in n for n in notes2)


def test_patch_methods_refuses_offsets_outside_code(tmp_path):
    lib = _lib(tmp_path)
    bad = {"Unity.TextMeshPro/TMPro/TMP_InputField.cs": {"TouchScreenKeyboardShouldBeUsed": (len(lib) + 64, 8)}}
    with pytest.raises(RuntimeError, match="isn't code"):
        U.patch_methods(lib, bad)
    misaligned = {"Unity.TextMeshPro/TMPro/TMP_InputField.cs": {"isKeyboardUsingEvents": (U._executable(lib)[0][0] + 2,
                                                                                         64)}}
    with pytest.raises(RuntimeError):
        U.patch_methods(lib, misaligned)


def test_detection_of_text_fields_and_unity_version():
    meta = b"\0Selectable\0TMP_InputField\0TMPro\0UnityEngine.UI\0"
    assert unity_text_fields(meta) == ["TMP_InputField"]  # "InputField" only as the tail of TMP_InputField
    assert unity_text_fields(meta + b"InputField\0") == ["TMP_InputField", "InputField"]
    assert unity_text_fields(b"\0Button\0") == []
    assert unity_version(b"\0" * 40 + b"2021.3.45f1\0") == "2021.3.45f1"
    assert unity_version(None, b"x 6000.2.7f2 y 6000.2.7f2 z 6000.2.7f1 2018.3.0a1") == "6000.2.7f2"


def test_patches_suggested_for_unity_apps_with_text_fields():
    from test_patches import _analysis

    from frameport.patches import base

    base.load_all()
    a = _analysis(libs=["libil2cpp.so", "libunity.so"], extra={"text_fields": ["TMP_InputField"], "vr_kind": "quest"})
    assert base.get("frame.unity_text_input").detect(a).recommended
    assert not base.get("device.text_input_window").detect(a).recommended
    assert base.get("device.text_input_window").detect(a) is not None
    a.extra["text_fields"] = []
    assert base.get("frame.unity_text_input").detect(a) is None and not base.get("frame.unity_text_input").applies(a)


def test_catalog_device_toggles_round_trip():
    from frameport.recommend.catalog import CatalogEntry

    e = CatalogEntry.from_dict({"package": "com.x", "title": "X", "frame": ["frame.unity_text_input"],
                                "device": ["device.text_input_window"]}, "bundled")
    assert e.device == ["device.text_input_window"] and e.to_dict()["device"] == ["device.text_input_window"]


def test_reanalyze_refreshes_the_suggestion_and_keeps_a_users_recipe(monkeypatch, tmp_path):
    from test_patches import _analysis

    from frameport import pipeline
    from frameport.core import library
    from frameport.core.models import Recipe

    apk = tmp_path / "game.apk"
    apk.write_bytes(b"x")
    a = _analysis(package="com.x", libs=["libil2cpp.so", "libunity.so"],
                  extra={"text_fields": ["TMP_InputField"], "vr_kind": "quest", "unity_version": "6000.2.7f2"})
    monkeypatch.setattr(pipeline, "analyze", lambda path, data_bytes=0: a)
    old = Recipe(package="com.x", patches={"frame.adapter": {}}, source="heuristics")
    library.upsert_game("com.x", title="X", apk=str(apk), analysis=_analysis(package="com.x").to_dict(),
                        recipe=library.recipe_to_dict(old), suggested=library.recipe_to_dict(old))
    pipeline.reanalyze("com.x")
    g = library.game("com.x")
    assert g["analysis"]["extra"]["text_fields"] == ["TMP_InputField"]
    assert "frame.unity_text_input" in g["recipe"]["patches"]  # heuristic recipe: replaced by the new suggestion
    user = Recipe(package="com.x", patches={"frame.adapter": {}}, source="user")
    library.upsert_game("com.x", recipe=library.recipe_to_dict(user))
    pipeline.reanalyze("com.x")
    g = library.game("com.x")
    assert "frame.unity_text_input" not in g["recipe"]["patches"]  # the user's own choices stay
    assert "frame.unity_text_input" in g["suggested"]["patches"]


def test_flat_windows_game_keeps_only_proton_patches():
    from test_patches import _analysis

    from frameport.patches import base
    from frameport.recommend import engine

    base.load_all()
    a = _analysis(package="rift.somegame", engine="Unity", xr="?", libs=[],
                  extra={"kind": "rift", "flat": True, "vr_found": False, "exe": "Game.exe"})
    vr = engine.suggest(_analysis(package="rift.somegame", engine="Unity", xr="OpenXR", libs=[],
                                  extra={"kind": "rift", "vr_found": True, "openxr": True, "exe": "Game.exe"}),
                        use_catalog=False)
    r = engine.suggest(a, use_catalog=False)
    assert set(r.patches) <= set(engine.FLAT_WINDOWS_PATCHES)
    assert set(vr.patches) - set(engine.FLAT_WINDOWS_PATCHES)  # the same game with VR gets VR patches
