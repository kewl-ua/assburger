# rfbot2 — notes for agents (rfbot 5.5)

RF Online bot built on the **BotCore** module, manual-mapped into the client (no LoadLibrary, not in the
module list). Rebuilt from the old ProjectRF bot (`hpbars.c` / `rf.py`), with all cosmetics removed.
This is the **5.5** line (the old 5.1 tree is gone, do not look for it).

## Goal / design decisions (agreed)
- **Trace kept to a minimum**: no `dinput8.dll` file in the game folder, spoof stays in the launcher only
  (never injected into the game), module is **manual-mapped** (invisible to `Module32`/`EnumProcessModules`),
  bot process masked as **Overwolf.exe**, module file named **Bagnon.dll**.
- **Kept**: target selection via game memory (`CTargetMgr::CheckTarget`), walking (`MoveRequest`), belt use
  (`CLinkBoard::UseSlot`), key presses, animus select/summon, loot, combat-packet read (who attacks you/animus).
- **Removed**: HP bars, level labels, ground-marker drawing, hiding of the game's overhead windows, Direct3D.
- **Hooks**: only 2 vtable slots (no code patching) — `CAvatar+0x84` (per-frame export + commands) and
  `CNetMsgProcessor_Combat+0x04` (attacks). Old bot hooked 5; `.rdata` edits dropped from 5 dwords to 2.

## Stealth measures (why the module is hard to spot)
The image is mapped so it does not look like a foreign blob:
- **SEC_IMAGE mapping** (`RF_MAP=image`, the default): the DLL is mapped via `NtCreateSection(SEC_IMAGE)` +
  `NtMapViewOfSection`, so the region is **`MEM_MAPPED`/`MEM_IMAGE`** — like a real module, not a private blob.
  `RF_MAP=private` (the old `VirtualAllocEx` path) or `RF_MAP=auto` (image, fall back to private) also work.
  - The kernel **applies the base relocations itself** for a SEC_IMAGE view — the mapper must NOT relocate again.
  - `NtCreateSection` needs **`PAGE_READONLY`** as the section protection for SEC_IMAGE (PAGE_READWRITE = ACCESS_DENIED).
  - The IAT lives in a read-only file-backed page: make the image RW while fixing imports, then restore section rights.
  - Freeing an image view is **`NtUnmapViewOfSection`**, not `VirtualFreeEx` (handled in `free_mapped`).
- **DOS + PE signatures wiped** in the mapped image (`_hide_headers`): no `MZ` at 0 and no `PE\0\0` at e_lfanew.
- **Section names renamed** to `.gex0..3` (post-link step in `build.ps1`), so the header does not read like a clang DLL.
- **`TimeDateStamp` zeroed** (build.ps1 post-step).
- **No absolute build path** in the image: the debug log is written next to the DLL (`g_dir`), not hardcoded.
- **Entry stub + DLL-path buffers are freed** after init (`_run_entry` waited for DllMain), so no stray private RX/RW pages.
- **Bot string literals XOR-obfuscated** (`MASK 0x5A`, `MS()`/`MASKSTR` in `src/botcore.c`): no plain `BotCore`/`RFBotState`
  in `.rdata`. Decoding must stay `volatile`, otherwise clang `-O2` constant-folds the strings back to plaintext.
- **Entry injection via `NtCreateThreadEx`** (Win32 `CreateRemoteThread` fallback) — `auto = nt -> crt`.
- Residual tell: the two hooked vtable slots point into our region (a determined vtable scan still finds us).

## Layout
- `src/botcore.c` — the module (adapted from ProjectRF `hpbars.c`). Reads `BotCore.ini` / writes `BotCore.log`
  next to the DLL path (the mapper passes it in `reserved`).
- `tools/manualmap.py` — manual PE mapper. `manual_map()` maps as SEC_IMAGE by default (`RF_MAP`), fixes the IAT
  via the target PEB, runs the entry, unlinks from the PEB. `free_mapped()` unmaps (image) / frees (private).
- `run_bot.py` — maps `build/Bagnon.dll` into the running game. `find_and_map()` is the shared entry (also
  used by `rfbot.autostart_map` for the one-click start).
- `rfbot.py` — the bot (adapted from ProjectRF `rf.py`; shared memory + commands, unchanged protocol). It is
  the single user-facing entry: self-elevates, maps the module, and exposes Map/Eject/Config/etc. in the GUI.
- `rf_bot_config.json` — bot config.
- `build.ps1` — build the DLL (clang + lld-link, `/dynamicbase`; post-steps: zero TimeDateStamp, rename sections).
- `tools/do_eject.py` — tell the module to unhook, wait for the vtable slots to be restored, then unmap it.
  The GUI "Eject" button (`rfbot.eject_module`) runs the same sequence in-process.
  **Only unmaps when both hooked vtable slots point back into the game**; otherwise the idle module stays
  mapped (freeing while a slot still points into it leaves a dangling hook -> game crash).
- `rfbot.py` is self-contained: `find_and_map()` / `_module_live()` / `is_admin()` live in it (only
  `tools/manualmap.py` is still imported). The GUI "Remap" button = eject+free+map in one click (needed after
  a rebuild / a stale module: after an eject the idle module no longer answers commands, a plain Inject would
  double-map). `run_bot.py` / `tools/*` stay runnable on their own but are no longer required by rfbot.
- `tools/peek_shm.py`, `tools/peek_snap.py`, `tools/strings.py`, `tools/hdr.py`, `tools/secprot.py` — live probes
  (shared memory, snapshot, plain strings, PE-header leftovers, region protections).

## Build (Windows, PowerShell)
```
powershell -ExecutionPolicy Bypass -File build.ps1
```
Needs LLVM in `C:\Program Files\LLVM\bin`.

