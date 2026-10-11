---
name: frameport-controller-input
description: >-
  Use this skill when diagnosing, configuring, or troubleshooting controller and hand tracking
  input issues in Quest games ported to the Steam Frame. Covers controller_fix vs synthetic
  hand tracking conflicts, OpenXR interaction profile remapping (Touch / Touch Plus / Touch Pro),
  Unity deviceModel checks in libunity.so, and live FrameBridge adapter settings.
---

# Quest to Steam Frame Controller & Input Porting Guide

This skill documents input architecture, common controller failure modes, diagnostic workflows, and fixes when running Meta Quest VR titles on the Valve Steam Frame via FramePort and FrameBridge.

---

## 1. Hand Tracking vs. Controller Conflict (`controller_fix`)

### Symptom
The player spawns into the game with head tracking working, but physical VR controllers are **unresponsive, invisible, or ignored** (e.g. Octonic VR, or other hybrid titles). In logs or engine output, controller mode switching checks fail or revert to hand tracking (e.g. `SwitchBetweenControllerHands:Check()`).

### Root Cause
1. **Manifest Heuristic False Positive**:
   In `src/frameport/analysis/detect.py`, `hand_tracking_only` is set to `True` whenever `<uses-feature android:name="oculus.software.handtracking" />` is found in `AndroidManifest.xml`. Many Quest titles support **both** controllers and hands, but include this feature tag with `android:required="true"` or defaulted to true.
2. **Auto-Heuristic Sets `controller_fix=0`**:
   In `src/frameport/patches/settings.py`, `hand_tracking_only` causes FramePort to suggest `adapter.controller_fix: 0` (turning off **"Use controllers"** in the UI).
3. **Runtime Consequences in FrameBridge (`frame_adapter.c`)**:
   - **No Interaction Profile Remap**: Normally, `xrGetCurrentInteractionProfile` (in `native/adapter/frame_adapter.c`) rewrites `/interaction_profiles/valve/frame_controller` or generic controller to `/interaction_profiles/oculus/touch_controller`. When `controller_fix == 0`, this rewrite is skipped (`if (!controller_fix) return result;`). Unity's Oculus XR Plugin / OVRInput sees an unknown interaction profile and reports no controllers connected.
   - **Synthetic Hand Passthrough**: When `controller_fix == 0`, `xrLocateHandJointsEXT` (in `native/adapter/frame_adapter.c`) does not force `locations->isActive = XR_FALSE`. The Steam Frame's synthetic hands (generated from controller poses) are passed to the app, causing the game engine to switch to hand-tracking mode and ignore physical button presses.

### Fix
Ensure `controller_fix=1` is active:

1. **Live Fix on Connected Frame (No Rebuild Needed)**:
   ```bash
   uv run python -m frameport.cli settings <package.name> controller_fix=1
   ```
   This immediately writes `controller_fix=1` to both:
   - `<base>/settings.conf` (e.g. `/home/steamos/Applications/quest-frame/<package>/settings.conf`)
   - `/sdcard/Android/data/<package>/files/framebridge.conf`
2. **In FramePort UI**:
   Open **Game → Game settings… → Controllers → Use controllers** (toggle switch **ON**) and save.
3. **In Recipe (`library.json`)**:
   Remove `"adapter.controller_fix": {"value": 0}` from the recipe's patches so reinstalls or rebuilds retain the default `controller_fix=1`.

---

## 2. Interaction Profile Remapping (`profile_remap`)

### Symptom
Launch log warning or error:
```text
xrSuggestInteractionProfileBindings(m_xrInstance, &proSuggestedBindings) -> XR_ERROR_PATH_UNSUPPORTED
```
Controllers do nothing on setup screens or menus.

### Root Cause
The game only suggests bindings for newer Meta interaction profiles:
- `/interaction_profiles/meta/touch_controller_plus` (Quest 3)
- `/interaction_profiles/meta/touch_plus_controller`
- `/interaction_profiles/facebook/touch_controller_pro` (Quest Pro)
- `/interaction_profiles/meta/touch_pro_controller`
- `/interaction_profiles/meta/touch_controller_quest_2`

The Steam Frame's Android OpenXR runtime only recognizes `/interaction_profiles/oculus/touch_controller`.

### Behavior & Fix
- FrameBridge includes `profile_remap=1` by default (in `native/adapter/session_fixes.c`).
- When `xrSuggestInteractionProfileBindings` returns `XR_ERROR_PATH_UNSUPPORTED` for a newer profile in `NEWER_TOUCH`, `remap_to_touch` automatically filters out unsupported components and resubmits the bindings for `/interaction_profiles/oculus/touch_controller`.
- If an app has buttons mapped incorrectly, verify `profile_remap=1` is present in `framebridge.conf`.

