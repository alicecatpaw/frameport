"""BlazeRush (ru.targem.blazerush 1.0.349): two instruction edits and one string in libtargemapp.so, from Klownicle's
verified developer guide (GitHub #57).

1. Controllers: the menus wait for Meta's Avatar SDK to deliver the player's avatar before they create the game's own
   interactive controller entities. FramePort's avatar stub (frame.avatar_stub) keeps the game alive without Meta's
   avatar driver but never delivers an avatar, so the second menu ignored all input. The conditional branch that waits
   for avatar readiness becomes a NOP (0x4b2dbc), and the wrapper that renders the avatar meshes returns at once
   (0x4b2adc), so the entities that now exist never touch the missing avatar renderer. The generic avatar stub keeps
   reporting "no avatar": other games could dereference avatar assets that don't exist.
2. Shader cache: the game keeps compiled program binaries under files/cache/shader_cache and uses them instead of the
   shader sources. "cache/shader_cache" becomes "cache/br_shader_v1" (same length), so programs compiled before the GL
   shim's precision fix (gl_highp_markers) aren't used; the old cache and the saves stay.

Only the exact build is edited: its code segment must hash to the known fingerprint (with the edit sites as shipped
or already edited), every instruction word must be the expected original or replacement, and the string must sit at
its known address, once. Anything else is refused and left unchanged (logged in the build notes). File offsets come
from the PT_LOAD segments, so libraries rewritten by other patches (the GL shim adds a DT_NEEDED entry and a segment,
nothing that exists moves) still match.

The guide's other fixes are elsewhere: integer vertex attributes and the particle shaders' precision in the GL shim
(gl_int_attribs, gl_highp_markers), the startup FOV in the VrApi bridge (the FOV of the previous session), scale 1.7
in the catalog recipe, and the saved resolution in user_config.xml through device.config_sync.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from ...analysis import elf
from ..base import ApkContext, Patch, Suggestion, register

PACKAGE = "ru.targem.blazerush"
LIB = "libtargemapp.so"
NOP = 0xD503201F
RET = 0xD65F03C0
OLD_CACHE = b"cache/shader_cache\0"
NEW_CACHE = b"cache/br_shader_v1\0"
EM_AARCH64 = 183


@dataclass(frozen=True)
class Build:
    version: str
    text_sha256: str  # SHA-256 of the executable PT_LOAD segment with every edit site as shipped
    sites: tuple[tuple[int, int, int, str], ...]  # (virtual address, original word, replacement, what)
    cache_va: int  # virtual address of "cache/shader_cache"


BUILDS = (
    # 1.0.349: libtargemapp.so SHA-256 89686ffc5105f5149adf9bf08d88eafdd4e8e99a3cd14d1ac9cc0d3317dfe568 (as shipped;
    # OVRPort and FramePort's other patches leave it unchanged)
    Build("1.0.349", "951bf1d5208ae36603f73990346d164a8523e7d1e60cc3e67d3571c7fc55d5f4",
          ((0x4B2DBC, 0x36000AE0, NOP, "avatar readiness wait (tbz) -> nop"),
           (0x4B2ADC, 0xF0002368, RET, "avatar mesh renderer -> ret")),
          0x13AF70),
)


def _exec_segment(data: bytes, va: int) -> tuple[int, int, int] | None:
    """(vaddr, file offset, size) of the executable PT_LOAD segment holding `va`."""
    for seg in elf._elf(data).iter_segments():
        start, size = seg["p_vaddr"], seg["p_filesz"]
        if seg["p_type"] == "PT_LOAD" and seg["p_flags"] & 1 and start <= va < start + size:
            return start, seg["p_offset"], size
    return None


def find_sites(data: bytes) -> dict | None:
    """The edits for a supported build: {"build", "edits": [(file offset, old word, new word, what)], "cache_offset",
    "done": every edit already made}; None for anything else (another build, a damaged or foreign library)."""
    if not elf.is_elf(data) or not elf.is_64bit(data) or data[5] != 1:
        return None
    if struct.unpack_from("<H", data, 18)[0] != EM_AARCH64:
        return None
    try:
        segments = elf.load_segments(data)
    except Exception:  # noqa: BLE001 - not a readable ELF: refuse
        return None
    for build in BUILDS:
        text = _exec_segment(data, build.sites[0][0])
        if not text:
            continue
        t_va, t_off, t_size = text
        code = bytearray(data[t_off:t_off + t_size])
        edits, ok = [], True
        for va, old, new, what in build.sites:
            if not t_va <= va < t_va + t_size - 3:
                ok = False
                break
            at = va - t_va
            word = struct.unpack_from("<I", code, at)[0]
            if word not in (old, new):
                ok = False
                break
            struct.pack_into("<I", code, at, old)  # fingerprint over the code as shipped
            edits.append((t_off + at, old, new, what, word == new))
        if not ok or hashlib.sha256(code).hexdigest() != build.text_sha256:
            continue
        off = elf.vaddr_to_offset(segments, build.cache_va)
        if off is None:
            continue
        here = data[off:off + len(OLD_CACHE)]
        old_n, new_n = data.count(OLD_CACHE), data.count(NEW_CACHE)
        if not ((here == OLD_CACHE and old_n == 1 and new_n == 0) or (here == NEW_CACHE and old_n == 0 and new_n == 1)):
            continue
        cache_done = here == NEW_CACHE
        return {"build": build.version, "edits": [e[:4] for e in edits], "cache_offset": off,
                "done": cache_done and all(e[4] for e in edits),
                "pending": [e[3] for e in edits if not e[4]] + ([] if cache_done else ["shader cache namespace"])}
    return None


def patch_library(data: bytes) -> tuple[bytes, dict | None]:
    """(edited library, sites) for a supported build; the data unchanged and None otherwise."""
    site = find_sites(data)
    if not site or site["done"]:
        return data, site
    buf = bytearray(data)
    for at, _old, new, _what in site["edits"]:
        struct.pack_into("<I", buf, at, new)
    buf[site["cache_offset"]:site["cache_offset"] + len(NEW_CACHE)] = NEW_CACHE
    return bytes(buf), site


class BlazeRush(Patch):
    id = "frame.blazerush"
    title = "BlazeRush: controllers without Meta avatars, own shader cache"
    description = ("BlazeRush 1.0.349 only (Klownicle's guide, GitHub #57). Its menus wait for Meta's avatar, which "
                   "never comes on the Frame, before they create the game's own controllers: the second menu ignored "
                   "all input. Two instructions in libtargemapp.so skip that wait and the avatar mesh drawing; the "
                   "game's shader cache gets a new folder name (cache/br_shader_v1), so programs compiled before the "
                   "GL shim's shader fixes aren't reused. Only this exact build is changed (code fingerprint and "
                   "every instruction checked); anything else is left as it is.")
    order = 59  # after frame.avatar_stub (58), before the GL shim (61): it doesn't matter, nothing here moves
    strict = True  # a catalog recipe only uses it where applies() holds
    note = "BlazeRush: avatar wait skipped, avatar meshes not drawn, shader cache cache/br_shader_v1"
    reason = ("BlazeRush waits for a Meta avatar before it creates its controllers (the menus ignore input on the "
              "Frame) and reuses shaders compiled before the GL shim's fixes.")

    def applies(self, a):
        return a.package == PACKAGE and "arm64-v8a" in a.abis and LIB in a.libs

    def detect(self, a):
        if self.applies(a) and a.version in {b.version for b in BUILDS}:
            return Suggestion(True, self.reason)
        return None

    def apply(self, ctx: ApkContext) -> bool:
        ws = ctx.ws
        if ws.abi != "arm64-v8a" or not ws.has(ws.lib(LIB)):
            return False
        data = ws.read_lib(LIB)
        new, site = patch_library(data)
        if not site:
            ctx.notes.append(f"{self.id}: {LIB} isn't BlazeRush 1.0.349's library as known, left unchanged")
            return False
        if new == data:
            return False
        ws.put(ws.lib(LIB), new)
        ctx.notes.append(f"{self.note} ({LIB}: " + ", ".join(site["pending"]) + ")")
        return True

    def validate(self, ctx: ApkContext):
        ws = ctx.ws
        if ws.abi != "arm64-v8a" or not ws.has(ws.lib(LIB)):
            return []
        site = find_sites(ws.read_lib(LIB))
        return [("BlazeRush avatar wait skipped and own shader cache", bool(site) and site["done"],
                 "" if site else "library not recognised (different build)")]


register(BlazeRush)
