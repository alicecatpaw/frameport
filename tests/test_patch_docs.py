"""docs/PATCHES.md and the site's patch map are generated from the registry: they must be current."""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("patch_docs", ROOT / "scripts" / "patch_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_patch_docs_are_up_to_date():
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "patch_docs.py"), "--check"], capture_output=True,
                       text=True)
    assert p.returncode == 0, p.stderr


def test_every_patch_has_one_anchor_and_links_resolve():
    from frameport.patches import base

    doc = (ROOT / "docs" / "PATCHES.md").read_text(encoding="utf-8")
    anchors = re.findall(r'<a id="([^"]+)"></a>', doc)
    assert len(anchors) == len(set(anchors))
    for p in base.all_patches():
        assert p.id.replace(".", "-") in anchors, p.id
    for target in re.findall(r"\]\(#([^)]+)\)", doc):
        assert target in anchors, target


def test_suggestions_are_read_per_setting():
    from frameport.patches import base

    mod = _module()
    reasons = [r for _, r, _ in mod.suggestions(base.get("adapter.controller_fix"))]
    assert reasons and all("Hand tracking" in r for r in reasons)
    assert mod.suggestions(base.get("adapter.swap_eyes")) == []
    assert mod.anchor("frame.unity_text_input") == "frame-unity_text_input"
