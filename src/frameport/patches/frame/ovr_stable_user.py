"""OVRPort's platform loader gives the game a new Meta user id at every start, so games lose their progress.

Without a Meta account on the device, OVRPort's `ovr_GetLoggedInUserID` (and the logged-in user's `ovr_User_GetID`)
answer with an id it makes up: 6e18 + a value from `random()`, kept only in memory. Games that file their saves under
the user id (Walkabout Mini Golf: `Profiles/Oculus/<user id>/`, GitHub #182) open an empty profile at every start, so
their progress seems gone (the old saves stay on the Frame, under the earlier ids).

This patch rewrites that helper to return a fixed id instead: 6e18 + 32 bits of a hash of the game's package name and
its signing keystore. The id stays the same for every build and reinstall of the game (the keystore never changes), and
differs between games and between FramePort users (each user's keystores are their own), so games that use the id
online don't see two players as one.
"""
from __future__ import annotations

import hashlib

from ...analysis import elf
from ..base import ApkContext, Patch, Suggestion, register

LOADER = "libovrplatformloader.so"
BASE_ID = 0x53444835EC580000  # 6e18: OVRPort's own base for made-up ids

STP = 0xA9BF7BFD       # stp x29, x30, [sp, #-16]!
MOV_FP = 0x910003FD    # mov x29, sp
BL, BL_MASK = 0x94000000, 0xFC000000
# the end of the helper, which loads 6e18 into x9 and adds it (same bytes in OVRPort runtimes 3.4.3-23204ea and
# 3.4.3-aa54c3f)
MOV_X9_LO = 0xD2BD8B09   # mov  x9, #0xec580000
MOVK_X9_32 = 0xF2C906A9  # movk x9, #0x4835, lsl #32
MOVK_X9_48 = 0xF2EA6889  # movk x9, #0x5344, lsl #48
ADD_X0 = 0x8B090100      # add  x0, x8, x9
LDP = 0xA8C17BFD         # ldp  x29, x30, [sp], #16
RET = 0xD65F03C0
SIZE = 19                # instructions in the helper, stp … ret


def _words(data: bytes | bytearray, off: int, n: int) -> list[int]:
    return [int.from_bytes(data[off + 4 * i:off + 4 * i + 4], "little") for i in range(n)]


def _text_ranges(data: bytes) -> list[tuple[int, int]]:
    """File ranges of executable PT_LOAD segments."""
    try:
        e = elf._elf(data)
    except Exception:  # noqa: BLE001
        return []
    return [(s["p_offset"], s["p_offset"] + s["p_filesz"]) for s in e.iter_segments()
            if s["p_type"] == "PT_LOAD" and s["p_flags"] & 1]


def find_helper(data: bytes) -> int | None:
    """File offset of OVRPort's made-up-user-id helper (stp; mov x29,sp; bl random; …; mov/movk x9 = 6e18; add x0,
    x8, x9; ldp; ret), or None. Exactly one match is required."""
    tail = [MOV_X9_LO, MOVK_X9_32, MOVK_X9_48, ADD_X0, LDP, RET]
    found = []
    for start, end in _text_ranges(data):
        off = data.find(MOV_X9_LO.to_bytes(4, "little") + MOVK_X9_32.to_bytes(4, "little"), start, end)
        while off != -1:
            head = off - 4 * (SIZE - len(tail))
            if head >= start and _words(data, off, len(tail)) == tail:
                w = _words(data, head, 3)
                if w[0] == STP and w[1] == MOV_FP and w[2] & BL_MASK == BL:
                    found.append(head)
            off = data.find(MOV_X9_LO.to_bytes(4, "little") + MOVK_X9_32.to_bytes(4, "little"), off + 4, end)
    return found[0] if len(found) == 1 else None


def stable_id(package: str, keystore: bytes) -> int:
    """6e18 + 32 bits from the package name and the game's signing keystore."""
    digest = hashlib.sha256(package.encode() + b"\0" + keystore).digest()
    return BASE_ID + int.from_bytes(digest[:4], "little")


def _mov_x0(value: int) -> list[int]:
    """movz/movk x0 with a 64-bit value."""
    out = []
    for i in range(4):
        imm = (value >> (16 * i)) & 0xFFFF
        base = 0xD2800000 if i == 0 else 0xF2800000  # movz / movk (64-bit)
        out.append(base | (i << 21) | (imm << 5))
    return out


def pin_user_id(data: bytes, user_id: int) -> bytes | None:
    """The loader whose made-up-id helper returns `user_id`, or None when the helper isn't found (Meta's own loader,
    another OVRPort build, already patched)."""
    off = find_helper(data)
    if off is None:
        return None
    new = _mov_x0(user_id) + [RET]
    out = bytearray(data)
    for i, word in enumerate(new):  # the rest of the helper stays (unreachable), so the size never changes
        out[off + 4 * i:off + 4 * i + 4] = word.to_bytes(4, "little")
    return bytes(out)


def _keystore(package: str) -> bytes:
    from ...apk import sign

    try:
        return sign.ensure_keystore(package).read_bytes()
    except OSError:
        return b""


class OvrStableUser(Patch):
    id = "frame.ovr_stable_user"
    title = "Keep the same Meta user between starts"
    description = ("Without a Meta account, OVRPort's platform library makes up a new user id at every start "
                   "(ovr_GetLoggedInUserID). Games that file saves under the user id (for example Walkabout Mini "
                   "Golf) then start with an empty profile each time and seem to lose all progress. Gives the game "
                   "a fixed id instead, different for each game and each FramePort user.")
    order = 47
    default_on = True  # suggested only where the game has the platform library (detect)

    def detect(self, a):
        if LOADER in a.libs:
            return Suggestion(True, "The game uses Meta's platform library: OVRPort's version gives it a new user "
                                    "id at every start, which loses saves filed under that id.")
        return None

    def applies(self, a):
        return LOADER in a.libs

    def apply(self, ctx: ApkContext) -> bool:
        ws = ctx.ws
        if not ws.has(ws.lib(LOADER)):
            return False
        package = ctx.analysis.package
        user_id = stable_id(package, _keystore(package))
        fixed = pin_user_id(ws.read_lib(LOADER), user_id)
        if fixed:
            ws.put(ws.lib(LOADER), fixed)
            ctx.notes.append(f"{LOADER}: the logged-in user id is always {user_id}")
        return bool(fixed)


register(OvrStableUser)
