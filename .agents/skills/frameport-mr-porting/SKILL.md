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
> For controller binding, interaction profile remapping, or hand tracking vs. controller issues, see the companion skill `frameport-controller-input`.

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
4. **Active Room Filter (`ActiveRoomsOnly` / `IsUserInRoom`)**:
   - Unity's `OVRSceneManager` checks `ActiveRoomsOnly`. When true, `LoadSceneModelAsync` filters rooms by evaluating whether the player is inside the room polygon (`IsUserInRoom` -> `PointInPolygon2D`).
   - On the Steam Frame, synthetic guardian boundary evaluation can fail or place the tracking position outside the 2D floor polygon, causing `OVRSceneManager` to discard the synthetic room, fire `NoSceneModelToLoad`, and get stuck in capture prompts ("NoRoom", "ParseErrorRetryScan").
   - Fix: Use `frame.unity_scene_active_rooms` to patch `OVRSceneManager.IsUserInRoom` and `PointInPolygon2D` to return `true` in `libil2cpp.so`.
5. **Live Room Dimension Tuning Without Reinstalling**:
   - The emulated room dimensions can be adjusted on the fly without repatching or reinstalling the APK:
     ```powershell
     .\.venv\Scripts\python -m frameport.cli settings <package.name> scene_width=4.0 scene_depth=2.0
     ```
   - This command connects over SSH and updates `/home/steamos/Applications/quest-frame/<package>/settings.conf` directly. FrameBridge reads these values on app startup, automatically generating the `FLOOR`, `CEILING`, and 4 `WALL_FACE` entities matching the specified width and depth (default height: 2.50 m).

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

## 3. Meta Depth API, Laser Visibility & Dual-LOD Fixes (`HARD_OCCLUSION` / `SOFT_OCCLUSION`)

### The General Problem: Missing Depth Sensor
- Games utilizing Meta's Depth API (e.g. `Meta.XR.EnvironmentDepth` / `EnvironmentDepthManager`) compile shaders with `#pragma multi_compile _ HARD_OCCLUSION SOFT_OCCLUSION` (e.g. Laser Dance's `FX/Laser`).
- These shaders sample `_PreprocessedEnvironmentDepthTexture` or `_EnvironmentDepthTexture` to occlude virtual objects behind real-world physical obstacles (hands, furniture).
- The Steam Frame lacks Meta Quest's depth sensor extension (`XR_META_environment_depth`), leaving depth maps uninitialized or blank.
- The depth comparison logic treats virtual objects near the player/camera as occluded by the physical environment, causing meshes and effects (e.g. laser beams) to vanish as the player approaches them while remaining visible from far away.

### Core Fix: `frame.meta_depth_occlusion` in `libil2cpp.so`
- In Unity IL2CPP code, Meta's `EnvironmentDepthManager` controls runtime occlusion by calling `Shader.EnableKeyword("HARD_OCCLUSION")` or `Shader.EnableKeyword("SOFT_OCCLUSION")`.
- Simply renaming keyword strings in assets or `global-metadata.dat` (e.g. to `NO_OCCLUSION_X`) does not disable occlusion because `EnvironmentDepthManager` will still call `Shader.EnableKeyword` with the renamed keyword, matching the renamed shader variants.
- The proper fix implemented in `src/frameport/patches/frame/meta_depth_occlusion.py` patches `EnvironmentDepthManager` in `libil2cpp.so`:
  - `get_IsSupported` -> `RET_ZERO` (`false`).
  - `get_IsDepthAvailable` -> `RET_ZERO` (`false`).
  - `get_OcclusionShadersMode` -> `RET_ZERO` (`None`).
  - `SetOcclusionShaderKeywords` -> `RET_ZERO` (returns immediately without enabling any shader keyword).
- This prevents `Shader.EnableKeyword` from ever running, forcing Unity to render the default unoccluded shader variants.

### The Red Herring: SPIR-V Distance Factor `(dist - 2.0)`
- In shaders like `FX/Laser Beam Hard Edges` (Shader 281), SPIR-V disassembly reveals distance-to-head calculations:
  ```spirv
  %204 = (dist - 2.5, dist - 2.0)
  %211 = ((dist - 2.5) * 0.4, (dist - 2.0) * 0.5)
  %219 = clamp(%211, 0.0, 1.0) ; (factors.x, factors.y)
  ```
  At first glance, it appears that $dist \le 2.0\text{ m} \implies factors.y = 0.0$ directly zeroes the laser alpha.
- **Why this was a red herring**: Tracing the full fragment algebra in `sub_24.dis` reveals that `factors.y` is multiplied into `val_101 = col_a * (1.0 - _Transparency) * factors.y`. In Material 97, `_Transparency = 1.0`, so `(1.0 - 1.0) == 0.0`—completely eliminating the `factors.y` term! The shader distance formula was **not** the reason lasers disappeared.