## Run (IMPORTANT: mapping needs admin)
The game's DACL trims `PROCESS_VM_OPERATION`; a non-elevated shell cannot even `OpenProcess(PROCESS_ALL_ACCESS)`,
and `SeDebugPrivilege` is not in a filtered token. So mapping / eject must run **as admin** (elevated), where
`enable_debug_privilege()` then makes `PROCESS_ALL_ACCESS` work.
- **One-click, no console**: double-click `run.cmd` (windowless `pythonw.exe`). `rfbot.py` **self-elevates**
  (UAC via `ShellExecuteW "runas"`) and maps the module itself on start (unless `--no-map`), then shows the GUI.
  The game (+ spoof in the launcher) must already be running. Everything important is in the GUI (Map / Eject /
  Restart as admin / Config / Debug folder / Module log), so no extra scripts or console are needed.
- Flags: `--sys-console` (python.exe + console), `--no-elevate`, `--no-map`, `--show-console`, `--hide-console`.
- `run_overwolf.cmd` runs the bot masked as `Overwolf.exe` (still self-elevating).
- `rfbot.autostart_map()` reuses `run_bot.find_and_map()`, which reuses an already-live mapping (checks the
  `Local\RFBotState` version + fresh tick + pid), so re-running is safe and never double-maps.
- Manual: `python run_bot.py` (map only) still works. Elevation is required for the map (game runs elevated).

### Multi-client (one bot, several clients, per-character settings)
- Each client = a **profile**: `profiles/<name>/` with its own `rf_bot_config.json`, a copy of `Bagnon.dll`,
  its own `BotCore.ini` (unique `[Bot] SharedName`), its own `.mapped.json` and `BotCore.log`. The module
  derives ini/log/shm from the DLL's folder, so mapping from a per-profile DLL isolates everything.
- Run a bot per client: `pythonw rfbot.py --profile <name>` (GUI has "New client" / "Switch" too). The bot
  binds to `profiles/<name>/.target` pid (auto-picks a client without another profile's shm when unset).
- One client = one module. Do NOT map two profiles into the same game process (they'd fight over the vtable).
- `run_bot.py --dll profiles/<name>/Bagnon.dll [--pid N]`; `tools/do_eject.py --dll profiles/<name>/Bagnon.dll`.

The mapped image is at some free base (SEC_IMAGE picks one); `.mapped.json` records pid+base for eject/unmap.

## Encoding (IMPORTANT — PowerShell 5.1)
Same rules as ProjectRF: write text files as UTF-8 (no BOM) for non-ASCII; the module reads `BotCore.ini` as
ANSI/ASCII.

## Shared memory protocol
`Local\RFBotState`, `BOT_MAGIC "RFBS"`. `BOT_VERSION` is bumped on any layout change (now 9 in 5.5).
rfbot.py mirrors the structs 1:1 — keep both sides in sync. (The module still reports the runtime
value it was built with; if the bot refuses a snapshot, trust BotCore.ini / `build.ps1`, not this file.)

`BotCommand` carries a `tick` (GetTickCount at write); a command older than `BOT_CMD_STALE_MS` (2000) is
answered `BOT_CMDR_STALE` instead of being executed (a MOVE/KEY the bot dropped by timeout must not fire
later, e.g. after the game window is restored).

Module-side extras beyond ProjectRF:
- `BotEntity` has **no** distance field: distances are computed **bot-side** (`rfbot.dist_xz`) from `pos`.
- `BotSnapshot.attackRange` — your melee/attack reach (`CAvatar+0x270`, getter 0x436B80); bot derives
  `Snapshot.in_attack_range`. Note: distinct from `combat.max_attack_distance` (a bot-side gate).
- Ground loot list + `BOT_CMD_LOOT` (packet 7/2 via `_itembox_take_request` 0x540360, the space-pickup action).
  The manager is the **static object at `ADDR_GROUNDMGR` itself** (NOT dereferenced): list head at `+8`
  (`std::list`, node+0 = next, node+8 = item; item+8 = index, item+0x10 = name, item+0x50 = pos,
  item+0x280 = owner serial).
  The bot's loot tab toggles pickup, walk-to-loot (`BOT_CMD_MOVE`), "also while fighting", "only our loot", and a
  `priority_no_mobs_radius` (no monster within it -> loot becomes top priority).
- Ground item **owner** at `CGroundItem+0x280` (getter 0x40DB40; setter SetOwnerState 0x460700): own serial,
  `0xFFFFFFFF` = free for all, `0xFFFFFFFE` = party/src. The client tints the drop name green when it is yours or
  free (`0x522B20`), red otherwise; own serial = `*(g_pAvatar+0x8)`. Pickup (0x540360) is always sent, the server
  validates, so the bot can pre-filter foreign loot (`loot.only_mine`).
- Combat presses **belt slots only** (no attack key): `press_rotation` picks a ready rotation slot, else belt
  slot 1. The rotation interval (`rotation.interval_seconds`) paces the presses.

## Reverse-engineering notes
- `RF_Online_4gb_dump.exe` (`C:\SHARE\hwid`) is a **rebased** dump: game RVA = dump RVA + 0x400000. Helper scripts:
  `tools/audit.py`, `finddist.py`, `refrange.py`, `xref_call.py`.
- Attack-readiness check `0x40B230` (`gameTime - [CGP_MainGame+0x5914] op [..+0x5910]`); pickup action `0x540360`
  (xrefs 0x466702/0x466861 — the key handler). `CAvatar` range array at `+0x266/0x268/0x26C/0x270`
  (setter 0x436A20 / getter 0x436A70 by type; `+0x270` = melee reach used above). LOS still TBD.
