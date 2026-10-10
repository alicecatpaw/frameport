---
name: frameport-mr-porting
description: >-
  Use this skill when porting, configuring, or troubleshooting Quest AR/MR (Mixed Reality)
  games on the Steam Frame. Covers Meta scene/room emulation (XR_FB_scene, MRUK), passthrough
  alpha blending (XR_FB_passthrough), OpenXR composition layer limits (OVROverlayCanvas / maxLayerCount),
  and FrameBridge adapter fixes.
---

# Quest to Steam Frame AR/MR Porting Guide

This skill documents key findings, runtime quirks, and troubleshooting workflows for running Quest Mixed Reality / Augmented Reality games on the Steam Frame using FramePort and FrameBridge.

> [!TIP]
> For controller binding, interaction profile remapping, or hand tracking vs. controller issues, see the companion skill [`frameport-controller-input`](file:///c:/Users/alice/Documents/frameport/frameport/.agents/skills/frameport-controller-input/SKILL.md).

---

## 1. Meta Scene & Spatial Entity Emulation (`XR_FB_scene`)

### Context
Quest MR titles (using Meta XR SDK or Mixed Reality Utility Kit / MRUK) rely on Meta scene discovery and spatial entities to detect the room, floor, walls, ceiling, and obstacles.

### Configuration
In `settings.conf` (or APK `libframe_settings.so`):
```conf
scene_emul=1
passthrough_emul=1
scene_width=5.0
scene_depth=5.0
```

### Key Gotchas & Fixes
1. **Room Dimensions**:
   - Some games (or MRUK room-setup steps, such as placing doors or objects) calculate collision boundaries and reject placements if the synthetic room boundary is too small or colliding with bounding boxes (e.g. door outline remaining red).
   - Use `scene_width` and `scene_depth` in `settings.conf` to expand the synthetic room boundary (e.g. 5.0m x 5.0m).
2. **Semantic Labels**:
   - MRUK expects specific semantic label strings: `FLOOR`, `WALL_FACE`, `CEILING`, `DOOR_FRAME`, `WINDOW_FRAME`.
   - Ensure `xrGetSpaceSemanticLabelsFB` provides correct label bitmasks and names matching Meta SDK expectations.
3. **Reference Space & Tracking**:
   - Reference space `XR_REFERENCE_SPACE_TYPE_LOCAL_FLOOR_EXT` (`1000426000`) must have a valid tracked pose aligned with the floor anchor.

---

## 2. Passthrough & Alpha Blending (`XR_FB_passthrough`)

### How Steam Frame Passthrough Works
Steam Frame provides video passthrough via the OpenXR environment blend mode:
- When a game creates or enables an `XrPassthroughFB` layer, FrameBridge intercepts it (`emulate_passthrough = 1`).
- FrameBridge removes the raw Quest passthrough layer and sets `environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_ALPHA_BLEND` in `XrFrameEndInfo`.
- The main projection layer must have the blend flags enabled:
  ```c
  projections[count].layerFlags |= XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT |
                                   XR_COMPOSITION_LAYER_UNPREMULTIPLIED_ALPHA_BIT;
  ```
- Pixels rendered by the game with alpha < 1.0 will reveal the Frame's physical camera passthrough environment.

---

## 3. Composition Layer Limits (`maxLayerCount = 16`)

### The Problem
- The OpenXR specification defines `XR_MIN_COMPOSITION_LAYERS_SUPPORTED = 16`.
- SteamVR / Steam Frame's compositor strictly enforces `maxLayerCount = 16`.
- Unity Meta XR SDK apps frequently use `OVROverlayCanvas` for world-space UI menus, HUD panels, and text blocks. Each canvas creates an `OVROverlay` component that submits an `XR_TYPE_COMPOSITION_LAYER_QUAD`.
- In games with complex UIs (e.g. Punch Fit), the app may submit **21+ layers** (e.g. 20 quads + 1 projection layer).
- When `layerCount > maxLayerCount`, SteamVR rejects the entire frame submission:
  ```text
  xrEndFrame failed -24: blend=3 layers=21  (XR_ERROR_LAYER_LIMIT_EXCEEDED)
  Unity: Source: NativePlugin/Source/unity_display.cpp:424
  ```
  This causes every frame to fail, leaving the headset with a black/blank screen even though the game engine and audio continue running.

### Layer Trimming Architecture in `native/adapter/frame_adapter.c`
In `xrEndFrame`:
1. Query `properties->graphicsProperties.maxLayerCount` via `xrGetSystemProperties` (defaults to 16 if unspecified).
2. Filter unusable layers (zero extents, missing swapchains, detached surfaces).
3. If `count > max_layers`:
   - Calculate budget for projection layers: `proj_budget = min(proj_count, max_layers)`.
   - Calculate budget for non-projection layers: `non_proj_budget = max_layers - proj_budget`.
   - Preserve **all** projection layers (`XR_TYPE_COMPOSITION_LAYER_PROJECTION`) up to `proj_budget`.
   - Fill remaining slots with non-projection layers up to `non_proj_budget`.
   - Maintain relative layer ordering so UI overlays and underlays composite correctly.

---

## 4. `xrGetInstanceProcAddr` with `XR_NULL_HANDLE`

- `OVRPlugin` often probes extension function pointers (such as Meta passthrough, scene, and performance metrics) before `xrCreateInstance` completes, calling `xrGetInstanceProcAddr(XR_NULL_HANDLE, ...)`.
- If the loader shim (`native/xrshim/xrshim.c`) rejects `XR_NULL_HANDLE`, `OVRPlugin` caches the function as unsupported and disables the MR feature entirely.
- Ensure `xrshim.c` dispatches known emulated function pointers even when `instance == XR_NULL_HANDLE`.

---

## 5. Development & Verification Workflow

### 1. Build Native Libraries
```bash
uv run python native/build.py --only adapter,xrshim
```

### 2. Build and Sign APK
```bash
uv run python -X utf8 -m frameport.cli build <package.name>
```

### 3. Install to Steam Frame
```bash
uv run python -X utf8 -m frameport.cli install <package.name>
```

### 4. Headless Launch & Pacing Test
```bash
uv run python -X utf8 -m frameport.cli test <package.name>
```
Verify the output:
- `[PASS] Process: RUNNING`
- `[PASS] Submitting frames:`
- `[PASS] Frame pacing: 60+ fps`

### 5. Remote Log Inspection
Connect to Frame (`192.168.86.60`) and inspect `/home/steamos/Applications/quest-frame/<package.name>/launch.log`:
- Check for `xrEndFrame` errors or `-24` (`XR_ERROR_LAYER_LIMIT_EXCEEDED`).
- Check layer trim log:
  ```text
  xrEndFrame: layerCount 21 exceeds runtime limit 16, trimmed to 16 (proj 1/1, non-proj 15/20)
  ```
- Check passthrough activation:
  ```text
  xrEndFrame: passthrough layer -> ALPHA_BLEND environment
  ```
- Check pacing statistics:
  ```text
  FrameBridge: pacing: 72.1 fps, displayTime vs predicted: avg 0.00 ms, max 0.00 ms
  ```
