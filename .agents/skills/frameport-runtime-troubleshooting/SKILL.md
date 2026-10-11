---
name: frameport-runtime-troubleshooting
description: >-
  Use this skill when diagnosing runtime display issues (e.g. flat Android rectangle screen
  instead of VR gameplay, lepton-show-flatscreen), false "Update ready" library states
  (recipe_fingerprint and deployment.json desyncs), resolution scaling/sharpness,
  Steam shortcut renaming, and asset localization in Quest games on the Steam Frame.
---

# Steam Frame & FramePort Runtime Troubleshooting Guide

This skill documents diagnostic procedures, root causes, and solutions for runtime display anomalies, recipe/deployment state mismatches, resolution tuning, and Steam library metadata management on the Valve Steam Frame.

---

## 1. 2D Android Desktop / Rectangle Screen Instead of VR Gameplay

### Symptom
When launching a Quest VR game from Steam on the Steam Frame, the headset displays a floating 2D flat Android screen (phone/tablet window or Gamescope desktop rectangle) showing Android system UI or a flat view of the game, rather than immersing the user into full 6DOF VR.

### Root Cause
1. **The `lepton-show-flatscreen` Marker**:
   Lepton (the SteamOS Android container runtime) executes Quest apps headless by default (only OpenXR composition swapchains reach the compositor).
   If a file named `lepton-show-flatscreen` is present inside `<base>/lepton-app/` (e.g. `/home/steamos/Applications/quest-frame/<package>/lepton-app/lepton-show-flatscreen`), Lepton forces Waydroid/Gamescope to render the app as a flat 2D Wayland desktop surface.
2. **`device.text_input_window` False Positives**:
   FramePort includes a patch `TextInputWindow` (`src/frameport/patches/settings.py`, `device.text_input_window`), designed to allow text input from Steam's on-screen keyboard into Android input fields.
   When `device.text_input_window` is enabled, `src/frameport/install/installer.py` flags `flatscreen=True` during install finalization, creating the `lepton-show-flatscreen` marker.
   If `TextInputWindow.detect` (`src/frameport/patches/settings.py`) returns `Suggestion(True)` for any game with text fields (e.g. *Run*, *Angry Birds VR*, *Counter Fight ICHIRAN*), the game inadvertently installs in 2D flatscreen mode.

### Diagnosis
Check for the marker file on the Frame:
```bash
python -c "
from frameport.frame.connection import Frame, FrameTarget
f = Frame(FrameTarget('<frame-ip>', 'steamos')).connect()
ret, out, err = f.run('ls -la /home/steamos/Applications/quest-frame/<package>/lepton-app/lepton-show-flatscreen')
print('Marker present:' if ret == 0 else 'No marker')
"
```

### Live Fix (No Rebuild or Reinstall Needed)
1. **Delete the marker file on the Frame**:
   ```bash
   rm -f /home/steamos/Applications/quest-frame/<package>/lepton-app/lepton-show-flatscreen
   ```
2. **Remove `device.text_input_window` from `deployment.json` on the Frame**:
   In `/home/steamos/Applications/quest-frame/<package>/deployment.json`, remove `"device.text_input_window"` from `recipe.patches`.
3. **Update recipe in `library.json`**:
   Remove `"device.text_input_window"` from the game's `recipe.patches` so future updates or syncs do not reintroduce it.
4. **Ensure `TextInputWindow.detect` remains opt-in**:
   In `src/frameport/patches/settings.py`, `detect()` must return `Suggestion(False, ...)` so text field detection does not auto-enable the flat window.

---

## 2. False "Update Ready" States & Recipe Desync Management

### Symptom
Installed games in FramePort display "Update ready" (`outdated` style) even though the game version has not changed and the installed APK is identical.

### Root Cause
In `src/frameport/ui/components.py`, `install_state(g, frame_info)` marks an install `"outdated"` if:
1. **Binary APK mismatch**: `dep["sha256"] not in built`.
2. **Recipe changed**: `dep["sha256"] in built and recipe_changed(game)`:
   - `recipe_changed` (`src/frameport/ui/components.py`) compares the current `recipe_fingerprint(recipe)` (`src/frameport/patches/base.py`) against `build.recipe_fp` stored in `library.json`.
   - `recipe_fingerprint` hashes **all** patches in `recipe["patches"]`, including runtime-only settings (`adapter.*`, `device.*`). If any patch is removed or default recommendations change, the fingerprint changes.
3. **Settings difference**: `settings_diff(game, frame_info)` (`src/frameport/ui/components.py`) is not `None`:
   - Compares the patches list stored in remote `deployment.json` with the current recipe patches (filtering superseded patches).
   - If a patch was removed locally but remains recorded in the Frame's `deployment.json`, `settings_diff` returns `([], ['removed_patch'])`.