---

## 3. Unity Device Model Check (`unity_oculus_check`)

### Symptom
In older Unity games (Unity 2017–2019, e.g. BattleSisters), the game boots and displays frames, but ignores all controller input, and logcat shows only Oculus Go controller masks polled.

### Root Cause
In `libunity.so`, Unity's built-in Oculus VR module executes a hardcoded check against Android's system device model:
```c
strncmp(SystemInfo.deviceModel, "Oculus", 6) == 0
```
On the Steam Frame, the Lepton container reports the device model as `"Valve Lepton"`. Because the prefix does not match `"Oculus"`, Unity treats the headset as unknown/Go, never initializes Touch controller nodes, and fails to poll `ovrp_GetControllerState(0x3)`.

### Fix
Apply patch `frame.unity_oculus_check` (`src/frameport/patches/frame/unity_oculus_check.py`, revision 4):
- Binary patches the check in `libunity.so` by replacing `orr w2, wzr, #6` with `mov w2, #0` (`MOV_W2_0 = 0x52800002`), forcing `strncmp` length to 0 (always matches).
- Routes `ovrp_GetNodePresent` and `ovrp_Update2` through `libfp_ovrp.so` (`ovrpshim`).

---

## 4. Headset User Presence (`frame.unity_user_presence`)

### Symptom
In Unity titles using the Oculus XR Plugin (e.g. BONELAB), the scene renders at full frame rate (72 fps), but the avatar body is frozen, head tracking does not update the camera, and controllers are stuck in mid-air.

### Root Cause
A few seconds after boot, `OVRPlugin` reports `ovrp_GetUserPresent2 -> 0` ("headset not worn"). Games with custom rigs (e.g. Marrow Rig) check `XRHMD.IsUserPresent` / `UserPresence` every frame and refuse to update controller or head tracking poses when user presence is false.

### Fix
Apply patch `frame.unity_user_presence` (`src/frameport/patches/frame/unity_user_presence.py`):
- Replaces the `ovrp_GetUserPresent2` symbol in `libOculusXRPlugin.so` with `fpov_GetUserPresent2` in `libfp_ovrp.so`, which unconditionally reports user presence as true (`*present = 1`).

---

## 5. Steam Frame Controller Models (`controller_models`)

### Configuration
In `settings.conf` or `framebridge.conf`:
```conf
controller_models=1
```
- When enabled, FramePort's agent converts SteamVR's controller models from the host (`/opt/steamvr/drivers/frame_controller/...`) into GLB format at `/sdcard/Android/data/<package>/files/framebridge`.
- FrameBridge emulates `XR_FB_render_model` to serve these models to games that load runtime controller meshes instead of bundling static models.

---

## 6. Controller Input Diagnostics (`input_diag`)

When troubleshooting unrecognized buttons or interaction profiles:
1. Enable diagnostics dynamically:
   ```bash
   uv run python -m frameport.cli settings <package.name> input_diag=1
   ```
2. Check `launch.log` on the Frame:
   ```text
   input_diag: bindings: /interaction_profiles/oculus/touch_controller accepted (30 paths)
   input_diag: bindings: /user/hand/left uses /interaction_profiles/oculus/touch_controller
   input_diag: bindings: /user/hand/right uses /interaction_profiles/oculus/touch_controller
   ```
3. If an interaction profile is rejected, `input_diag` prints:
   ```text
   input_diag: unsupported: interaction profile <profile> -> <result>
   ```

---

## 7. Verification Checklist for Controller Issues

| Step | Action | Expected Output |
| :--- | :--- | :--- |
| **1. Check `controller_fix`** | `cat <base>/settings.conf` | `controller_fix=1` |
| **2. Check Profile Remap** | Review `launch.log` for OpenXR profile | `bindings: ... uses /interaction_profiles/oculus/touch_controller` |
| **3. Check Hand Tracking** | Review `launch.log` for synthetic hands | `locations->isActive = XR_FALSE` (hands inactive) |
| **4. Headless Launch Test** | `uv run python -m frameport.cli test <package.name>` | `[PASS] Process: RUNNING`, `Submitting frames`, 72 fps |
| **5. Live Headset Check** | Launch game on Frame in VR | Controllers render and buttons/triggers interact with menus |