### The True Root Cause: Dual-LOD Laser Swapping via `LineLod`
In *Laser Dance*, each laser consists of two separate `LineRenderer` game objects managed by `LineLod` (`MonoScript 119`):
1. **`beam_LOD1`** (LineRenderers `5496` & `5498`): Low-detail beam using **`Material 45`** (`Shader 279`: `Custom/UnlitColorInstancedFading`). This shader has no depth sensor dependencies and renders reliably on Vulkan on Steam Frame.
2. **`beam_LOD0`** (LineRenderers `5495` & `5497`): High-detail near beam using **`Material 97`** (`Shader 281`: `FX/Laser Beam Hard Edges`). Shader 281 samples Meta Quest depth textures (`_EnvironmentDepthTexture`), which fail on Steam Frame.

In `LineLod.Update()` (`RVA 0x218ED3C`), the game checks player head-to-line distance (`LineVariableType.headToLine = 0`):
- At distance $> 2.20\text{ m}$: `beam_LOD1` is enabled (`minDistance = 2.20 m, maxDistance = 9999 m`), so the player sees the working shader.
- At distance $< 2.20\text{ m}$: `LineLod` **disables `beam_LOD1` and enables `beam_LOD0`**. As soon as the player steps closer than ~2 meters, the working laser turns off and the occluded/invisible LOD0 turns on, causing the laser to vanish.

### The Offset Pitfall in Unity Serialized MonoBehaviour (`split80`)
In Component `13936`, the float value `2.20f` (`\xcd\xcc\x0c\x40` in little-endian float32) appears **twice**:
- Relative offset `+360`: `max_d` of Rule 4 (`beam_LOD0`)
- Relative offset `+432`: `min_d` of Rule 5 (`beam_LOD1`)

A naive search-and-replace (`data.find(b'\xcd\xcc\x0c\x40')`) will match the first occurrence (+360) and change `max_d` of `beam_LOD0` to `0.0`, while leaving `min_d` of `beam_LOD1` at `2.20`. This results in **both** renderers being disabled under 2.2 meters!

Similarly in Component `13814`, `2.30f` appears at:
- Relative offset `+52`: `max_d` of Rule 0 (`beam_LOD0`)
- Relative offset `+124`: `min_d` of Rule 1 (`beam_LOD1`)

### The Complete 3-Way Asset Fix (`_patch_laser_dance_assets`)
To guarantee lasers stay permanently visible at point-blank range, `meta_depth_occlusion.py` applies a coordinated 3-way asset patch:
1. **`split80` (Distance Rule Extension)**:
   - In Component `13814`: Set Rule 0 (`beam_LOD0`) `max_d` (+52) to `999.0` and Rule 1 (`beam_LOD1`) `min_d` (+124) to `0.0`.
   - In Component `13936`: Set Rule 4 (`beam_LOD0`) `max_d` (+360) to `9999.0` and Rule 5 (`beam_LOD1`) `min_d` (+432) to `0.0`.
   - **Result**: `LineLod` distance checks `min_d <= dist <= max_d` are satisfied unconditionally at all distances from $0.0\text{ m}$ to $9999.0\text{ m}$, preventing `LineLod` from ever disabling the lasers.
2. **`split79` (LineRenderer Material Redirection)**:
   - At offsets `0x20a38` and `0x20d78`, rewrite LineRenderers 5495 and 5497 `m_Materials` PPtr from `(0, 97)` to `(0, 45)`.
3. **`split0` (Material Shader Pointer Redirection)**:
   - At offset `0x7b2a0`, rewrite Material 97's `m_Shader` PPtr from `(0, 281)` to `(0, 279)`.

Together with `EnvironmentDepthManager` method zeroing in `libil2cpp.so`, this completely eliminates the close-proximity disappearing laser bug while preserving full 72 fps performance.

---

## 4. Composition Layer Limits (`maxLayerCount = 16`)

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

## 5. `xrGetInstanceProcAddr` with `XR_NULL_HANDLE`

- `OVRPlugin` often probes extension function pointers (such as Meta passthrough, scene, and performance metrics) before `xrCreateInstance` completes, calling `xrGetInstanceProcAddr(XR_NULL_HANDLE, ...)`.
- If the loader shim (`native/xrshim/xrshim.c`) rejects `XR_NULL_HANDLE`, `OVRPlugin` caches the function as unsupported and disables the MR feature entirely.
- Ensure `xrshim.c` dispatches known emulated function pointers even when `instance == XR_NULL_HANDLE`.

---

## 6. Development & Verification Workflow

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
Connect to Frame (`<frame-ip>`) and inspect `/home/steamos/Applications/quest-frame/<package.name>/launch.log`:
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