### The Reinstall Pitfall
If the user clicks "Update on Frame", FramePort checks if the local converted APK exists. Because FramePort removes intermediate APK copies after installation (`pipeline.remove_converted_copies` in `src/frameport/pipeline.py`), it triggers a full, redundant rebuild (OVRPort decompile, patch, repack, sign, upload) taking several minutes.

### Fast Metadata Reconciliation (Zero-Rebuild Sync)
When the APK on the Frame is already correct and only settings or default recipe definitions changed:
1. **Sync Remote `deployment.json`**:
   Update `recipe.patches` in `/home/steamos/Applications/quest-frame/<package>/deployment.json` to match `sorted(upstream.without_superseded(recipe.patches, build.superseded))`.
2. **Sync Local `build.recipe_fp`**:
   In `library.json`, update `game["build"]["recipe_fp"]` to match `recipe_fingerprint(game["recipe"])`:
   ```python
   from frameport.core import library
   from frameport.patches.base import recipe_fingerprint, load_all
   load_all()

   def sync_fp(g):
       if "build" in g and isinstance(g["build"], dict):
           g["build"]["recipe_fp"] = recipe_fingerprint(g.get("recipe") or {})
   library.update_game("<package>", sync_fp)
   ```
This immediately restores status to `"installed"` ("On Frame") without re-transferring files.

---

## 3. Resolution Scaling & Visual Sharpness (`adapter.scale`)

### Symptom
The game renders in VR, but textures and text look blurry, soft, or heavily aliased compared to native Quest rendering.

### Diagnostic Workflow
1. Inspect `launch.log` on the Frame for eye-buffer dimensions:
   ```bash
   grep -i "pacing\|eye\|resolution\|swapchain" /home/steamos/Applications/quest-frame/<package>/launch.log
   ```
2. Check if the title uses internal dynamic resolution downscaling (e.g. *Counter Fight ICHIRAN* renders at internal 0.75x / `1296x1296` vs the Frame's recommended `1728x1728`).
3. Check MSAA configuration:
   Most Unity titles on FramePort use `frame.unity_runtime_msaa_off` (`src/frameport/patches/frame/unity_runtime.py`) because multisampled renderbuffers on GLES can crash or hang the Steam Frame's GPU. Without MSAA, sub-native rendering looks especially low-res.

### Fix: Eye Buffer Multiplier
Apply `adapter.scale` via FrameBridge (available live without re-patching the APK):
```bash
uv run python -m frameport.cli settings <package> scale=1.4
```
This updates:
- `<base>/settings.conf` (`scale=1.4`)
- `/sdcard/Android/data/<package>/files/framebridge.conf`
- FrameBridge multiplies recommended eye width/height by the scale factor before allocating OpenXR swapchains.

---

## 4. Steam Library Renaming & Shortcut Preservation

### Symptom
The game displays an unreadable internal package slug in the Steam library (e.g. `neko_atsume_purrfect` instead of `Neko Atsume`, or `palazzo_santacruz` instead of `Angry Birds VR: Isle of Pigs`).

### Architecture & Update Rules
Steam shortcuts are managed across three layers:
1. **PC `library.json`**: Entry `title`.
2. **Frame `deployment.json`**: Entry `title`.
3. **Frame `shortcuts.vdf`**: Located at `/home/steamos/.local/share/Steam/userdata/<userid>/config/shortcuts.vdf`.
   - Contains binary VDF fields: `AppName`, `Exe` (`launch.sh`), `StartDir`, `icon`, `appid`.
   - **Crucial**: Changing `AppName` in `shortcuts.vdf` can alter Steam's calculated shortcut ID if not carefully matched. Existing grid artwork (`<appid>p.jpg`, `<appid>_hero.jpg`, `<appid>_logo.png`) is keyed to `appid`.
   - Updating the title requires updating `AppName` in `shortcuts.vdf` while ensuring the shortcut references the same `appid` and grid artwork paths.

---

## 5. Unity Asset & Voice Audio Localization Diagnostics

### Symptom
Changing language settings (e.g. `LANG=ja_JP.UTF-8` or `setprop persist.sys.locale ja-JP`) changes UI text, but voice acting or announcer lines remain in English.

### Diagnostic Procedure
Do not assume voice files exist simply because text localization is present. To verify offline:
1. Locate Unity global asset files in the APK (`assets/bin/Data/data.unity3d` or `sharedassets*.assets`).
2. Dump all `AudioClip` names using `UnityPy`:
   ```python
   import UnityPy
   env = UnityPy.load("data.unity3d")
   clips = [obj.read().name for obj in env.objects if obj.type.name == "AudioClip"]
   print(f"Total audio clips: {len(clips)}")
   print([c for c in clips if any(k in c.lower() for k in ["voice", "ja", "jp", "en", "narrator"])])
   ```
3. If all voice clip names lack locale variants (e.g. only `Announce_Countdown_en`, `Tutorial_en`), the game only shipped English voice audio across all platforms. Revert locale overrides to prevent unhandled fallback behavior.
