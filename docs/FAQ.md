# FAQ

## How should I lay out a game that has OBB files?

Some Quest games come as an APK (the app file) plus `.obb` files (the game's data). Give every game its own folder,
put the APK in it and put the data in a folder named after the game's **package name** (for example `com.Armature.VR4`):

```tree
Games/                                  ← scan this folder (Add games → Scan a folder)
├── Resident Evil 4/                    ← one folder per game (any name)
│   ├── VR4.apk                         ← the APK (any file name)
│   └── com.Armature.VR4/               ← the data folder: exactly the package name
│       ├── main.203.com.Armature.VR4.obb
│       └── patch.203.com.Armature.VR4.obb
└── Beat Saber/
    └── com.beatgames.beatsaber.apk     ← games without OBBs: just the APK
```

- **Data folder name:** the package name (`com.Armature.VR4` above) or `obb`.
- **Everything in that folder is copied** to the Steam Frame, subfolders included, so other data files work too.
- **One game per folder.** Several APKs in one folder count as one game.
- **Scanning:** pick the folder that contains the game folders (`Games/` above) to add them all, or one game's folder
  to add just that game. FramePort looks up to 5 levels deep.
- **A single game:** **Add games → Add an APK…** also finds the data folder next to the APK.

Not sure of the package name? It's in the OBB file names (`main.<version>.<package name>.obb`), and the game's page
shows it under **Details**.

## Can I scan SideQuest backups or AXRB downloads directly?

Yes. Scan the folder as it is; FramePort finds the APK and its OBB files in both layouts:

```tree
SideQuest Backups/                      ← scan this folder
└── com.Armature.VR4/                   ← one folder per game (the package name)
    └── 2026-10-07T02-10-19-171Z/       ← one folder per backup
        ├── apk/com.Armature.VR4.apk    ← the game
        ├── obb/                        ← its OBB files, sent to the Frame
        │   ├── main.203.com.Armature.VR4.obb
        │   ├── patch.203.com.Armature.VR4.obb
        │   └── VR4-Android-Shipping-arm64.apk   ← ignored (not a second game)
        ├── data/                       ← the app's own files on the Quest: not needed
        ├── icon.png
        └── manifest.json

AXRB/                                   ← AXRB's download folder (Downloads/AXRB): scan this folder
├── 1234567890/                         ← AXRB's numbers for the game and the build
│   └── 987654321/
│       ├── base.apk                    ← the game
│       ├── main.203.com.Armature.VR4.obb   ← sent to the Frame, with any other files here (DLC)
│       └── patch.203.com.Armature.VR4.obb
└── patched/                            ← AXRB's own PC builds: ignored
```

- **Several backups of one game:** FramePort uses the newest one. To use another, scan just that backup's folder.
- **AXRB's patched builds** (`patched/`, `*-axrb.apk`) are converted for AXRB's PC runtime and lack the game's data, so
  FramePort skips them and, on the next scan, replaces a game that was added from one with the original download.
- **AXRB export ZIPs:** unpack them first. A game's ZIP holds `base.apk` and `Android/obb/<package>/`, which FramePort
  finds as is.
- **"Game data (.obb) is missing" on the game's page** although you have the file: the backup didn't include it (copy
  the game's `Android/obb/<package>` folder from the Quest with SideQuest), or it sits in a folder FramePort doesn't
  look in. Then use the layout in the previous answer.
- **The game starts and stops at once (Steam shows Resume):** add the game again from its original download or
  backup, click **Update on Frame**, then report it (last answer on this page) if it still stops.

## Where are a game's settings in FramePort?

Every game has three places; the answers below refer to them.

- **Game settings:** right-click the game in the **Library** → **Game settings…**. Sharpness, refresh rate,
  controllers, menus and more, in plain words. Changes apply the next time the game starts.
- **Patches:** click the game in the **Library** to open its page, then **Customize** (in the **Patches** section).
  Turn a patch on or off, then click **Update on Frame** at the top of the page.
- **The game's menu:** the **…** button at the top of its page (or right-click in the Library → **More actions…**).
  It has **Reset to suggested recipe…** and **Report a problem…**, among others.

The sidebar has two tabs for troubleshooting: **Monitor** (the running game's frame rate, CPU and graphics) and
**Files** (each installed game's storage on the Frame, under **Game storage**).

## A game doesn't work right. Where do I start?

1. **Update FramePort** (it offers updates itself; Settings → Updates), then open the game's page: if it shows
   **Update on Frame**, click it. Recipes and patches improve often.
2. **Read the game's page.** The last launch test and your last play session (**Last session**) leave their result
   there, often with a suggested patch or setting and a button that applies it. Try that first.
3. **Changed patches yourself?** The game's menu → **Reset to suggested recipe…** brings back the tested ones.
4. **Find your symptom below.** Each answer says how to tell what's wrong and what to do.
5. **Still stuck?** Report it (last answer on this page).

## The game doesn't start, or stops right away

How to tell: the game's page shows the last launch test's result (**Last launch test:** …) with an explanation, and
Steam returns to **Play** or **Resume** within seconds.

- **"Game data (.obb) is missing"** on the game's page: FramePort didn't find the game's data files, so they never
  reached the Frame.
  1. Find the game's `.obb` files (named like `main.<version>.<package>.obb`).
  2. Put them in a folder named exactly the package name (shown in the file names) next to the game's APK, as in the
     first answer on this page.
  3. Library → **Add games** → **Scan a folder…** and pick the game's folder.
  4. Open the game's page and click **Update on Frame**.
- **"Lepton didn't start the game this time"**, or it failed only on the first start after an install: click **Play**
  again.
- **"This game is 32-bit only"**: the Frame can't run 32-bit apps, and no patch changes that. Look for a PC VR version
  of the game.
- **"The game quit itself right after starting"**: open the game's page and click **Update on Frame** so the suggested
  patches apply (many games check for a Quest at start, and a patch removes that).
- **Nothing like that, or it still fails:** report it.

## It hangs on a logo, a black screen or a loading screen

How to tell what it's doing: leave it running and open **Monitor** in FramePort's sidebar.

- **CPU or graphics busy:** it's still working, often preparing its shaders on the first start. Wait up to 10 minutes
  once; the next start is quicker.
- **CPU and graphics near zero:** it's stuck waiting for something. While it still hangs, open the game's menu →
  **Report a problem…** and save the diagnostics: that zip shows what each of the game's threads waits for (FramePort
  1.0.1 and newer), which a zip saved after quitting can't. Attach it to the report.
- **The game starts with a video** and hangs at its logo: game page → **Customize** → turn off **Hardware video
  decoding** → **Update on Frame**, and try again.

## The picture is wrong

Most picture problems have a setting or a patch. Change one thing at a time, then start the game again (patches also
need **Update on Frame**).

| You see | Try |
|---|---|
| Something shows in one eye only, or one eye is gray (Unity games) | Game page → **Customize** → [Unity: render each eye separately](PATCHES.md#frame-unity_multipass) |
| Left and right look swapped (depth feels wrong) | **Game settings…** → **Swap eyes** |
| Textures flicker, objects pop in and out | **Game settings…** → **Turn off space warp** |
| One eye shimmers while menus look steady | Game page → **Customize** → **Eye-tracked foveation (Valve)**: **Fixed**, else **Off** |
| Menus or screens upside down | **Game settings…** → **Fix upside-down menus** |
| Curved menus or video screens missing | **Game settings…** → **Show curved menus and screens** |
| Blurry | **Game settings…** → raise **Sharpness** (costs frame rate) |

The [patch reference](PATCHES.md) lists every patch with what it does. If nothing helps, report it with a short
description of what you see.

## It stutters or runs slowly

How to tell: open **Monitor** in the sidebar while you play. Smooth play needs the game's frame rate at the refresh
rate (for example 72 or 90 fps).

- **Below the refresh rate:** right-click the game → **Game settings…** → lower **Sharpness** (for example to 0.8×) or
  pick a lower **Refresh rate**. After a session, the game's page may suggest a value.
- **At the refresh rate but it still judders:** report it; that points to timing, not speed.

## The game pauses or recenters by itself

The Frame briefly tells games they lost focus, for example when the headset's sensor thinks you took it off.
Right-click the game → **Game settings…**: keep **Don't pause on short interruptions** on and raise **Ignore focus
dips up to** (for example to 2.5 s).

## Controllers don't work in a game

Right-click the game → **Game settings…**:

- **No controllers, or only hands:** turn on **Use controllers**.
- **Buttons work but you can't aim at menus:** adjust **Pointer angle**.
- **Vibration too strong:** lower **Vibration strength**.

## The Frame turns off or gets hot during a game

How to tell: if it only happens on battery and never while plugged in, it's power, not FramePort. Heavy games can
draw more than the battery delivers, especially at lower charge, and the Frame then turns off without an error.

- Play plugged in, or right-click the game → **Game settings…** → lower **Sharpness** to reduce the load.
- It also turns off while plugged in: report it. The diagnostics include the log of the boot that ended.

## My progress isn't saved

1. Quit through the game's own menu, not Steam's **Exit game**. Exit game closes the game at once, and some games only
   save when they exit normally.
2. Check whether it saves at all: **Files** in the sidebar → under **Game storage**, the game → look at the files'
   dates. Play, save in the game, quit from its menu and look again.
3. Nothing changes: report it.

Saves stay on the Frame when you update or reinstall a game.

## A game with mods crashes

How to tell: play once without mods and custom content. If it then works, a mod is the cause; the diagnostics zip
usually names the mod's library in the crash. Report it to the mod's author, and check for a mod version that matches
your game version.

## The game needs files I supply (ports, emulators, mods)

How to tell where they go: the game says it on screen or in its instructions, and its log names the path (in the
diagnostics zip, `launch.log`). It's usually `Android/data/<package>/files`.

1. Unpack or extract the files on your PC first: these apps read folders, not disc images (`.iso`) or archives.
2. **Files** in the sidebar → under **Game storage**, the game → open that folder → **Upload folder…** (or
   **Upload files…**). The game's menu → **Add videos and files** opens the same place.

In-game "choose a file" buttons don't work on the Frame, which has no file picker.

## How do I report a problem well?

1. Reproduce it once, then right away open the game's menu (**…** on its page) → **Report a problem…**. For a hang,
   do it while the game still hangs.
2. Say what you saw in the headset and what you already tried.
3. **Collect and open GitHub** saves a diagnostics zip and opens a prefilled game report; attach the zip to it. The
   zip holds logs, not your game files, and personal details are removed.
