r"""
rfbot.py - RF Online memory bot, version 5.14, for the BotCore module (C:/SHARE/rfbot2).

BotCore (build\\Bagnon.dll) is manual-mapped into the client by tools\manualmap.py (no LoadLibrary,
no module in the module list) and hooks only CAvatar+0x84 and CNetMsgProcessor_Combat+0x04 (vtable
slots, no code patching). All cosmetics are gone. Every [Bot] IntervalMs the module publishes a
snapshot of the game state in shared memory ("Local\\RFBotState", BotCore.ini [Bot]):
  - your character: world position, HP, level
  - the current target (CTargetMgr::IsTarget)
  - every monster and animus the client knows (also hidden ones): index, serial, name, level, HP, whom it
    attacked last, world position
  - all effects on your character, and marker data (anchor points)
  - your animus (as the animus window shows them) and the belt: 5 pages, with the game's own skill cooldowns
The bot reads it every 100 ms and acts through commands the module runs on the game thread with the client's
own functions: select / clear the target (CTargetMgr::CheckTarget, what a click does), walk (MoveRequest,
what a click on the ground does), use a belt slot (CLinkBoard::UseSlot, what the belt key does), press
another key (WM_KEYDOWN / WM_KEYUP to the game window), select and summon an animus, loot. Nothing is
recognised from pixels, the mouse and the keyboard are never used.

Behaviour, in this order every tick (combat.actions_first): 1. the animus (a heal / reset / summon in progress:
no attacks, no new target), 2. due actions (buffs, potions, heals; also in a fight, the attack key waits),
3. fighting:
  - no target                 -> monsters within targeting.search_radius of the anchor (world units): those that
                                 attacked your animus first, then those that attacked you, then the rest, and
                                 inside each group those within targeting.near_radius of you first (nearest),
                                 then the ones nearest to the anchor (targeting.sort 'mixed'). The bot asks the
                                 game to select the monster (exactly what a click does, also monsters behind
                                 you), then waits for the server to confirm it
  - target is a monster       -> the first ready belt slot of the rotation (window: Rotation tab) every
                                 rotation.interval_seconds; with the rotation off, empty or nothing ready: press
                                 'attack' (1) every 0.1-0.25 s (random). Switch to a monster that attacks your
                                 animus (targeting.switch_to_animus_attackers)
  - target is not a monster   -> clear it (animus, player, npc)
  - target dead / HP stuck / farther than combat.max_attack_distance -> clear it and skip that monster
  - a monster someone else fights (not yours, lost HP or attacks another player) -> attacked last
                                 (targeting.prefer_untouched, window: Monsters tab)
  - the game drops the target itself (a live monster that took no damage) twice within a minute -> skip it 60 s.
                                 Monsters the game hides from you (stealth, hidden) are never selected: the client
                                 drops them as the target every frame
  - no target for 3 s          -> walk back to the anchor (anchor.idle_return_seconds), still looking for monsters
  - alive again far from the anchor after a death (respawned elsewhere) -> the bot pauses
  - too far from the anchor   -> even with a target: walk back through the game (the game finds the path);
                                 the ticks go on meanwhile (animus, 'any' / 'in' actions, loot, hotkeys), only
                                 fighting and new targets wait until the character is back
  - animus missing            -> summon the first animus of animus.order (or the one with the most HP) that has
                                 animus.summon_min_hp (50%) of its HP and is not switched off (animus.never),
                                 like the animus window (select + summon). Never while the game says an animus is
                                 summoned (that would recall it)
  - animus died               -> (animus.heal_skill / reset_skill, window: Animus tab): as soon as the game says
                                 the heal skill is ready, heal the dead animus (it ranks before the one that would
                                 be summoned otherwise), then use the summon reset skill and summon it. A summon
                                 that brings no animus out counts as refused (summon wait): the reset skill is used
                                 then too, when it is ready. Cooldowns come from the game (belt export)
  - actions (cfg "actions", window: Actions tab) -> belt slots / keys on conditions: an effect missing / ending
                                 (buffs, potions), your HP or your animus HP below a percent (heals); out of
                                 combat, any time or in combat. Defaults: buffs Tempo 3, Vista 4, Velocity 5,
                                 Adept 6, renew 2 when one ends, potion 7. An action with a belt page (1-5) uses
                                 the slot of its key on that page, whatever page the belt shows.
                                 A renew action that twice does not extend one of its effects (while it extends
                                 the others) stops counting that effect (some buffs cannot be renewed); logged

Skill cursor: a skill / force pressed while the game would not cast it (its cooldown, the 1 s global delay
after the last skill, a cast still running) lights the skill cursor, and the next press or click then casts it at
whatever it hits. So the bot presses a skill of the belt (rotation, an attack key that holds a skill, buffs,
the animus heal / reset) only when the game's own check (CAvatar::CanUseSF) says it is ready and at least
GLOBAL_DELAY after its last skill press. An attack key that holds no skill (an AUTO macro) is pressed as before.

Your character's action (what it does: stand, walk, attack, cast...) comes from the module every frame
(status.avatarAction, CCharacter+0x250). The window button "Record actions" or Ctrl+PageDown logs every change for
15 s: cast skills and buffs, walk and attack meanwhile, then send the log, so the values that mean "casting" can be
named. Starting the bot logs whether the mapped module exports it (an older Bagnon.dll does not: rebuild, Remap).
Recorded: 0x10000000 = standing, 0x10000001 = walking, 0x3xxxxxxx (kind 3) = casting a skill / force. While your
character casts (combat.wait_while_casting) the bot presses no skill (rotation, attack key, skill actions, animus
skills), does not walk to loot or back to the anchor (a walk would break the cast); potions and other item
actions still go. Casting longer than CAST_STUCK seconds no longer holds the bot back (logged once).

Loot (loot.*, window: Main tab): drops are picked up through the game. The pickup request is sent only within
loot.pickup_range (the game answers "too far" beyond its own pickup range); a drop farther away is walked to
first (through the game) and picked up on arrival. A drop the character does not get closer to (blocked) is
skipped for loot.skip_seconds. loot.first (on by default): after a kill
the bot waits up to loot.after_kill_wait seconds for the drop and selects no new target while a wanted drop is
within reach (pickup radius, or walk radius when walking to loot is on); monsters that attack you or your animus
are still fought at once. A drop still on the ground after a pickup request is retried once a second (the second
try walks right onto it first); after loot.tries requests it is skipped for loot.skip_seconds. Drops farther than
the leash from the anchor are left. When drops lie around but none is taken, the log says why (name filter,
owner, leash, skipped); the debug hotkey lists every drop around you with its owner and why it is (not) taken.
When the module refuses the pickup command itself (object not found, wrong object class, unknown command) the drop
is skipped at once; after LOOT_REFUSED_LIMIT such refusals in a row the bot stops walking to loot and holding the
next target for it (one pickup try per drop in range still runs, so a fixed module is noticed at once).
Module builds: the bot and Bagnon.dll share BOT_VERSION. A live module of another version is never reused and
never mapped over (that would hook the game twice): press Remap (eject + fresh map). A profile's own copy of
Bagnon.dll is refreshed from build\Bagnon.dll when the build is newer. A module counts as present in a game
by its status block (pid, hooks), not by a fresh snapshot: at the login screen it publishes none, and mapping a
second copy then would hook the game twice. Eject frees the module only when it says every hook is back
(status.ejectWanted); a hook another mod chained after ours keeps it mapped.

Start: the window opens at once; mapping the module into the game (autostart) runs in the bot thread, so a slow
or stuck map never keeps the window from opening. The console has QuickEdit off: a click into it no longer
freezes the bot (Windows stops every program that writes to a console while text is being selected in it).

Bound client (profiles/<name>/.target): used only while that pid is still a running game client. After a game
restart Windows may give the old pid to another program; the bot then picks the game itself and binds to it.

Commands: the bot waits up to 1.2 s for an answer; the module drops commands older than 1 s, so one the bot gave
up on never runs late (a walk or a key press out of context).

Anchor: the ground marker you placed last (Ctrl+Shift+M). It follows the markers while the bot runs:
a new marker becomes the anchor at once, and when the anchor marker is removed the last remaining marker
takes over (without markers its position stays the anchor). The anchor hotkey or starting the bot picks
the marker nearest to you (within anchor.marker_pick_radius), else your position at that moment.
All distances are world units (a monster in the middle of the screen is about 400-500 away): press the
debug hotkey to see the distances to the anchor and to the monsters around you, and tune the config.

Own animus: the module tells which animus the game has summoned for you.

Dead monsters: the module marks a monster whose die action runs. The HP rate alone means nothing there: the client
lowers it itself on hits it sees and sets it to 0 for monsters an area attack touched (only the target gets its
HP from the server), so such monsters are alive and still attacked.

Keys: the belt keys 1-0 (BotCore.ini [Bot] BeltKeys) use their belt slot directly (CLinkBoard::UseSlot, what the
belt key does): put everything the bot uses on the belt (attack 1, renew 2, buffs 3-6, potion 7).
More than 10 actions: the belt has 5 pages; an action with a belt page uses slot 1-0 of that page directly,
without switching the page the belt shows.
Other keys are posted to the game window as WM_KEYDOWN / WM_KEYUP; F10 and Alt never (Windows turns them
into the window menu, which stalls the game).

Background: the bot fights and walks back with the game window inactive (not minimized), e.g. while you use the
bot window (other keys than belt keys: BotCore.ini [Bot] KeysWhileInactive=1).

BotCore.log: the bot shows the lines of BotCore.log (build folder) about the export, keys and errors in its own
log as "Module: ...", so its log tells what both sides did.

Window: a small control window (tkinter) shows the state, your exact position (copy / collect points), the
target, the monsters around you with an attack list, the distances and the log. python rfbot.py --nogui runs
without it.

Bot hotkeys (global: they work in any window; configurable in rf_bot_config.json -> "hotkeys"; defaults
avoid the game belt keys 1-0 / F1-F10 and the Bagnon keys Insert / F6 / F7 / F9):
  anchor (Delete)      - set the anchor (nearest ground marker, else your current position; a newly
                         placed ground marker becomes the anchor by itself)
  toggle (F11)         - start / pause the bot
  debug (PageDown)     - dump the game state to ./debug (JSON) and print a summary
  record (Ctrl+PageDown) - log every change of your character's action for 15 s (also the window button)
  quit (Ctrl+End)      - quit

Supported key names: 0-9, a-z, f1-f24, esc, space, tab, enter, insert, delete, home, end,
pageup, pagedown, pause, scrolllock; with modifiers: ctrl+end, shift+f11, ctrl+alt+delete... A hotkey
without a modifier does not fire while Ctrl / Shift / Alt is held (End alone is not Ctrl+End).

Files (same folder as the script is started from):
  rf_bot_config.json  - keys, hotkeys, timings, distances, actions (created on first run)

Requirements: Python 3.9+ (64-bit) with tkinter (part of the standard Windows installer), no extra packages.
Run the bot with the same rights as the game: if the game runs as administrator, run it as administrator
too (otherwise Windows blocks the shared memory).
"""

import copy
import ctypes
import importlib.util
import json
import math
import os
import queue
import random
import shutil
import sys
import threading
import time
import traceback
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.join(HERE, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(HERE, "tools"))
_EARLY_ERRORS = []                           # errors before log() / the window log exist; main() logs them
_mm_error = None
try:
    import manualmap as _mm
except Exception as e:                       # manualmap is optional (only for eject)
    _mm = None
    _mm_error = "%s: %s" % (type(e).__name__, e)
    _EARLY_ERRORS.append("manualmap import failed (%s): Eject cannot free the module memory." % _mm_error)

if sys.platform == "win32":
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.IsUserAnAdmin.restype = wintypes.BOOL
    shell32.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      wintypes.LPCWSTR, ctypes.c_int]
    shell32.ShellExecuteW.restype = ctypes.c_void_p      # HINSTANCE: > 32 = started


def ensure_console():
    """Become a GUI app even without python.exe: allocate a console when none is attached (pythonw.exe) and
    hide/show it per --show-console / --hide-console. Keeps one instance a single console, never a second one."""
    if sys.platform != "win32":
        return
    if not hasattr(sys, "argv"):                 # imported as a module (e.g. tools/chk_ground.py)
        return
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetConsoleWindow.restype = wintypes.HWND
    u = ctypes.WinDLL("user32", use_last_error=True)
    no_console = k.GetConsoleWindow() == 0       # started under pythonw.exe -> no console at all
    if no_console:
        k.AllocConsole()
        _reopen_std_streams()                    # bind stdout/stderr/stdin to the fresh console
    hwnd = k.GetConsoleWindow()
    if hwnd:
        _disable_quick_edit(k)
        if "--hide-console" in sys.argv[1:]:
            u.ShowWindow(hwnd, 0)
        elif "--show-console" in sys.argv[1:]:
            u.ShowWindow(hwnd, 5)


def _disable_quick_edit(k):
    """
    QuickEdit off for this console: with it, a click into the console starts a text selection ("Select" in the
    title) and Windows blocks every write to the console until Esc / Enter, so log() and with it the whole bot
    (window included) freeze. Insert mode and the other input flags stay as they are.
    """
    ENABLE_QUICK_EDIT_MODE, ENABLE_EXTENDED_FLAGS = 0x0040, 0x0080
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                              wintypes.DWORD, wintypes.HANDLE]
    k.CreateFileW.restype = wintypes.HANDLE
    k.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.GetConsoleMode.restype = wintypes.BOOL
    k.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.SetConsoleMode.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    # CONIN$ is this console's input buffer whatever stdin is (pythonw, redirected input)
    h = k.CreateFileW("CONIN$", 0x80000000 | 0x40000000, 0x1 | 0x2, None, 3, 0, None)   # read/write, share, existing
    if not h or h == wintypes.HANDLE(-1).value:
        _EARLY_ERRORS.append("Console: cannot open CONIN$ (error %d), QuickEdit stays as it is: do not click into "
                             "the console while the bot runs." % ctypes.get_last_error())
        return
    try:
        mode = wintypes.DWORD()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return
        new = (mode.value | ENABLE_EXTENDED_FLAGS) & ~ENABLE_QUICK_EDIT_MODE
        if new != mode.value and not k.SetConsoleMode(h, new):
            _EARLY_ERRORS.append("Console: QuickEdit could not be switched off (error %d): do not click into the "
                                 "console while the bot runs." % ctypes.get_last_error())
    finally:
        k.CloseHandle(h)


def _reopen_std_streams():
    """After AllocConsole, bind stdout/stderr/stdin to the new console and make them UTF-8, so log() and the
    Cyrillic game text do not raise (a pythonw process starts with stdout/stderr = None)."""
    for name, stream, mode, enc in (("stdout", "CONOUT$", "w", "utf-8"),
                                    ("stderr", "CONOUT$", "w", "utf-8"),
                                    ("stdin", "CONIN$", "r", "utf-8")):
        try:
            f = open(stream, mode, buffering=1, encoding=enc, errors="replace")
            setattr(sys, name, f)
        except Exception as e:
            _EARLY_ERRORS.append("Console: cannot bind sys.%s to %s (%s: %s)." % (name, stream, type(e).__name__, e))


ensure_console()

VERSION = "5.14"
CONFIG_FILE = "rf_bot_config.json"
DEBUG_DIR = "debug"
CONFIG_VERSION = 28
TICK_SECONDS = 0.1
PROFILES_DIR = os.path.join(HERE, "profiles")   # one folder per game client (own config / dll / shm name)
BUILD_DLL = os.path.join(HERE, "build", "Bagnon.dll")


def profile_arg(argv):
    """--profile NAME (default 'main') from argv."""
    for i, a in enumerate(argv):
        if a == "--profile" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--profile="):
            return a.split("=", 1)[1]
    return "main"


def profile_dir(name):
    return os.path.join(PROFILES_DIR, name)


PROFILE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
RESERVED_NAMES = frozenset(["con", "prn", "aux", "nul"] + ["com%d" % i for i in range(1, 10)]
                           + ["lpt%d" % i for i in range(1, 10)])


def valid_profile_name(name):
    """
    A profile name used as a single folder under profiles/ and inside the shared memory name: ASCII letters,
    digits, '.', '_' and '-' only (BotCore.ini is written and read as ANSI; no path traversal, drive or
    separator), no trailing dot, no Windows device name (CON, NUL, COM1...).
    """
    if not name or name in (".", "..") or name.endswith("."):
        return False
    if any(c not in PROFILE_CHARS for c in name):
        return False
    return name.split(".")[0].lower() not in RESERVED_NAMES


def profile_name_or_raise(name):
    if not valid_profile_name(name):
        raise ValueError("invalid profile name '%s' (ASCII letters, digits, '.', '_', '-' only)" % name)
    return name


def profile_config_file(name):
    # the default profile keeps using the historic root config so existing setups keep working
    if name == "main" and not os.path.isfile(os.path.join(profile_dir(name), CONFIG_FILE)) \
            and os.path.isfile(os.path.join(HERE, CONFIG_FILE)):
        return os.path.join(HERE, CONFIG_FILE)
    return os.path.join(profile_dir(name), CONFIG_FILE)


def profile_dll(name):
    """The profile's own Bagnon.dll copy (refreshed from build\\Bagnon.dll when the build is newer: a copy made
    once by create_profile would otherwise keep mapping an old module after every rebuild), else the build."""
    d = os.path.join(profile_dir(name), "Bagnon.dll")
    nd = os.path.join(profile_dir(name), "Bagnon.new.dll")
    if os.path.isfile(nd) and (not os.path.isfile(d) or os.path.getmtime(nd) > os.path.getmtime(d)):
        d = nd
    if not os.path.isfile(d):
        return BUILD_DLL
    try:
        if os.path.isfile(BUILD_DLL) and os.path.getmtime(BUILD_DLL) > os.path.getmtime(d) + 1.0:
            shutil.copy2(BUILD_DLL, d)
            log("Profile '%s': its Bagnon.dll was older than build\\Bagnon.dll, refreshed." % name)
    except OSError as e:
        log_limited("profdll:" + name, "Profile '%s': could not refresh %s from %s (%s: %s); it may map an old "
                    "module." % (name, d, BUILD_DLL, type(e).__name__, e), 300.0)
    return d


def list_profiles():
    if not os.path.isdir(PROFILES_DIR):
        return []
    return sorted(n for n in os.listdir(PROFILES_DIR) if os.path.isfile(profile_config_file(n)))


def create_profile(name, clone_from=None, shared_name=None):
    """Create profiles/<name>/ with its own config + DLL copy + BotCore.ini (unique SharedName) + .target.
    Each client gets its own folder, so the module reads its own ini / shm name and the bot its own config."""
    profile_name_or_raise(name)
    d = profile_dir(name)
    os.makedirs(d, exist_ok=True)
    if not os.path.isfile(os.path.join(d, "Bagnon.dll")) and os.path.isfile(BUILD_DLL):
        shutil.copyfile(BUILD_DLL, os.path.join(d, "Bagnon.dll"))
    shm = shared_name or ("Local\\RFBotState_" + name)
    # minimal BotCore.ini (the module fills the rest from its defaults); unique SharedName per client, and the
    # client's Cyrillic codepage (module builds before the fix defaulted to 1252: names came out as mojibake)
    ini = os.path.join(d, "BotCore.ini")
    if not os.path.isfile(ini):
        with open(ini, "w", encoding="ascii") as f:
            f.write("[Bot]\nEnabled=1\nCodepage=1251\nSharedName=%s\n" % shm)
    cfgp = profile_config_file(name)
    if not os.path.isfile(cfgp):
        if clone_from and os.path.isfile(profile_config_file(clone_from)):
            shutil.copyfile(profile_config_file(clone_from), cfgp)
        else:
            os.makedirs(os.path.dirname(cfgp), exist_ok=True)
            write_json(cfgp, copy.deepcopy(DEFAULT_CONFIG))
    # force the profile's own shared name into the cloned config
    try:
        with open(cfgp, "r", encoding="utf-8") as f:
            c = json.load(f)
        c.setdefault("shared", {})["name"] = shm
        write_json(cfgp, c)
    except Exception as e:                       # a clone left with the source's shm name reads the wrong client
        log_limited("profshm:" + name, "Profile '%s': could not set shared.name = %s in %s (%s: %s); set it by "
                    "hand, else it shares the shm of the profile it was cloned from."
                    % (name, shm, cfgp, type(e).__name__, e), 60.0)
    return d


ACTIVE_PROFILE = "main"
CFG_PATH = CONFIG_FILE          # set in main() to the active profile's config file

OBJ_PLAYER, OBJ_MONSTER, OBJ_ANIMUS, OBJ_AVATAR = 0, 1, 3, 15
OBJ_NAMES = {0: "player", 1: "monster", 2: "npc", 3: "animus", 4: "guard tower", 5: "crystal",
             6: "keeper", 7: "trap", 10: "type10", 11: "miner", 15: "avatar"}

DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "_note": "Distances are game world units.",
    "shared": {
        "_note": "Must match BotCore.ini [Bot] SharedName. A snapshot that did not change for stale_seconds "
                 "is treated as missing (game minimized, loading screen, UI hidden).",
        "name": "Local\\RFBotState",
        "stale_seconds": 2.0
    },
    "keys": {
        "attack": "1"
    },
    "hotkeys": {
        "anchor": "delete",
        "toggle": "f11",
        "debug": "pagedown",
        "quit": "ctrl+end",
        "record": "ctrl+pagedown"
    },
    "timing": {
        "tick_seconds": 0.1,
        "_attack_note": "Seconds between two presses of the attack key: random between min and max (window: Main).",
        "attack_interval_min": 0.1,
        "attack_interval_max": 0.25,
        "summon_interval": 3.0,
        "_select_note": "select_guard: minimum seconds between two target requests. target_confirm: longest wait "
                        "for the server to confirm a selected monster as the target.",
        "select_guard": 0.8,
        "target_confirm": 1.5,
        "target_stuck_seconds": 20.0,
        "dead_target_clear": 0.8,
        "clear_guard": 1.0
    },
    "targeting": {
        "_note": "Monsters within search_radius of the anchor (of you when there is no anchor). "
                 "sort: 'mixed' = monsters within near_radius of you first (nearest first), then the ones "
                 "nearest to the anchor; 'avatar' = nearest to you first; 'anchor' = nearest to the anchor first. "
                 "only_names / skip_names: parts of monster names (case-insensitive). Levels 0 = no limit. "
                 "attack_any: ignore only_names and attack every monster (skip_names still wins).",
        "search_radius": 500.0,
        "sort": "mixed",
        "near_radius": 150.0,
        "min_hp": 0.0,
        "skip_damaged": False,
        "attack_any": True,
        "only_names": [],
        "skip_names": [],
        "min_level": 0,
        "max_level": 0,
        "_priority_note": "Nearest monster to you first, but monsters that attacked your animus (then you) within "
                          "priority_window seconds come before the others, whatever only_names / skip_names / "
                          "levels / search_radius say (up to max(search_radius, leash) from you). "
                          "switch_to_animus_attackers: drop the current target for a monster that attacks your "
                          "animus (not more often than switch_cooldown seconds).",
        "priority_window": 6.0,
        "switch_to_animus_attackers": True,
        "switch_cooldown": 3.0,
        "_others_note": "prefer_untouched: a monster that is not yours (you have not attacked it, it does not attack "
                        "you or your animus) and has lost HP or attacks another player is probably someone else's: "
                        "it comes after the untouched ones (still attacked when there is nothing else).",
        "prefer_untouched": True,
        "_skip_note": "A monster the game could not select is ignored for skip_seconds, one the server did not "
                      "confirm as the target (or that stayed out of range) for miss_seconds.",
        "skip_seconds": 6.0,
        "miss_seconds": 10.0
    },
    "anchor": {
        "_note": "leash: walk back (through the game) when farther than this from the anchor, until closer than "
                 "return_dist. step: distance of a nearer point to walk to when the game finds no path to the "
                 "anchor itself. step_wait: seconds without moving before the next walk request. walk_timeout: "
                 "longest wait for one walk request. max_steps: walk requests per return.",
        "enabled": True,
        "marker_pick_radius": 150.0,
        "leash": 650.0,
        "return_dist": 60.0,
        "step": 200.0,
        "step_wait": 1.0,
        "walk_timeout": 30.0,
        "max_steps": 20,
        "retry_cooldown": 5.0,
        "_idle_note": "idle_return_seconds: no target for this long (nothing to attack near you) and farther than "
                      "return_dist from the anchor: walk back to it (through the game; the bot keeps looking for "
                      "monsters on the way). 0 = off.",
        "idle_return_seconds": 3.0
    },
    "combat": {
        "_note": "Targets farther than max_attack_distance (world units from you) are not attacked "
                 "(so the skill key does not make the character run to them). 0 = no limit.",
        "max_attack_distance": 0.0,
        "far_target_timeout": 2.0,
        "_switch_note": "switch_distance: a target farther than this from you (world units) for "
                        "switch_distance_seconds is left for another monster nearer to you (it is skipped for "
                        "targeting.miss_seconds); without another monster the bot keeps it. 0 = off.",
        "switch_distance": 0.0,
        "switch_distance_seconds": 1.0,
        "_actions_first_note": "actions_first: every tick the animus first (a heal / reset / summon in progress: no "
                               "attacks), then due actions (buffs, potions: also 'out' ones during a fight, the "
                               "attack key waits), then fighting. false: 'out' actions only without a target.",
        "actions_first": True,
        "_casting_note": "wait_while_casting: while your character casts (its action kind 3, from the module) the bot "
                         "presses no skill and does not walk to loot or back to the anchor (that would break the "
                         "cast; a skill pressed meanwhile lights the skill cursor).",
        "wait_while_casting": True
    },
    "animus": {
        "_note": "enabled: summon / heal your animus. absent_confirm_seconds: seconds without an animus out "
                 "before the bot summons one.",
        "enabled": True,
        "absent_confirm_seconds": 3.0,
        "_summon_note": "The module lists your animus with their HP (it regenerates while they rest). With no animus "
                        "out, the bot summons the first one of 'order' (parts of names) that has at least "
                        "summon_min_hp of its HP (the game needs 50%); empty order = the one with the most HP.",
        "order": [],
        "_never_note": "never: names of animus the bot never summons (switch them off in the window, Animus tab).",
        "never": [],
        "summon_min_hp": 0.5,
        "_revive_note": "heal_skill / reset_skill = names of skills on your belt (any page, see the "
                        "Belt tab). When an animus you would summon died (heal_recalled: also one that rests with "
                        "too little HP), the bot uses heal_skill as soon as the game says it is ready, then "
                        "reset_skill (reset_after_heal) and summons it. A summon without an animus out after "
                        "summon_check_seconds counts as refused (summon wait): reset_skill is used then too.",
        "heal_skill": "",
        "heal_recalled": False,
        "reset_skill": "",
        "reset_after_heal": True,
        "summon_check_seconds": 6.0,
        "_presses_note": "skill_presses: presses of the heal / reset skill, skill_press_delay seconds apart (the "
                         "first press lights the cursor, the second casts it on you). A press the game did not "
                         "use is retried with single presses.",
        "skill_presses": 2,
        "skill_press_delay": 0.25
    },
    "loot": {
        "_note": "Pick up ground items (drops) through the game (packet 7/2). pickup_range: the pickup request is "
                 "sent only this close (world units; the game says 'too far' beyond its own range: lower it then, "
                 "raise it when the character walks right onto every drop). Farther drops are walked to first: "
                 "radius = drops the bot goes for at once (also during a fight with in_combat), walk_radius = "
                 "drops it goes for when not fighting (walk on). "
                 "only_names / skip_names: parts of item names (case-insensitive). in_combat: also pick up while "
                 "you have a live target. delay: minimum seconds between two pickups. "
                 "priority_no_mobs_radius (0 = off): when no monster is within this distance, loot becomes the top "
                 "priority (walk to it even with a target and ignore the in_combat gate). only_mine: skip drops "
                 "owned by another player (the server would reject them); free/party loot is still taken. "
                 "first: loot before the next target: after a kill wait up to after_kill_wait seconds for the "
                 "drop, and select no new target while a wanted drop is within reach (monsters attacking you or "
                 "your animus are still fought), at most max_hold_seconds in a row. tries: pickup requests for one "
                 "drop (the second one walks onto it first), then it is skipped for skip_seconds.",
        "enabled": True,
        "pickup_range": 25.0,
        "radius": 120.0,
        "in_combat": False,
        "delay": 0.4,
        "walk": True,
        "walk_radius": 400.0,
        "priority_no_mobs_radius": 0.0,
        "only_mine": True,
        "first": True,
        "after_kill_wait": 2.0,
        "max_hold_seconds": 10.0,
        "tries": 4,
        "skip_seconds": 60.0,
        "only_names": [],
        "skip_names": []
    },
    "rotation": {
        "_note": "Combat rotation: while you have a live monster target the bot presses the belt slots in this "
                 "order (most important first), the first one whose skill is ready, then waits interval_seconds "
                 "before the next press. slots: {'page': 0 = the page the belt shows (or the first page that has "
                 "something on that slot) or 1-5, 'slot': 1-10}; a slot of another page is used directly through "
                 "the game. Rotation off, empty slots list or no slot ready = the plain attack key (keys.attack) "
                 "every timing.attack_interval_min..max seconds. only_ready: skip skills whose cooldown is still "
                 "running (needs the belt cooldowns from the module). Edit it in the window (Rotation tab).",
        "enabled": True,
        "interval_seconds": 1.0,
        "only_ready": True,
        "slots": []
    },
    "_actions_note": "Key presses on conditions, checked in this order. when: 'missing' = one of 'effects' is not "
                     "on you, 'ending' = one of them is on you with less than 'seconds' left, 'missing_or_ending', "
                     "'hp_below' / 'animus_hp_below' = your / your animus HP below 'percent'. combat: 'out' = only "
                     "without a target (one action at a time, then 'wait' seconds), 'any' = also in combat, 'in' = "
                     "only in combat. 'presses' presses 'press_delay' apart, then not again for 'cooldown' seconds. "
                     "Edit them in the window (Actions tab).",
    "actions": [
        {"name": "Tempo", "key": "3", "when": "missing", "effects": ["Tempo"], "combat": "out", "presses": 2,
         "press_delay": 0.2, "cooldown": 8.0, "wait": 1.5},
        {"name": "Vista", "key": "4", "when": "missing", "effects": ["Vista"], "combat": "out", "presses": 2,
         "press_delay": 0.2, "cooldown": 8.0, "wait": 1.5},
        {"name": "Velocity", "key": "5", "when": "missing", "effects": ["Velocity"], "combat": "out", "presses": 2,
         "press_delay": 0.2, "cooldown": 8.0, "wait": 1.5},
        {"name": "Adept", "key": "6", "when": "missing", "effects": ["Adept"], "combat": "out", "presses": 2,
         "press_delay": 0.2, "cooldown": 8.0, "wait": 1.5},
        {"name": "Renew buffs", "key": "2", "when": "ending", "effects": ["Tempo", "Vista", "Velocity", "Adept"],
         "seconds": 200, "combat": "out", "presses": 2, "press_delay": 0.5, "cooldown": 8.0, "wait": 1.5},
        {"name": "Potion", "key": "7", "when": "missing_or_ending", "effects": ["Advanced Adrenalin Potion"],
         "seconds": 10, "combat": "any", "presses": 1, "cooldown": 10.0, "wait": 0.0}
    ]
}

# Sections kept from a config older than rf.py 4.8 when it is replaced by the defaults of this version.
KEEP_ON_UPGRADE = ("keys", "hotkeys")
# Settings of removed features (mouse / keyboard modes, older module builds), deleted from a config of rf.py 4.8-4.15.
OBSOLETE = {
    None: ("screen", "mouse", "input", "background", "buffs", "potion"),
    "keys": ("summon_animus", "clear_target"),
    "timing": ("_hover_note", "hover_settle_ms", "hover_timeout", "click_hold_min", "click_hold_max",
               "_click_guard_note", "click_guard", "_select_guard_note"),
    "targeting": ("max_candidates", "_hover_note", "require_hover", "_mode_note", "mode", "hover_tries"),
    "animus": ("own_max_distance", "names", "owner_raw", "learn_hits", "present_min_hp"),
}

ACTION_WHEN = ("missing", "ending", "missing_or_ending", "hp_below", "animus_hp_below")
ACTION_COMBAT = ("out", "any", "in")
ACTION_DEFAULTS = {"name": "", "enabled": True, "key": "", "page": 0, "when": "missing", "effects": [],
                   "seconds": 10.0, "percent": 50.0, "combat": "out", "presses": 1, "press_delay": 0.2,
                   "cooldown": 8.0, "wait": 1.5}
BELT_KEYS = "1234567890"   # belt slots 1..10 in order
BELT_PAGES = 5


def normalize_action(a):
    """An action with every field (defaults for the missing ones) and sane types."""
    act = copy.deepcopy(ACTION_DEFAULTS)
    act.update({k: v for k, v in a.items() if k in ACTION_DEFAULTS})
    act["name"], act["key"] = str(act["name"]), str(act["key"]).lower()
    if isinstance(act["effects"], str):
        act["effects"] = [act["effects"]]
    act["effects"] = [str(e) for e in act["effects"] if str(e).strip()]
    if act["when"] not in ACTION_WHEN:
        act["when"] = "missing"
    if act["combat"] not in ACTION_COMBAT:
        act["combat"] = "out"
    for k in ("seconds", "percent", "press_delay", "cooldown", "wait"):
        try:
            act[k] = max(0.0, float(act[k]))
        except (TypeError, ValueError):
            act[k] = ACTION_DEFAULTS[k]
    try:
        act["presses"] = max(1, int(act["presses"]))
    except (TypeError, ValueError):
        act["presses"] = 1
    try:
        act["page"] = min(BELT_PAGES, max(0, int(act["page"])))   # 0 = the page the belt shows
    except (TypeError, ValueError):
        act["page"] = 0
    act["enabled"] = bool(act["enabled"])
    return act


def belt_slot(key):
    """Belt slot 0..9 of a belt key ('1'..'9', '0'), None for other keys."""
    key = str(key).strip()
    return BELT_KEYS.index(key) if len(key) == 1 and key in BELT_KEYS else None


def action_key_label(a):
    """'5', or '5 (p2)' for slot 5 of belt page 2."""
    return a["key"].upper() + (" (p%d)" % a["page"] if a["page"] else "")


def normalize_actions(cfg):
    """cfg['actions'] with every field (the default actions when there is no list). True if changed."""
    src = cfg.get("actions")
    if isinstance(src, list):
        acts = [normalize_action(a) for a in src if isinstance(a, dict)]
    else:
        acts = [normalize_action(a) for a in DEFAULT_CONFIG["actions"]]
    cfg["actions"] = acts
    return acts != src


def rotation_entry(value):
    """
    A rotation entry {'page': 0..5, 'slot': 1..10} (page 0 = the page the belt shows) from an int (older configs),
    a 'page:slot' string or a dict; None when it is not one.
    """
    page = 0
    try:
        if isinstance(value, dict):
            page, slot = int(value.get("page", 0)), int(value.get("slot"))
        elif isinstance(value, str) and ":" in value:
            p, s = value.split(":", 1)
            page, slot = int(p.strip().lstrip("pP")), int(s)
        else:
            slot = int(value)
    except (TypeError, ValueError):
        return None
    if not 1 <= slot <= 10 or not 0 <= page <= BELT_PAGES:
        return None
    return {"page": page, "slot": slot}


def rotation_label(entry):
    """'5' (shown page) or 'p3:5' (slot 5 of belt page 3)."""
    return ("p%d:%d" % (entry["page"], entry["slot"])) if entry["page"] else str(entry["slot"])


def normalize_rotation(cfg):
    """cfg['rotation'] with sane types; fills the defaults when the section is missing. True if changed."""
    src = cfg.get("rotation")
    rot = copy.deepcopy(DEFAULT_CONFIG["rotation"])
    if isinstance(src, dict):
        for k, v in src.items():
            if k in rot or k.startswith("_"):
                rot[k] = v
    rot["enabled"] = bool(rot["enabled"])
    rot["only_ready"] = bool(rot["only_ready"])
    try:
        rot["interval_seconds"] = max(0.2, float(rot["interval_seconds"]))
    except (TypeError, ValueError):
        rot["interval_seconds"] = 1.0
    slots = []
    for s in rot.get("slots") or []:
        entry = rotation_entry(s)
        if entry is not None and entry not in slots:
            slots.append(entry)
    rot["slots"] = slots
    cfg["rotation"] = rot
    return rot != src


def drop_obsolete(cfg):
    """Delete the settings of removed features (OBSOLETE). True if one was there."""
    changed = False
    for section, names in OBSOLETE.items():
        where = cfg if section is None else cfg.get(section)
        if not isinstance(where, dict):
            continue
        for name in names:
            if name in where:
                del where[name]
                changed = True
    return changed

FILE_MAP_WRITE, FILE_MAP_READ = 0x0002, 0x0004

SPECIAL_KEYS = {
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "tab": 0x09, "enter": 0x0D,
    "insert": 0x2D, "ins": 0x2D, "delete": 0x2E, "del": 0x2E,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
    "pause": 0x13, "scrolllock": 0x91,
}

# ---------------------------------------------------------------------------
# Shared memory layout (must match the Bot* structs in botcore.c, BOT_VERSION below)
# ---------------------------------------------------------------------------

BOT_MAGIC = 0x53424652          # "RFBS"
BOT_VERSION = 10                # 10: BotStatus.loot (older builds have no BOT_CMD_LOOT); must match botcore.c
BOT_MAP_SIZE = 0x10000
BOT_MAX_ENTITIES = 256
BOT_MAX_EFFECTS = 48
BOT_MAX_MARKERS = 32
BOT_NAME_LEN = 64

BOTF_TARGET = 0x0002
BOTF_DYING = 0x0100        # its die action runs (HP 0 alone is no death: the client guesses HP)
BOTF_HIDDEN = 0x0200       # hidden from you (stealth / hidden flag): the game drops it as the target

U32, I32, F32 = ctypes.c_uint32, ctypes.c_int32, ctypes.c_float


class BotEntity(ctypes.Structure):
    _fields_ = [("ptr", U32), ("type", I32), ("index", U32), ("serial", U32), ("flags", U32),
                ("vtable", U32), ("level", I32), ("hp", F32), ("pos", F32 * 3),
                ("victimType", I32), ("victimIndex", U32), ("victimAgeMs", U32),
                ("name", ctypes.c_char * BOT_NAME_LEN)]


class BotEffect(ctypes.Structure):
    _fields_ = [("group", ctypes.c_char * 12), ("slot", I32), ("level", I32), ("remainMs", I32),
                ("durationMs", U32), ("type", I32), ("index", U32), ("code", U32),
                ("name", ctypes.c_char * BOT_NAME_LEN), ("effect", ctypes.c_char * BOT_NAME_LEN)]


class BotMarker(ctypes.Structure):
    _fields_ = [("pos", F32 * 3)]


class BotSnapshot(ctypes.Structure):
    _fields_ = [("magic", U32), ("version", U32), ("seq", U32), ("snapshotSize", U32),
                ("entitySize", U32), ("effectSize", U32), ("counter", U32),
                ("tick", U32), ("gameTime", U32), ("pid", U32), ("intervalMs", U32), ("targetPresent", I32),
                ("attackRange", F32),
                ("avatar", BotEntity), ("target", BotEntity),
                ("markerCount", U32), ("markers", BotMarker * BOT_MAX_MARKERS),
                ("effectCount", U32), ("effects", BotEffect * BOT_MAX_EFFECTS),
                ("entityTotal", U32), ("entityCount", U32), ("entities", BotEntity * BOT_MAX_ENTITIES)]


# Status block: why there is no snapshot, what the module supports in this client. Written directly, outside the
# snapshot.
BOT_STATUS_OFFSET = 0xFF00
BOT_STATUS_MAGIC = 0x51424652   # "RFBQ"
BOT_STATE_WAIT_LEVEL, BOT_STATE_WAIT_DELAY, BOT_STATE_RUNNING, BOT_STATE_FAILED = range(1, 5)   # 0: no avatar
BOT_STAGE_NAMES = ("idle", "header", "own character", "characters", "markers", "effects", "publish", "target",
                   "command")


class BotStatus(ctypes.Structure):
    _fields_ = [("magic", U32), ("state", U32), ("tick", U32), ("hookCalls", U32), ("hookSelf", U32),
                ("avatar", U32), ("level", U32), ("levelVtable", U32), ("snapshots", U32),
                ("exCode", U32), ("exAddr", U32), ("exStage", U32), ("exObject", U32),
                ("commands", U32), ("cmdSeq", U32), ("cmdResult", U32), ("cmdTick", U32), ("keys", U32),
                ("moves", U32), ("keysInactive", U32), ("keyStateHooks", U32), ("keyHeld", U32),   # 1.10+
                                                                       # keyStateHooks: always 0 since 1.22
                ("keyWindow", U32), ("keyPresses", U32),                                           # 1.11+
                ("animusOut", U32),                                                                # 1.14+
                ("animusList", U32), ("animusIndex", U32), ("dyingKnown", U32),                    # 1.15+
                ("beltPages", U32),                                                                # 1.18+
                ("belt", U32),                                                                     # 1.19+
                ("requestPending", U32), ("requestAgeMs", U32), ("beltPage", U32),                 # 1.21+
                ("unhooked", U32), ("ejectWanted", U32),                                           # botcore
                ("loot", U32), ("pid", U32),                                                       # version 10
                ("avatarAction", U32), ("actionChanges", U32)]                                     # appended


# Command block: executed once per new seq on the game thread with the client's own functions.
BOT_COMMAND_OFFSET = 0xF100      # raised: the ground list grew (owner field)
BOT_CMD_SELECT, BOT_CMD_CLEAR, BOT_CMD_KEY, BOT_CMD_MOVE, BOT_CMD_SUMMON, BOT_CMD_SLOT = 1, 2, 3, 4, 5, 6
BOT_CMD_ANIMUS_SELECT = 7
BOT_CMD_LOOT = 8
BOT_CMD_UNHOOK = 9               # protocol only: the bot always ejects (BOT_CMD_EJECT), kept to match botcore.c
BOT_CMD_EJECT = 10
BOT_CMDR_NAMES = {0: "no result", 1: "ok", 2: "monster not found", 3: "serial differs (another monster now)",
                  4: "wrong object class", 5: "unknown command", 6: "game not ready",
                  7: "the game refused (cannot do it now)", 8: "stale (the game thread was blocked)"}
BOT_CMDR_OK = 1
BOT_CMDR_NOT_FOUND = 2
CMD_TIMEOUT = 1.2   # seconds the bot waits for a command answer; the module drops commands older than 1 s
                    # (botcore.c BOT_CMD_STALE_MS), so a command given up on here never runs late

# The two vtable slots the module hooks (botcore: ADDR_CAVATAR_VTBL + VT_RENDEROVERHEAD,
# VTBL_COMBAT_PROCESSOR + VT_ANALYSIS_PACKET). Eject polls them until they point back into the game.
MODULE_HOOK_SLOTS = (0x00A41E4C + 0x84, 0x00A4FE70 + 0x04)


class BotCommand(ctypes.Structure):
    _fields_ = [("seq", U32), ("tick", U32), ("op", U32), ("type", I32), ("index", U32), ("serial", U32),
                ("hwnd", U32), ("pos", F32 * 3)]   # pos: BOT_CMD_MOVE world point; tick: GetTickCount() at write


# Belt: 5 pages x 10 slots (page * 10 + slot), own seq (odd while writing). Skills / forces carry
# the game's own check (CAvatar::CanUseSF) and their cooldown.
BOT_BELT_OFFSET = 0xC000
BOT_BELT_SLOTS = 50
BELT_EMPTY, BELT_ITEM, BELT_SF, BELT_ANIMUS, BELT_OTHER = 0, 1, 2, 3, 4
BELT_KIND_NAMES = {BELT_ITEM: "item", BELT_SF: "skill / force", BELT_ANIMUS: "animus", BELT_OTHER: "other"}
SKILL_WAIT = 5.0   # an animus heal / reset skill ready within this many seconds is waited for
DEAD_HP = 0.10     # an animus that is gone with this HP rate or less died (the last HP the client saw may be > 0)
RESET_TRIES = 5    # heal / summon reset tries the game did not use (no cooldown started) before the bot gives up
GLOBAL_DELAY = 1.2 # the game takes no next skill for 1 s after one (CAvatar::CanUseSF, 1000 ms), with a margin
ACTION_TRIES = 5   # tries of an action the game did not use (busy, cursor) before the bot waits its cooldown
SKILL_CHECK = 1.0  # seconds after a skill press until its cooldown must have started (else: one more press)
ACTION_KIND_CAST = 3   # your character's action >> 28 while it casts a skill / force (recorded: 0x30000002)
CAST_STUCK = 8.0       # casting longer than this (seconds) no longer holds the bot back
LOOT_RETRY = 1.0   # seconds between two pickup requests for the same drop (the server's answer may still come)
LOOT_CLOSE = 5.0   # a drop not picked up from farther than this: the next try walks right onto it first
LOOT_WALK_STUCK = 4   # walk requests to a drop without getting closer before it counts as unreachable
LOOT_WALK_MAX = 15.0  # seconds of walking to one drop before it counts as unreachable
LOOT_FREE_OWNERS = (0, 0xFFFFFFFF, 0xFFFFFFFE)   # drop owners anyone may take: none recorded, free for all, party
LOOT_REFUSED = (4, 5)      # BOT_CMDR_* of a pickup the module will never run: wrong class, unknown command
                           # (BOT_CMDR_NOT_FOUND = the drop is gone meanwhile: skipped, no refusal)
LOOT_REFUSED_LIMIT = 3     # refusals in a row: no walking to loot and no loot.first hold until a pickup goes through


class BotBeltSlot(ctypes.Structure):
    _fields_ = [("kind", U32), ("sfType", U32), ("ready", I32), ("cooldownLeft", U32), ("cooldownTotal", U32),
                ("name", ctypes.c_char * 64)]


class BotBelt(ctypes.Structure):
    _fields_ = [("seq", U32), ("pages", U32), ("tick", U32), ("state", U32), ("slots", BotBeltSlot * BOT_BELT_SLOTS)]


# Animus list: your animus as the animus window shows them, own seq (odd while writing).
BOT_ANIMUS_OFFSET = 0xE000
BOT_MAX_ANIMUS = 8


class BotAnimusItem(ctypes.Structure):
    _fields_ = [("entry", U32), ("item", U32), ("hp", I32), ("maxHp", I32), ("level", U32), ("summoned", U32),
                ("name", ctypes.c_char * 64)]


class BotAnimusList(ctypes.Structure):
    _fields_ = [("seq", U32), ("count", U32), ("tick", U32), ("state", U32),
                ("items", BotAnimusItem * BOT_MAX_ANIMUS)]


# Ground items (loot on the floor), own seq (odd while writing).
BOT_GROUND_OFFSET = 0xE400
BOT_MAX_GROUND = 48
BOT_GROUND_NAME = 40


class BotGroundItem(ctypes.Structure):
    _fields_ = [("ptr", U32), ("index", U32), ("owner", U32), ("pos", F32 * 3),
                ("name", ctypes.c_char * BOT_GROUND_NAME)]


class BotGroundList(ctypes.Structure):
    _fields_ = [("seq", U32), ("count", U32), ("tick", U32), ("state", U32),
                ("items", BotGroundItem * BOT_MAX_GROUND)]


SNAPSHOT_SIZE = ctypes.sizeof(BotSnapshot)
SEQ_OFFSET = BotSnapshot.seq.offset

# ---------------------------------------------------------------------------
# Win32 interop
# ---------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL

kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenFileMappingW.restype = wintypes.HANDLE
kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_size_t]
kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
kernel32.UnmapViewOfFile.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                       ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype = wintypes.BOOL
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def set_dpi_aware():
    """Sharp window text on scaled displays."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:                            # no shcore before Windows 8.1: the older call below
        try:
            user32.SetProcessDPIAware()
        except Exception as e:
            log_limited("dpi", "DPI awareness not set (%s: %s): the window text may be blurry."
                        % (type(e).__name__, e), 3600.0)


def get_tick():
    """GetTickCount(): the same millisecond clock the DLL writes into every snapshot."""
    return int(kernel32.GetTickCount()) & 0xFFFFFFFF


def tick_diff(a, b):
    """a - b in ms for 32-bit tick counts (handles the wrap-around)."""
    d = (a - b) & 0xFFFFFFFF
    return d - 0x100000000 if d >= 0x80000000 else d


def get_window_title(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def get_client_rect_on_screen(hwnd):
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    pt = POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return pt.x, pt.y, rect.right - rect.left, rect.bottom - rect.top


def find_process_window(pid):
    """The visible top-level window of `pid` with the largest client area, or None."""
    found = []

    def callback(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            rc = get_client_rect_on_screen(hwnd)
            if rc and rc[2] > 0 and rc[3] > 0:
                found.append((rc[2] * rc[3], hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    if not found:
        return None
    found.sort(key=lambda item: item[0], reverse=True)
    return found[0][1]


def process_image_path(pid):
    """Full path of the exe of process `pid`, or None (no rights: run the bot like the game)."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value
    finally:
        kernel32.CloseHandle(handle)


def hwid_game_profile(pid):
    """Game profile (C:\\SHARE\\hwid\\profiles.json) for a game PID: id/label/bot_profile."""
    exe = process_image_path(pid)
    if not exe:
        return None
    try:
        path = os.path.join(os.path.dirname(HERE), "hwid", "profiles.json")
        if not os.path.isfile(path):
            path = r"C:\SHARE\hwid\profiles.json"
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        d = os.path.normcase(os.path.dirname(exe))
        for p in data.get("profiles", []):
            if os.path.normcase(os.path.dirname(p.get("game_exe") or "")) == d:
                return p
    except Exception:
        pass
    return None


def vk_from_name(name):
    n = str(name).strip().lower().replace(" ", "")
    if len(n) == 1 and n.isalnum():
        return ord(n.upper())
    if n.startswith("f") and n[1:].isdigit() and 1 <= int(n[1:]) <= 24:
        return 0x6F + int(n[1:])  # f1 = 0x70
    if n in SPECIAL_KEYS:
        return SPECIAL_KEYS[n]
    raise ValueError("Unknown key name in config: %r" % name)


MODIFIER_VKS = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12}
ALL_MODIFIERS = (0x10, 0x11, 0x12)


def hotkey_from_name(name):
    """(vk, modifier vks) of a hotkey like 'f11' or 'ctrl+end'; ValueError for an unknown name."""
    parts = [p for p in str(name).strip().lower().replace(" ", "").split("+") if p]
    if not parts:
        raise ValueError("Empty hotkey in config")
    mods = set()
    for p in parts[:-1]:
        if p not in MODIFIER_VKS:
            raise ValueError("Unknown modifier %r in hotkey %r (ctrl, shift, alt)" % (p, name))
        mods.add(MODIFIER_VKS[p])
    return vk_from_name(parts[-1]), tuple(sorted(mods))


class Hotkeys:
    """
    Global hotkeys {name: (vk, modifiers)}: one fires once when its key goes down with exactly its modifiers held
    (a hotkey without modifiers does not fire while Ctrl / Shift / Alt is held).
    """

    def __init__(self, hotkeys):
        self.keys = dict(hotkeys)
        self.prev = {name: False for name in self.keys}

    @staticmethod
    def down(vk):
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    def pressed(self, name):
        vk, mods = self.keys[name]
        down = (self.down(vk) and all(self.down(m) for m in mods)
                and not any(self.down(m) for m in ALL_MODIFIERS if m not in mods))
        was_down = self.prev[name]
        self.prev[name] = down
        return down and not was_down

# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------


def dist_xz(ax, az, bx, bz):
    return math.hypot(ax - bx, az - bz)


def _text(raw):
    return raw.decode("utf-8", "replace")


class Entity:
    """One character from the snapshot (monster, animus, player, npc, your own character)."""
    __slots__ = ("ptr", "type", "index", "serial", "flags", "vtable", "level", "hp", "distance", "x", "y", "z",
                 "victim_type", "victim_index", "victim_age_ms", "name", "alive")

    def __init__(self, e, dying_known=False):
        self.ptr = e.ptr
        self.type = e.type
        self.index = e.index
        self.serial = e.serial
        self.flags = e.flags
        self.vtable = e.vtable
        self.level = e.level
        self.hp = e.hp
        self.distance = 0.0                    # XZ distance to your own character (set by Snapshot)
        self.x, self.y, self.z = e.pos[0], e.pos[1], e.pos[2]
        self.victim_type = e.victimType          # monsters: whom they attacked last (packet 5/13), -1 = nobody
        self.victim_index = e.victimIndex
        self.victim_age_ms = e.victimAgeMs       # 0xFFFFFFFF = never
        self.name = _text(e.name)
        # the module knows who is dying; the HP rate is no death sign there (the client sets it to 0 itself for
        # monsters an area attack touched, only the target gets its real HP from the server)
        self.alive = not (e.flags & BOTF_DYING) if dying_known else e.hp > 0

    @property
    def key(self):
        return self.ptr, self.serial

    @property
    def is_target(self):
        return bool(self.flags & BOTF_TARGET)

    @property
    def hidden(self):
        return bool(self.flags & BOTF_HIDDEN)

    @property
    def type_name(self):
        return OBJ_NAMES.get(self.type, "type%d" % self.type)

    def dist(self, x, z):
        return dist_xz(self.x, self.z, x, z)

    def label(self):
        return "%s '%s' Lv.%d #%d" % (self.type_name, self.name, self.level, self.index)

    def to_dict(self):
        return {"ptr": "0x%08X" % self.ptr, "type": self.type, "type_name": self.type_name,
                "index": self.index, "serial": self.serial, "flags": "0x%04X" % self.flags,
                "vtable": "0x%08X" % self.vtable, "level": self.level, "hp": round(self.hp, 4),
                "pos": [round(self.x, 2), round(self.y, 2), round(self.z, 2)],
                "victim": [self.victim_type, self.victim_index, self.victim_age_ms], "name": self.name}


class Snapshot:
    """Python copy of one BotSnapshot."""

    def __init__(self, raw, read_tick, dying_known=False):
        self.counter = raw.counter
        self.tick = raw.tick
        self.game_time = raw.gameTime
        self.pid = raw.pid
        self.interval_ms = raw.intervalMs
        self.age_ms = max(0, tick_diff(read_tick, raw.tick))
        self.attack_range = raw.attackRange      # your attack reach (world units), 0 = unknown
        self.avatar = Entity(raw.avatar)
        self.target = Entity(raw.target, dying_known) if raw.targetPresent else None
        self.entity_total = raw.entityTotal
        self.entities = [Entity(raw.entities[i], dying_known) for i in range(min(raw.entityCount, BOT_MAX_ENTITIES))]
        # distances to your own character, computed bot-side from positions
        ax, az = self.avatar.x, self.avatar.z
        for e in self.entities:
            e.distance = dist_xz(e.x, e.z, ax, az)
        if self.target is not None:
            self.target.distance = dist_xz(self.target.x, self.target.z, ax, az)
        self.avatar.distance = 0.0
        self.markers = []
        for i in range(min(raw.markerCount, BOT_MAX_MARKERS)):
            m = raw.markers[i]
            self.markers.append({"pos": (m.pos[0], m.pos[1], m.pos[2])})
        self.effects = []
        for i in range(min(raw.effectCount, BOT_MAX_EFFECTS)):
            e = raw.effects[i]
            self.effects.append({"group": _text(e.group), "slot": e.slot, "name": _text(e.name),
                                 "effect": _text(e.effect), "level": e.level, "remain_ms": e.remainMs,
                                 "duration_ms": e.durationMs, "type": e.type, "index": e.index, "code": e.code})

    def find(self, key):
        for e in self.entities:
            if e.key == key:
                return e
        if self.target is not None and self.target.key == key:
            return self.target
        return None

    def to_dict(self):
        return {"counter": self.counter, "tick": self.tick, "game_time": self.game_time, "pid": self.pid,
                "interval_ms": self.interval_ms, "age_ms": self.age_ms, "avatar": self.avatar.to_dict(),
                "target": self.target.to_dict() if self.target else None,
                "entity_total": self.entity_total, "entities": [e.to_dict() for e in self.entities],
                "markers": self.markers, "effects": self.effects}


class ModuleLog:
    """
    The lines of BotCore.log (next to the mapped Bagnon.dll, build\\) about the bot export, keys and errors,
    shown in the bot log as 'Module: ...', so one log tells what both sides did.
    """
    KEEP = ("BotCore", "bot ", "ERROR", "config [", "module ", "hooked ", "signature mismatch", "client ")
    RETRY_SECONDS = 30.0

    def __init__(self):
        self.pid = None
        self.path = None
        self.pos = 0
        self.searched = 0.0            # last search for the log file (it may appear after the first map)
        self.reported = False          # "not found" logged for this pid

    def attach(self, pid):
        if pid == self.pid and (self.path or time.time() - self.searched < self.RETRY_SECONDS):
            return
        if pid != self.pid:
            self.pid, self.path, self.pos, self.reported = pid, None, 0, False
        self.searched = time.time()
        # BotCore writes its log next to the mapped DLL (build\BotCore.log), older builds into the game folder
        cands = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "BotCore.log")]
        exe = process_image_path(pid)
        if exe:
            cands.append(os.path.join(os.path.dirname(exe), "BotCore.log"))
        for path in cands:
            if path and os.path.exists(path):
                self.path = path
                if self.reported:
                    log("BotCore.log found: %s." % path)
                return
        if not self.reported:
            self.reported = True
            log("BotCore.log not found (looked at %s, again every %.0f s): its key and command reports are not "
                "shown here." % (", ".join(cands), self.RETRY_SECONDS))

    def poll(self):
        if not self.path:
            return
        try:
            size = os.path.getsize(self.path)
            if size < self.pos:        # a new game run starts a new log
                self.pos = 0
            if size == self.pos:
                return
            with open(self.path, "rb") as f:
                f.seek(self.pos)
                data = f.read(size - self.pos)
        except OSError:
            return
        end = data.rfind(b"\n") + 1    # a line being written stays for the next poll
        self.pos += end
        for line in data[:end].decode("utf-8", "replace").splitlines():
            text = line.split("  ", 1)[-1].strip()   # without the module's time stamp
            if any(k in text for k in self.KEEP):
                log("Module: %s" % text)


class SharedMemory:
    """Reader of the module snapshot, animus list, belt and status + writer of commands."""

    def __init__(self, name, stale_seconds, lock=None, cmd_lock=None):
        self.name = name
        self.stale_seconds = float(stale_seconds)
        self.handle = None
        self.view = None
        self.status = "not opened yet"
        self.last_counter = None
        self.last_pid = None
        self.last_change = 0.0
        self.cached = None             # last parsed Snapshot, reused until the DLL writes a new one
        self.cached_seq = None
        self.block_cache = {}          # {(offset, variant): (seq, parsed value)} of the animus / belt / ground blocks
        self.cmd_seq = int(time.time() * 1000) & 0x7FFFFFFF   # differs from the last seq of an older bot run
        # guards view lifetime (close vs. a reader's memmove) AND command writes: the worker thread and the
        # GUI (Eject button) both call command(), and close() runs on the GUI thread after mainloop.
        # Pass a shared lock when two instances (bot + GUI reader) write the same command block.
        self.lock = lock if lock is not None else threading.RLock()
        # serializes whole commands (write + wait for the answer) between the threads; self.lock is held only for
        # short reads / writes of the view, so a reader (the window) never waits up to 1.2 s for a command answer
        self.cmd_lock = cmd_lock if cmd_lock is not None else threading.RLock()

    def open(self):
        with self.lock:
            if self.view:
                return True
            handle = kernel32.OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, False, self.name)
            if not handle:
                self.status = ("shared memory '%s' not found (game not started, module not mapped (Inject), "
                               "BotCore.ini [Bot] Enabled=0, or the bot runs without administrator rights)"
                               % self.name)
                return False
            view = kernel32.MapViewOfFile(handle, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, BOT_MAP_SIZE)
            if not view:
                kernel32.CloseHandle(handle)
                self.status = "MapViewOfFile '%s' failed (error %d)" % (self.name, ctypes.get_last_error())
                return False
            self.handle, self.view = handle, view
            return True

    def close(self):
        with self.lock:
            if self.view:
                kernel32.UnmapViewOfFile(self.view)
            if self.handle:
                kernel32.CloseHandle(self.handle)
            self.handle = self.view = None
            self.cached = self.cached_seq = None
            self.block_cache.clear()

    def _copy(self):
        """(raw snapshot, seq) copied consistently (seqlock), or (None, None)."""
        with self.lock:
            if not self.view:
                return None, None
            seq_ref = U32.from_address(self.view + SEQ_OFFSET)
            raw = BotSnapshot()
            for _ in range(10):
                s1 = seq_ref.value
                if s1 == 0:
                    return None, None      # nothing written in this game run yet
                if s1 & 1:
                    time.sleep(0.002)
                    continue
                ctypes.memmove(ctypes.addressof(raw), self.view, SNAPSHOT_SIZE)
                if seq_ref.value == s1:
                    return raw, s1
            return None, None

    def is_stale(self, now):
        if now - self.last_change > self.stale_seconds:
            self.status = "game state is not updated for %.0f s: %s" % (now - self.last_change, self.dll_status())
            return True
        return False

    def dll_status(self):
        """What the module reports about its export (why there is no fresh snapshot)."""
        with self.lock:
            if not self.view:
                return "shared memory not open"
            st = BotStatus.from_address(self.view + BOT_STATUS_OFFSET)
            if st.magic != BOT_STATUS_MAGIC:
                return "no status from the module (Bagnon.dll too old? rebuild and Remap), see BotCore.log"
            if st.state == BOT_STATE_FAILED:
                stage = BOT_STAGE_NAMES[st.exStage] if st.exStage < len(BOT_STAGE_NAMES) else str(st.exStage)
                return ("The module export faulted: exception 0x%08X at 0x%08X while reading %s (object 0x%08X); "
                        "it is paused and retried by the module (10-60 s), please send this line if it repeats"
                        % (st.exCode, st.exAddr, stage, st.exObject))
            if st.hookCalls == 0:
                return "The module has not drawn your character yet (enter the world; the game UI must not be hidden)"
            if st.tick == 0:
                return ("The module draws CAvatar 0x%08X, but your character is 0x%08X, so it never exports; please "
                        "send this line" % (st.hookSelf, st.avatar))
            age = tick_diff(get_tick(), st.tick) / 1000.0
            if age > 2.0:
                return ("The module stopped checking %.0f s ago (game minimized, loading screen or UI hidden; "
                        "%d snapshots so far)" % (age, st.snapshots))
            if st.state == BOT_STATE_WAIT_LEVEL:
                return ("The module waits for the map to load (level 0x%08X, vtable 0x%08X)"
                        % (st.level, st.levelVtable))
            if st.state == BOT_STATE_WAIT_DELAY:
                return "The module waits StartDelayMs after entering the world"
            if st.state == BOT_STATE_RUNNING:
                return "The module is running (%d snapshots)" % st.snapshots
            return "The module state %d (level 0x%08X, vtable 0x%08X)" % (st.state, st.level, st.levelVtable)

    def read(self):
        with self.lock:
            if not self.open() or not self.view:
                return None
            magic = U32.from_address(self.view).value
            version = U32.from_address(self.view + 4).value
            if magic != BOT_MAGIC:
                self.status = "shared memory '%s' is not initialised yet" % self.name
                return None
            if version != BOT_VERSION:
                self.status = ("module version %d, this bot needs %d: another Bagnon.dll build is mapped in the "
                               "game (rebuild it from the current botcore.c, then press Remap)"
                               % (version, BOT_VERSION))
                return None
            now = time.time()
            if self.cached is not None and U32.from_address(self.view + SEQ_OFFSET).value == self.cached_seq:
                if self.is_stale(now):
                    return None
                self.cached.age_ms = max(0, tick_diff(get_tick(), self.cached.tick))
                return self.cached
            raw, seq = self._copy()
            if raw is None:
                self.status = "no snapshot yet: %s" % self.dll_status()
                return None
            if (raw.snapshotSize, raw.entitySize, raw.effectSize) != (
                    SNAPSHOT_SIZE, ctypes.sizeof(BotEntity), ctypes.sizeof(BotEffect)):
                self.status = "snapshot layout mismatch (DLL %d/%d/%d, bot %d/%d/%d)" % (
                    raw.snapshotSize, raw.entitySize, raw.effectSize,
                    SNAPSHOT_SIZE, ctypes.sizeof(BotEntity), ctypes.sizeof(BotEffect))
                return None
            if raw.counter != self.last_counter or raw.pid != self.last_pid:
                self.last_counter, self.last_pid = raw.counter, raw.pid
                self.last_change = now
            elif self.is_stale(now):
                return None
            self.status = "ok"
            self.cached, self.cached_seq = Snapshot(raw, get_tick(), self.dll_flag("dyingKnown")), seq
            return self.cached

    def dll_flag(self, name):
        """A capability of the module from its status block (commands, keys, moves, keysInactive)."""
        with self.lock:
            if not self.open() or not self.view:
                return False
            st = BotStatus.from_address(self.view + BOT_STATUS_OFFSET)
            return st.magic == BOT_STATUS_MAGIC and getattr(st, name) == 1

    def supports_commands(self):
        return self.dll_flag("commands")

    def supports_keys(self):
        """Key presses through the game: status.keys = 2 (key messages to the game window)."""
        with self.lock:
            if not self.open() or not self.view:
                return False
            st = BotStatus.from_address(self.view + BOT_STATUS_OFFSET)
            return st.magic == BOT_STATUS_MAGIC and st.keys == 2

    def _read_block(self, offset, struct, parse, variant=0):
        """
        A block with its own seq (odd while the module writes it), copied consistently and parsed by parse(raw);
        the parsed value is kept until the module writes the block again (the bot asks several times per tick).
        [] when the module marks it empty (state 0); while it is being written, the last consistent copy (None when
        there is none yet).
        """
        with self.lock:
            if not self.open() or not self.view:
                return None
            src = self.view + offset
            key = (offset, variant)
            cached = self.block_cache.get(key)
            if cached is not None and U32.from_address(src).value == cached[0]:
                return cached[1]
            for _ in range(5):
                seq = U32.from_address(src).value
                if seq & 1:
                    time.sleep(0.002)
                    continue
                raw = struct()
                ctypes.memmove(ctypes.addressof(raw), src, ctypes.sizeof(struct))
                if U32.from_address(src).value != seq:
                    continue
                value = parse(raw) if raw.state else []
                self.block_cache[key] = (seq, value)
                return value
            return cached[1] if cached is not None else None   # still being written: the last consistent copy

    def animus_list(self):
        """
        Your animus [{'entry', 'name', 'hp', 'max_hp', 'rate', 'level', 'summoned'}], None when the module has no
        animus list (the game's code differs).
        """
        if not self.dll_flag("animusList"):
            return None

        def parse(raw):
            out = []
            for it in raw.items[:min(raw.count, BOT_MAX_ANIMUS)]:
                max_hp = max(0, it.maxHp)
                out.append({"entry": it.entry, "name": _text(it.name), "hp": it.hp, "max_hp": max_hp,
                            "rate": (it.hp / float(max_hp)) if max_hp else 0.0, "level": it.level,
                            "summoned": bool(it.summoned)})
            return out

        return self._read_block(BOT_ANIMUS_OFFSET, BotAnimusList, parse)

    def ground(self):
        """
        Loot on the floor [{'index', 'name', 'pos', 'owner'}], None when the module has no ground list, [] when it
        is empty. 'owner' is the drop's owner serial: your own index, 0xFFFFFFFF = free for all, 0xFFFFFFFE = party.
        """
        def parse(raw):
            return [{"index": it.index, "name": _text(it.name), "owner": it.owner,
                     "pos": (it.pos[0], it.pos[1], it.pos[2])}
                    for it in raw.items[:min(raw.count, BOT_MAX_GROUND)] if it.index]

        return self._read_block(BOT_GROUND_OFFSET, BotGroundList, parse)

    def ground_info(self):
        """(seq, count, state) of the ground block as the module wrote it; None when the view is not open.
        seq 0 = the module never wrote it (a build without the ground export)."""
        with self.lock:
            if not self.open() or not self.view:
                return None
            src = self.view + BOT_GROUND_OFFSET
            return (U32.from_address(src).value, U32.from_address(src + 4).value,
                    U32.from_address(src + 12).value)

    def animus_index(self):
        """Object index of your summoned animus, None = none / unknown."""
        with self.lock:
            if not self.open() or not self.view:
                return None
            st = BotStatus.from_address(self.view + BOT_STATUS_OFFSET)
            if st.magic != BOT_STATUS_MAGIC or not st.animusList or st.animusIndex == 0xFFFFFFFF:
                return None
            return st.animusIndex

    def animus_out(self):
        """True = the game has an animus summoned, False = none, None = unknown."""
        with self.lock:
            if not self.open() or not self.view:
                return None
            st = BotStatus.from_address(self.view + BOT_STATUS_OFFSET)
            if st.magic != BOT_STATUS_MAGIC or st.animusOut not in (0, 1):
                return None
            return st.animusOut == 1

    def belt(self):
        """
        The non-empty belt slots [{'page' 1-5, 'key' '1'..'0', 'kind' BELT_*, 'name', 'ready', 'left',
        'total'}], None when the module has no belt export. ready (skills / forces): 1 = usable now, 0 = not now
        (global or shared delay), -1 = its own cooldown runs, 2 = unknown; left / total: cooldown in seconds.
        """
        with self.lock:
            if not self.open() or not self.view:
                return None
            st = BotStatus.from_address(self.view + BOT_STATUS_OFFSET)
            if st.magic != BOT_STATUS_MAGIC or st.belt not in (1, 2):
                return None
            mode = st.belt
        cooldowns = mode == 2                  # 2: skills / forces carry the game's check and cooldown

        def parse(raw):
            out = []
            for i, s in enumerate(raw.slots):
                if s.kind == BELT_EMPTY:
                    continue
                sf = s.kind == BELT_SF and cooldowns
                out.append({"page": i // 10 + 1, "key": BELT_KEYS[i % 10], "kind": s.kind, "name": _text(s.name),
                            "ready": s.ready if sf else 2, "left": s.cooldownLeft / 1000.0 if sf else 0.0,
                            "total": s.cooldownTotal / 1000.0 if sf else 0.0})
            return out

        return self._read_block(BOT_BELT_OFFSET, BotBelt, parse, variant=mode)

    def status_field(self, name):
        """A field of the module's status block, None when there is no status (no module / not initialised)."""
        with self.lock:
            if not self.open() or not self.view:
                return None
            st = BotStatus.from_address(self.view + BOT_STATUS_OFFSET)
            return getattr(st, name) if st.magic == BOT_STATUS_MAGIC else None

    def unhooked(self):
        """True = the module removed its hooks (idle); None = unknown."""
        with self.lock:
            if not self.open() or not self.view:
                return None
            st = BotStatus.from_address(self.view + BOT_STATUS_OFFSET)
            if st.magic != BOT_STATUS_MAGIC:
                return None
            return bool(st.unhooked)

    def belt_page(self):
        """Belt page the belt shows (1-5), None = unknown."""
        with self.lock:
            if not self.open() or not self.view:
                return None
            st = BotStatus.from_address(self.view + BOT_STATUS_OFFSET)
            return st.beltPage + 1 if st.magic == BOT_STATUS_MAGIC and st.beltPage < BELT_PAGES else None

    def request_pending(self):
        """True while a request (e.g. the animus summon) waits for the server's answer."""
        with self.lock:
            if not self.open() or not self.view:
                return False
            st = BotStatus.from_address(self.view + BOT_STATUS_OFFSET)
            return st.magic == BOT_STATUS_MAGIC and st.requestPending == 1 and st.requestAgeMs < 30000

    def belt_pages(self):
        """Belt pages BOT_CMD_SLOT can use (5), 0 = not supported or no belt yet."""
        with self.lock:
            if not self.open() or not self.view:
                return 0
            st = BotStatus.from_address(self.view + BOT_STATUS_OFFSET)
            return st.beltPages if st.magic == BOT_STATUS_MAGIC and st.beltPages <= 16 else 0

    def supports_moves(self):
        return self.dll_flag("moves")

    def command(self, op, obj_type=0, index=0, serial=0, pos=(0.0, 0.0, 0.0), hwnd=0, timeout=CMD_TIMEOUT):
        """Run a command in the game (BOT_CMD_*): result code (BOT_CMDR_*), or None on timeout."""
        with self.cmd_lock:                  # one command at a time (worker thread and window buttons)
            with self.lock:
                if not self.open() or not self.view:
                    return None
                self.cmd_seq = (self.cmd_seq + 1) & 0xFFFFFFFF or 1
                seq = self.cmd_seq
                cmd = BotCommand(0, get_tick(), op, obj_type, index, serial, hwnd or 0, (F32 * 3)(*pos))
                base = self.view + BOT_COMMAND_OFFSET
                head = BotCommand.tick.offset    # copy from tick on; seq is written last (its own store below)
                ctypes.memmove(base + head, ctypes.addressof(cmd) + head, ctypes.sizeof(BotCommand) - head)
                U32.from_address(base).value = seq                   # seq last: the DLL takes the command now
            deadline = time.time() + timeout
            while time.time() < deadline:
                with self.lock:                  # short: the view may be closed meanwhile
                    if not self.view:
                        return None
                    st = BotStatus.from_address(self.view + BOT_STATUS_OFFSET)
                    if st.cmdSeq == seq:
                        return st.cmdResult
                time.sleep(0.01)
            return None

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


LOG_QUEUE = None   # queue.Queue of log lines for the window, None without the window


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)
    if LOG_QUEUE is not None:
        LOG_QUEUE.put(line)


_LOG_TIMES = {}    # {key: [last time logged, repeats dropped since]} for log_limited()


def log_limited(key, msg, every=5.0):
    """log() at most once per `every` seconds per key (module-level twin of Bot.log_limited, for code outside
    the Bot and paths that run every tick / GUI refresh); the next line logged tells how many were dropped."""
    now = time.time()
    entry = _LOG_TIMES.setdefault(key, [0.0, 0])
    if now - entry[0] < every:
        entry[1] += 1
        return
    if entry[1]:
        msg = "%s (+%d repeats in %.0f s)" % (msg, entry[1], now - entry[0])
    entry[0], entry[1] = now, 0
    log(msg)


def merge_defaults(cfg, defaults):
    changed = False
    for key, value in defaults.items():
        if key not in cfg:
            cfg[key] = copy.deepcopy(value)
            changed = True
        elif isinstance(value, dict) and isinstance(cfg[key], dict):
            changed = merge_defaults(cfg[key], value) or changed
    return changed


def write_json(path, data):
    """Write JSON atomically: write a temp file in the same dir, fsync, then replace. A crash mid-write
    (or a killed process) leaves the previous file intact instead of a truncated/invalid one."""
    tmp = "%s.tmp.%d" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)          # atomic on the same volume (Windows + POSIX)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def load_config():
    path = CFG_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not os.path.exists(path):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        normalize_actions(cfg)
        normalize_rotation(cfg)
        write_json(path, cfg)
        log("Created default config: %s" % path)
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (ValueError, UnicodeDecodeError) as e:
        # a half-written or hand-broken config: keep the bad file, start from defaults (else pythonw exits
        # silently on the next start).
        bak = path + ".broken"
        try:
            shutil.copyfile(path, bak)
        except OSError:
            pass
        log("Config %s is not valid JSON (%s: %s); backed up to %s and using defaults."
            % (path, type(e).__name__, e, bak))
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        normalize_actions(cfg)
        normalize_rotation(cfg)
        write_json(path, cfg)
        return cfg
    changed = False
    version = cfg.get("version")
    if version != CONFIG_VERSION:
        shutil.copyfile(path, path + ".bak")
        if isinstance(version, int) and not isinstance(version, bool) and version >= 21:
            # rf.py 4.8 and later (also a newer config): upgraded in place, the settings stay; missing ones come
            # from the defaults below (merge_defaults)
            drop_obsolete(cfg)
            for key, value in DEFAULT_CONFIG.items():   # the notes of this version
                if key.startswith("_"):
                    cfg[key] = value
                elif isinstance(value, dict) and isinstance(cfg.get(key), dict):
                    cfg[key].update({k: v for k, v in value.items() if k.startswith("_")})
            if version == 21:                        # rf.py 4.8-4.15
                t = cfg.get("timing", {})
                if (t.get("attack_interval_min"), t.get("attack_interval_max")) in ((0.3, 0.7), (0.15, 0.35)):
                    t["attack_interval_min"], t["attack_interval_max"] = 0.1, 0.25   # the attack key 3x as often
                if cfg.get("targeting", {}).get("sort") == "avatar":
                    cfg["targeting"]["sort"] = "mixed"   # near you first, then near the anchor (yellow marker)
                if cfg.get("animus", {}).get("summon_check_seconds") == 3.0:
                    cfg["animus"]["summon_check_seconds"] = 6.0   # a summon may take a few seconds (cast, server)
                log("Config of rf.py 4.x updated (backup: %s.bak): the settings of the mouse / keyboard modes are "
                    "gone, everything goes through the game; targeting.sort = mixed (monsters close to you first, "
                    "then the ones nearest to the anchor)." % path)
            if version < 25 and str(cfg.get("hotkeys", {}).get("quit", "")).strip().lower() == "end":
                cfg["hotkeys"]["quit"] = "ctrl+end"  # End alone quit the bot from any window (typing in an editor)
                log("Quit hotkey changed from End to Ctrl+End (End alone also quit the bot while you typed in "
                    "another program); set hotkeys.quit in the config to change it.")
            if version > CONFIG_VERSION:
                log("Config %s is version %d, newer than this bot (%d): used as it is, unknown settings are kept "
                    "(backup: %s.bak)." % (path, version, CONFIG_VERSION, path))
            else:
                log("Config %s updated from version %d to %d (backup: %s.bak), your settings are kept."
                    % (path, version, CONFIG_VERSION, path))
            cfg["version"] = CONFIG_VERSION
        else:                                        # older: the defaults of this version
            old = cfg
            cfg = copy.deepcopy(DEFAULT_CONFIG)
            for section in KEEP_ON_UPGRADE:
                if isinstance(old.get(section), dict):
                    for name, value in old[section].items():
                        if name in cfg[section]:
                            cfg[section][name] = value
            if isinstance(old.get("actions"), list):
                cfg["actions"] = old["actions"]
            log("Old config version, backed up to %s.bak and replaced with v%s defaults "
                "(keys, hotkeys and actions kept)." % (path, VERSION))
        changed = True
    changed = normalize_actions(cfg) or changed
    changed = normalize_rotation(cfg) or changed
    changed = merge_defaults(cfg, DEFAULT_CONFIG) or changed
    if changed:
        write_json(CFG_PATH, cfg)
    return cfg

# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------


class Bot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.t = cfg["timing"]
        self.tc = cfg["targeting"]
        self.ac = cfg["anchor"]
        self.cc = cfg["combat"]
        self.anc = cfg["animus"]
        self.loot = cfg["loot"]
        self.rot = cfg["rotation"]
        self.last_loot = 0.0
        self.last_loot_walk = 0.0
        self.loot_state = {}           # {ground index: {"tries", "last", "walked"}} of drops being picked up
        self.loot_skips = {}           # {ground index: ignore until} of drops that stayed on the ground
        self.last_kill = None          # time a target died (its drop may come a moment later)
        self.loot_hold_since = None    # loot.first holds the next target since then
        self.loot_refused = 0          # pickups in a row the module refused (LOOT_REFUSED)
        self.loot_walk = None          # walk to a drop: {"index", "best", "stuck", "since"}
        self.mem = SharedMemory(cfg["shared"]["name"], cfg["shared"]["stale_seconds"])
        self.dll_log = ModuleLog()
        self.dll_log_polled = 0.0
        self.keys = {name: vk_from_name(value) for name, value in cfg["keys"].items()}
        self.hk_names = dict(cfg["hotkeys"])
        self.hotkeys = Hotkeys({name: hotkey_from_name(value) for name, value in self.hk_names.items()})

        self.hwnd = None               # game window: key messages go to it
        self.hwnd_pid = None
        self.running = False
        self.quit = False
        self.pending_anchor = False
        self.pending_debug = False
        self.pending_record = False
        self.cast_since = None         # your character casts since then (casting())
        self.cast_value = None
        self.pending_start = False
        self.hotkey_stop = threading.Event()
        self.hotkey_thread = None

        self.anchor = None             # (x, y, z) world position
        self.anchor_marker = False     # the anchor is a ground marker (it follows the markers)
        self.homing = None             # walk back to the anchor in progress (home_step), None = not walking
        self.prev_markers = None       # marker positions of the last tick, to spot new / removed markers
        self.nav_blocked_until = 0.0
        self.skips = {}                # {entity key: ignore until}
        self.last_clear = 0.0
        self.last_select = 0.0
        self.animus_ids = set()        # indexes of your own animus (for the target priority)
        self.last_switch = 0.0
        self.last_attack = 0.0
        self.attack_gap = 0.0
        self.last_summon = 0.0
        self.action_last = {}          # {(action name, key, belt page): time of the last press}
        self.bad_keys = set()          # action keys already reported as unknown
        self.not_renewed = {}          # {action name: effect names (lower case) it does not extend (game rule)}
        self.renew_misses = {}         # {(action name, effect lower case): presses in a row that did not extend it}
        self.animus_absent_since = None
        self.summon_pending = None     # (animus name, time) of a summon request until an animus is out
        self.out_entry = None          # animus entry that is out, to tell a death from a recall
        self.out_hp = 1.0              # HP rate of the animus out at the last tick (0 = its die action runs)
        self.dead_entries = set()      # animus that died and have not got their HP back since
        self.revive = None             # heal / reset in progress: {"entry", "name", "before", "since", "stage", "why"}
        self.last_skill_press = 0.0    # last press of anything that may cast (attack macro, action, skill): the
                                       # game's 1 s global delay follows it
        self.action_verify = None      # the last skill action: did the game use it? {"a", "page", "key", ...}
        self.renew_checks = []         # [(action, effects before, time)]: did a renew action extend its effects?
        self.last_reset_press = 0.0
        self.heal_retry_after = 0.0    # no heal attempt before then (the game did not take it several times)
        self.idle_since = None         # no target since then (anchor.idle_return_seconds)
        self.was_dead = False          # the character was dead at the last tick
        self.last_idle_walk = 0.0
        self.hold_attack_until = 0.0   # no attack key until then: a skill waits for the game's global delay
        self.combat_key = None
        self.combat_hp = None
        self.combat_start_hp = None    # target HP when it was selected: no damage since = dropped by the game?
        self.target_drops = {}         # {entity key: [times the game dropped it as the target without damage]}
        self.my_monsters = {}          # {entity key: last time it was your target}: yours, not someone else's
        self.combat_hp_changed = 0.0
        self.dead_since = None
        self.far_since = None
        self.switch_far_since = None   # the target is farther than combat.switch_distance since then

    # ---- helpers ---------------------------------------------------------

    def hk_label(self, name):
        return self.hk_names[name].upper()

    @staticmethod
    def log_limited(key, msg, every=5.0):
        """The module-level log_limited (with the count of dropped repeats), bot keys in their own namespace."""
        log_limited("bot:" + key, msg, every)

    def wait_running(self, seconds):
        """Sleep, but wake up early as soon as the bot is paused or asked to quit."""
        end = time.time() + max(0.0, seconds)
        while time.time() < end:
            if self.quit or not self.running:
                return False
            time.sleep(min(0.05, max(0.0, end - time.time())))
        return self.running and not self.quit

    def snapshot(self):
        return self.mem.read()

    def update_window(self, snap):
        """Find the game window from the process id in the snapshot (key messages go to it)."""
        if self.hwnd and self.hwnd_pid == snap.pid and user32.IsWindow(self.hwnd):
            return
        hwnd = find_process_window(snap.pid)
        if not hwnd:
            self.log_limited("nowin", "Game window of process %d not found." % snap.pid, 60.0)
            return
        self.hwnd, self.hwnd_pid = hwnd, snap.pid
        log("Game window 0x%X '%s' (pid %d)." % (hwnd, get_window_title(hwnd), snap.pid))

    def dll_can(self, flag, what):
        """A command the module supports in this client (status block); logged now and then when it does not."""
        if self.mem.dll_flag(flag):
            return True
        self.log_limited("no:" + flag, "%s: the module does not support it in this client (its code differs, see the "
                                       "'bot export' lines in BotCore.log)." % what, 300.0)
        return False

    def press_vk(self, vk, presses=1, delay=0.0):
        """Press a game key `presses` times through the game (belt keys use their slot, others go to the window)."""
        for i in range(max(1, int(presses))):
            if self.quit or not self.running:
                return
            if i and not self.wait_running(delay):
                return
            result = self.mem.command(BOT_CMD_KEY, index=vk, hwnd=self.hwnd)
            if result != BOT_CMDR_OK:
                self.log_limited("keyfail", "Key 0x%02X through the game failed: %s." % (
                    vk, BOT_CMDR_NAMES.get(result, result) if result is not None
                    else "the game did not answer within %.1f s (busy or loading?)" % CMD_TIMEOUT), 15.0)

    def belt_page_ok(self, a):
        """An action with a belt page can be pressed: a belt key and a belt with that page (logged once)."""
        problem = None
        if belt_slot(a["key"]) is None:
            problem = "belt page %d needs a belt key 1-0, not %r" % (a["page"], a["key"])
        elif self.mem.belt_pages() < a["page"]:
            problem = ("the module cannot use belt pages in this client" if not self.mem.belt_pages()
                       else "the belt has %d pages only" % self.mem.belt_pages())
        if problem is None:
            return True
        if (a["name"], problem) not in self.bad_keys:
            self.bad_keys.add((a["name"], problem))
            log("Action '%s': %s, skipped." % (a["name"], problem))
        return False

    def press_slot(self, page, slot, presses=1, delay=0.0):
        """Use belt slot 0..9 of belt page 0..4 through the game `presses` times (no key)."""
        for i in range(max(1, int(presses))):
            if self.quit or not self.running:
                return
            if i and not self.wait_running(delay):
                return
            result = self.mem.command(BOT_CMD_SLOT, obj_type=page, index=slot)
            if result != BOT_CMDR_OK:
                self.log_limited("slotfail", "Belt page %d slot %d through the game failed: %s." % (
                    page + 1, slot + 1, BOT_CMDR_NAMES.get(result, result) if result is not None
                    else "the game did not answer within %.1f s (busy or loading?)" % CMD_TIMEOUT), 15.0)

    def press(self, name):
        self.press_vk(self.keys[name])

    def eject_module(self, force_free=False):
        """Remove the hooks and free the module memory (the game becomes clean of our code). Safe while the bot
        runs: the module unhooks on the game thread, then we wait for the two hooked vtable slots to point back
        into the game and give it a few frames to unwind before unmapping (same sequence as tools/do_eject.py).

        force_free=True: also proceed when the module does not answer (it was already ejected before, so its
        hooks are gone and it no longer receives commands). The slots-clean check still gates the free."""
        result = self.mem.command(BOT_CMD_EJECT)
        log("Module eject (hooks off): %s." % (BOT_CMDR_NAMES.get(result, result) if result is not None
            else "no answer"))
        if result != BOT_CMDR_OK and not force_free:
            return False
        # the base file of the DLL that was really mapped (find_and_map maps newest_dll: maybe Bagnon.new.dll)
        fpid, base = _mm.read_base_file(_mm.newest_dll(profile_dll(ACTIVE_PROFILE))) if _mm else (None, None)
        if self.mem.status_field("magic") is not None and self.mem.status_field("ejectWanted") != 1:
            log("Eject: the module did not confirm that every hook is back (another mod chained after it, or it "
                "did not get the command): it stays mapped, idle where its hooks are off.")
            return result == BOT_CMDR_OK
        game_pid = fpid or (self.hwnd_pid or 0)
        if _mm is None:
            log("manualmap not available (%s): hooks are off, memory not freed." % _mm_error)
            return True
        if not base:
            log("No mapped base recorded: hooks are off, memory not freed.")
            return True
        return self._free_module_memory(game_pid, base)

    def _free_module_memory(self, game_pid, base):
        """Wait for both hooked vtable slots to point back into the game, then unmap the module at `base`.
        Fail-closed: a failed slot read or a still-hooked slot keeps the module (a dangling hook would crash)."""
        try:
            _mm.enable_debug_privilege()
        except Exception as e:
            log("enable_debug_privilege failed: %s" % e)
        # no read = a failed slot check: treat as "not clean" and keep the module (fail-closed).
        h = kernel32.OpenProcess(0x1F0FFF, False, game_pid) or kernel32.OpenProcess(0x410, False, game_pid)
        if not h:
            log("Eject: OpenProcess(pid %d) failed (error %d); idle module stays mapped (not freed)."
                % (game_pid, ctypes.get_last_error()))
            return True
        try:
            def slot(addr):
                v = ctypes.c_uint32()
                n = ctypes.c_size_t()
                if not kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), ctypes.byref(v), 4,
                                                  ctypes.byref(n)) or n.value != 4:
                    raise OSError("ReadProcessMemory(0x%08X) failed (error %d)" % (addr, ctypes.get_last_error()))
                return v.value

            def slots_clean():
                for s in MODULE_HOOK_SLOTS:              # CAvatar::RenderOverhead, Combat::AnalysisServerPacket
                    if base <= slot(s) < base + 0x200000:  # still our code mapped here
                        return False
                return True

            clean = False
            last_err = None
            for _ in range(200):
                try:
                    last_err = None
                    if slots_clean():
                        clean = True
                        break
                except OSError as e:
                    last_err = e
                time.sleep(0.02)
            if last_err is not None:
                # a read failed on the last attempt: do not assume "clean" (the game may still call freed pages)
                log("Eject: %s - not assuming clean, idle module stays mapped (not freed)." % last_err)
                return True
            time.sleep(0.4)                              # let the game thread leave our pages entirely
            if not clean:
                # A vtable slot still points into the module: freeing would leave a dangling hook (crash).
                log("Eject: vtable slots still point into the module; idle module stays mapped (not freed).")
                return True
            try:
                _mm.free_mapped(game_pid, base)
                log("Module memory freed (base 0x%08X)." % base)
            except Exception as e:
                log("Freeing the module failed: %s (hooks are off)." % e)
                return False
            return True
        finally:
            kernel32.CloseHandle(h)

    def skip(self, key, seconds):
        self.skips[key] = time.time() + float(seconds)

    def is_skipped(self, key, now):
        until = self.skips.get(key)
        if until is None:
            return False
        if until <= now:
            del self.skips[key]
            return False
        return True

    def clear_target(self, reason):
        now = time.time()
        if now - self.last_clear < self.t["clear_guard"]:
            return
        log(reason)
        result = self.mem.command(BOT_CMD_CLEAR)   # CTargetMgr::CheckTarget(NULL), what the game's Esc does
        if result != BOT_CMDR_OK:
            self.log_limited("clearfail", "Clearing the target through the game failed: %s." % (
                BOT_CMDR_NAMES.get(result, result) if result is not None else "no answer (timeout)"), 15.0)
        self.last_clear = time.time()
        self.reset_combat()

    # ---- controls --------------------------------------------------------

    def start_hotkeys(self):
        if self.hotkey_thread and self.hotkey_thread.is_alive():
            return
        self.hotkey_stop.clear()
        self.hotkey_thread = threading.Thread(target=self._hotkey_loop, name="rf-hotkeys", daemon=True)
        self.hotkey_thread.start()

    def stop_hotkeys(self):
        self.hotkey_stop.set()
        if self.hotkey_thread:
            self.hotkey_thread.join(timeout=0.5)
            self.hotkey_thread = None

    def _hotkey_loop(self):
        while not self.hotkey_stop.is_set():
            if self.hotkeys.pressed("toggle"):
                self.running = not self.running
                if self.running:
                    self.pending_start = True
                log("Bot %s." % ("STARTED" if self.running else "PAUSED"))
            if self.hotkeys.pressed("quit"):
                self.quit = True
                self.running = False
                log("Quit requested.")
                return
            if self.hotkeys.pressed("anchor"):
                self.pending_anchor = True
            if self.hotkeys.pressed("debug"):
                self.pending_debug = True
            if "record" in self.hotkeys.keys and self.hotkeys.pressed("record"):
                self.pending_record = True
            time.sleep(0.02)

    def poll_controls(self):
        """Handle pending hotkey actions. Toggle/quit are handled by the hotkey thread."""
        if self.quit:
            return False
        if self.pending_anchor:
            self.pending_anchor = False
            self.set_anchor()
        if self.pending_debug:
            self.pending_debug = False
            self.dump_debug()
        if self.pending_record:
            self.pending_record = False
            self.record_actions()
        if self.pending_start:
            self.pending_start = False
            self.on_start()
        return self.running and not self.quit

    def set_anchor_here(self):
        """Set the anchor to your current position (ignore ground markers). Always works via the GUI."""
        snap = self.snapshot()
        if snap is None:
            log("Anchor: no game state (%s)." % self.mem.status)
            return
        av = snap.avatar
        self.anchor = (av.x, av.y, av.z)
        self.anchor_marker = False
        self.prev_markers = [m["pos"] for m in snap.markers]
        self.nav_blocked_until = 0.0
        log("Anchor = your current position (%.0f, %.0f, %.0f)." % self.anchor)

    def set_anchor(self):
        snap = self.snapshot()
        if snap is None:
            log("Anchor: no game state (%s)." % self.mem.status)
            return
        av = snap.avatar
        best, best_d = None, None
        for i, m in enumerate(snap.markers):
            d = dist_xz(m["pos"][0], m["pos"][2], av.x, av.z)
            if d <= self.ac["marker_pick_radius"] and (best_d is None or d < best_d):
                best, best_d = i, d
        if best is not None:
            self.anchor = tuple(snap.markers[best]["pos"])
            self.anchor_marker = True
            log("Anchor = ground marker #%d at (%.0f, %.0f, %.0f), %.0f from you."
                % ((best + 1,) + self.anchor + (best_d,)))
        else:
            self.anchor = (av.x, av.y, av.z)
            self.anchor_marker = False
            log("Anchor = your current position (%.0f, %.0f, %.0f) (no ground marker within %.0f; "
                "Ctrl+Shift+M drops one)." % (av.x, av.y, av.z, self.ac["marker_pick_radius"]))
        self.prev_markers = [m["pos"] for m in snap.markers]
        self.nav_blocked_until = 0.0

    def follow_markers(self, snap):
        """A newly placed ground marker becomes the anchor; a removed anchor marker hands over to the last one."""
        markers = [m["pos"] for m in snap.markers]
        prev, self.prev_markers = self.prev_markers, markers
        if prev is None:
            return

        def known(p, among):
            return any(math.hypot(p[0] - q[0], p[2] - q[2]) < 1.0 for q in among)

        added = [p for p in markers if not known(p, prev)]
        if added:
            self.anchor = tuple(added[-1])
            self.anchor_marker = True
            self.nav_blocked_until = 0.0
            log("New ground marker at (%.0f, %.0f, %.0f): it is the anchor now, %.0f from you."
                % (self.anchor + (self.anchor_dist(snap),)))
            return
        if self.anchor is not None and self.anchor_marker and not known(self.anchor, markers):
            if markers:
                self.anchor = tuple(markers[-1])
                self.nav_blocked_until = 0.0
                log("Anchor marker removed: the anchor is ground marker #%d now (%.0f from you)."
                    % (len(markers), self.anchor_dist(snap)))
            else:
                self.anchor_marker = False
                log("Anchor marker removed: its position stays the anchor (Ctrl+Shift+M drops a new marker).")

    def on_start(self):
        """First tick after F11: make sure there is an anchor and print what the bot sees."""
        self.homing = None
        problem = self.action_export_problem()
        log("Your character's action from the module: %s." % (
            "0x%08X" % self.action_now()[0] if problem is None else "NOT available - %s" % problem))
        if self.anchor is None and self.ac["enabled"]:
            self.set_anchor()
        snap = self.snapshot()
        if snap is None:
            log("Waiting for the game: %s" % self.mem.status)
            return
        missing = [what for flag, what in (("commands", "selecting monsters"), ("moves", "walking"),
                                           ("animusList", "the animus window"), ("loot", "picking up loot"))
                   if not self.mem.dll_flag(flag)]
        if not self.mem.supports_keys():
            missing.append("key presses")
        if not self.mem.belt_pages():
            missing.append("belt pages")
        if missing:
            log("The module does not support %s in this client (its code differs, see the 'bot export' lines in "
                "BotCore.log)." % ", ".join(missing))
        elif not self.mem.dll_flag("keysInactive"):
            log("Keys that are no belt keys reach the game only while its window is active ([Bot] "
                "KeysWhileInactive=1 in BotCore.ini).")
        av = snap.avatar
        cx, cz = (self.anchor[0], self.anchor[2]) if self.anchor else (av.x, av.z)
        mobs = [e for e in snap.entities if e.type == OBJ_MONSTER and e.alive]
        near = [e for e in mobs if e.dist(cx, cz) <= self.tc["search_radius"]]
        nearest = min((e.dist(av.x, av.z) for e in mobs), default=None)
        log("Character '%s' Lv.%d HP %d%%, %d live monsters around, %d within %.0f of the %s, nearest %s."
            % (av.name, av.level, round(av.hp * 100), len(mobs), len(near), self.tc["search_radius"],
               "anchor" if self.anchor else "character",
               "%.0f" % nearest if nearest is not None else "-"))

    # ---- debug -----------------------------------------------------------

    def dump_debug(self):
        """Save the snapshot as JSON and log a summary."""
        snap = self.snapshot()
        if snap is None:
            log("Debug: no game state (%s)." % self.mem.status)
            return
        os.makedirs(DEBUG_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        av = snap.avatar
        data = snap.to_dict()
        data["bot"] = {"version": VERSION, "anchor": self.anchor, "hwnd": self.hwnd, "animus": sorted(self.animus_ids),
                       "belt": self.mem.belt(), "animus_list": self.mem.animus_list(),
                       "ground": self.mem.ground(), "ground_info": self.mem.ground_info()}
        path = os.path.join(DEBUG_DIR, "snapshot_%s.json" % stamp)
        write_json(path, data)

        counts = {}
        for e in snap.entities:
            counts[e.type_name] = counts.get(e.type_name, 0) + 1
        log("Debug saved: %s | snapshot #%d, %d ms old | objects: %s (total %d)"
            % (path, snap.counter, snap.age_ms, ", ".join("%s %d" % kv for kv in sorted(counts.items())) or "none",
               snap.entity_total))
        log("  You: '%s' Lv.%d HP %d%% at (%.0f, %.0f, %.0f), index %d serial %d"
            % (av.name, av.level, round(av.hp * 100), av.x, av.y, av.z, av.index, av.serial))
        if self.anchor:
            log("  Anchor at (%.0f, %.0f, %.0f), %.0f from you (leash %.0f)."
                % (self.anchor + (dist_xz(self.anchor[0], self.anchor[2], av.x, av.z), self.ac["leash"])))
        log("  Target: %s" % ("%s HP %d%% dist %.0f" % (snap.target.label(), round(snap.target.hp * 100),
                                                         snap.target.dist(av.x, av.z)) if snap.target else "none"))
        mobs = sorted((e for e in snap.entities if e.type == OBJ_MONSTER), key=lambda e: e.dist(av.x, av.z))
        for e in mobs[:8]:
            attack = ""
            if e.victim_age_ms != 0xFFFFFFFF:
                attack = " attacked %s #%d %.1f s ago" % (OBJ_NAMES.get(e.victim_type, e.victim_type), e.victim_index,
                                                          e.victim_age_ms / 1000.0)
            log("  %s HP %d%% dist %.0f flags 0x%04X%s%s"
                % (e.label(), round(e.hp * 100), e.dist(av.x, av.z), e.flags, " [target]" if e.is_target else "",
                   attack))
        for e in snap.entities:
            if e.type == OBJ_ANIMUS:
                log("  %s HP %d%% dist %.0f%s" % (e.label(), round(e.hp * 100), e.dist(av.x, av.z),
                                                  " (yours)" if e.index in self.animus_ids else ""))
        for i, m in enumerate(snap.markers):
            log("  Marker #%d at (%.0f, %.0f, %.0f), %.0f from you"
                % (i + 1, m["pos"][0], m["pos"][1], m["pos"][2], dist_xz(m["pos"][0], m["pos"][2], av.x, av.z)))
        self.log_effects("  Effects", snap)
        act = self.action_now()
        log("  Your action: %s." % ("0x%08X (kind %d), %d changes so far" % (act[0], act[0] >> 28, act[1])
                                    if act is not None else "not exported by this module build"))
        self.log_ground(snap)

    def log_ground(self, snap):
        """Debug: every drop the module lists, its owner, distance and whether the bot would pick it up."""
        av = snap.avatar
        info = self.mem.ground_info()
        ground = self.mem.ground()
        if info is None or ground is None:
            log("  Ground: no list from the module.")
            return
        seq, count, state = info
        log("  Ground: %d drop(s) listed (module: count %d, state %d, written %d times, loot command %s)%s; loot "
            "%s, radius %.0f, walk radius %.0f, only our loot %s; you: index %d = 0x%X, serial %d = 0x%X."
            % (len(ground), count, state, seq // 2, "on" if self.mem.dll_flag("loot") else "OFF",
               " - the module never wrote it (old Bagnon.dll?)" if seq == 0 else "",
               "on" if self.loot.get("enabled") else "OFF", float(self.loot.get("radius", 0.0)),
               float(self.loot.get("walk_radius", 0.0)), "on" if self.loot.get("only_mine", True) else "off",
               av.index, av.index, av.serial, av.serial))
        now = time.time()
        for it in sorted(ground, key=lambda g: dist_xz(g["pos"][0], g["pos"][2], av.x, av.z))[:15]:
            d = dist_xz(it["pos"][0], it["pos"][2], av.x, av.z)
            reason = self.loot_reason(it, av, now)
            if reason is None:
                reason = ("in pickup range" if d <= float(self.loot.get("pickup_range", 25.0)) else
                          "walks to it, then picks it up" if d <= max(float(self.loot.get("radius", 0.0)),
                                                                      float(self.loot.get("walk_radius", 0.0))
                                                                      if self.loot.get("walk") else 0.0)
                          else "too far (outside the loot radii)")
            log("  Drop '%s' #%d owner 0x%08X at (%.0f, %.0f, %.0f), %.0f from you: %s."
                % (it["name"], it["index"], it.get("owner", 0), it["pos"][0], it["pos"][1], it["pos"][2], d, reason))

    # ---- your character's action (casting?) -----------------------------

    def action_now(self):
        """(action value, changes counted by the module); None when the module does not export it (older build)."""
        action = self.mem.status_field("avatarAction")
        changes = self.mem.status_field("actionChanges")
        if action is None or changes is None or changes == 0:
            return None                    # no status, or a module without the fields (they read as zeros; a
                                           # module that has them counts the first value as a change)
        return action, changes

    def casting(self):
        """
        True while your character casts a skill / force (its action kind ACTION_KIND_CAST, from the module) and
        combat.wait_while_casting is on. False without the module export. A cast longer than CAST_STUCK s no
        longer counts (logged once): the bot does not stand still forever on a value it misreads.
        """
        if not self.cc.get("wait_while_casting", True):
            return False
        act = self.action_now()
        now = time.time()
        if act is None or (act[0] >> 28) != ACTION_KIND_CAST:
            self.cast_since = None
            return False
        if self.cast_since is None or act[0] != self.cast_value:
            self.cast_since, self.cast_value = now, act[0]
        if now - self.cast_since > CAST_STUCK:
            self.log_limited("caststuck", "Your character's action 0x%08X (casting) for more than %.0f s: the bot no "
                                          "longer waits for it. Send this line." % (act[0], CAST_STUCK), 300.0)
            return False
        return True

    def action_export_problem(self):
        """Why the module gives no action of your character (None when it does): for the log."""
        if self.mem.status_field("magic") is None:
            return "no module status (%s)" % self.mem.status
        if self.action_now() is not None:
            return None
        return ("the mapped Bagnon.dll is an older build without it (status: avatarAction 0x%X, changes %d, module "
                "pid %s). Copy the new Bagnon.dll to build\\, press Remap (not Inject), then try again; BotCore.log "
                "must show the module loaded after the copy." % (self.mem.status_field("avatarAction") or 0,
                                                                 self.mem.status_field("actionChanges") or 0,
                                                                 self.mem.status_field("pid") or "?"))

    def record_actions(self, seconds=15.0):
        """
        Log every change of your character's action for `seconds` (sampled every 5 ms in its own thread): which
        values come while you cast, buff, walk, attack. The module counts every change, so the log also tells
        how many were too short to be sampled.
        """
        log("Actions: recording requested.")
        if getattr(self, "_recording", False):
            log("Actions: already recording.")
            return
        problem = self.action_export_problem()
        if problem:
            log("Actions: cannot record: %s" % problem)
            return
        first = self.action_now()
        self._recording = True

        def run():
            try:
                log("Actions: recording for %.0f s. Now cast skills and buffs (also a press that only lights the "
                    "cursor), walk and attack; the bot can keep running." % seconds)
                start = time.time()
                last, changes0 = first
                since = start
                seen = 0
                rows = []
                while time.time() - start < seconds and not self.quit:
                    cur = self.action_now()
                    if cur is not None and cur[0] != last:
                        now = time.time()
                        rows.append((since - start, now - since, last))
                        last, since = cur[0], now
                        seen += 1
                    time.sleep(0.005)
                end = time.time()
                rows.append((since - start, end - since, last))
                cur = self.action_now()
                total = (cur[1] - changes0) & 0xFFFFFFFF if cur is not None else seen
                log("Actions: %d changes in %.0f s (the module counted %d%s):"
                    % (seen, end - start, total, "" if total <= seen else ", %d too short to sample" % (total - seen)))
                for at, dur, value in rows[:120]:
                    log("  +%5.2f s  action 0x%08X (kind %d, low 0x%07X) for %.2f s"
                        % (at, value, value >> 28, value & 0x0FFFFFFF, dur))
                if len(rows) > 120:
                    log("  ... %d more changes not listed." % (len(rows) - 120))
                kinds = {}
                for _, dur, value in rows:
                    kinds[value] = kinds.get(value, 0.0) + dur
                log("Actions: time per value: %s." % ", ".join("0x%08X %.1f s" % kv for kv in
                                                              sorted(kinds.items(), key=lambda kv: -kv[1])[:12]))
            except Exception as e:
                log("Actions: recording failed (%s: %s):\n%s" % (type(e).__name__, e, traceback.format_exc()))
            finally:
                self._recording = False

        threading.Thread(target=run, name="rf-actions", daemon=True).start()

    # ---- effects (buffs / potion) ----------------------------------------

    @staticmethod
    def effects_now(snap):
        """{name: seconds left now} of effects that are still running (item and effect names)."""
        age = snap.age_ms / 1000.0
        effects = {}
        for e in snap.effects:
            remain = 1e9 if e["remain_ms"] < 0 else e["remain_ms"] / 1000.0 - age
            for name in (e["name"], e["effect"]):
                if name:
                    effects[name] = max(effects.get(name, -1.0), remain)
        return {n: r for n, r in effects.items() if r > 0}

    def log_effects(self, title, snap):
        effects = self.effects_now(snap)
        log("%s: %s | actions: %s"
            % (title, ", ".join("%s %.0fs" % (n, min(r, 99999)) for n, r in sorted(effects.items())) or "none",
               ", ".join("%s (%s)" % (a["name"], action_key_label(a)) for a in self.cfg["actions"] if a["enabled"])
               or "none"))

    # ---- actions (buffs, potions, heals: cfg["actions"], edited in the window) -------

    @staticmethod
    def effect_left(effects, name):
        """Seconds left of an effect by its name (or its item name), case-insensitive; -1 = not on you."""
        name = name.strip().lower()
        return max([r for n, r in effects.items() if n.lower() == name] or [-1.0])

    def own_animus_hp(self, snap):
        """HP rate (0..1) of your summoned animus, None when none is out."""
        own = [e for e in self.own_animus(snap) if e.alive and e.hp > 0]
        if own:
            return max(e.hp for e in own)
        for it in self.mem.animus_list() or []:
            if it["summoned"] and it["max_hp"]:
                return it["rate"]
        return None

    def action_reason(self, a, snap, effects):
        """Why the action is due now ('Tempo missing', 'HP 35%'...), or None."""
        when = a["when"]
        if when in ("missing", "ending", "missing_or_ending"):
            left = [(n, self.effect_left(effects, n)) for n in a["effects"]]
            missing = [n for n, r in left if r <= 0]
            skip = self.not_renewed.get(a["name"], ())
            ending = ["%s %.0fs" % (n, r) for n, r in left if 0 < r < a["seconds"] and n.lower() not in skip]
            if missing and when in ("missing", "missing_or_ending"):
                return "%s missing" % ", ".join(missing)
            if ending and when in ("ending", "missing_or_ending"):
                return "%s ending" % ", ".join(ending)
            return None
        if when == "hp_below":
            hp = snap.avatar.hp * 100.0
            return "HP %d%%" % round(hp) if hp < a["percent"] else None
        if when == "animus_hp_below":
            rate = self.own_animus_hp(snap)
            return "animus HP %d%%" % round(rate * 100) if rate is not None and rate * 100.0 < a["percent"] else None
        return None

    def action_belt_slot(self, a):
        """(page, key, belt slot or None) of an action on the belt; (None, None, None) when unknown."""
        slot = belt_slot(a["key"])
        page = a["page"] or self.mem.belt_page()
        belt = self.mem.belt() if slot is not None and page else None
        if belt is None:
            return None, None, None
        key = BELT_KEYS[slot]
        return page, key, next((x for x in belt if x["page"] == page and x["key"] == key), None)

    def action_slot_ready(self, a):
        """
        Belt export: False when the action's belt slot is empty (logged: potions used up?) or holds a skill /
        force the game would not use now (its cooldown, or the global delay of the last skill: the attack key
        waits, next tick). True when it can be pressed, or when the belt is not known.
        """
        page, key, s = self.action_belt_slot(a)
        if page is None:
            return True
        if s is None:
            self.log_limited("empty:" + a["name"], "%s: belt page %d key %s is empty (used up?), skipped." % (
                a["name"], page, key), 300.0)
            return False
        if s["kind"] == BELT_SF and (time.time() - self.last_skill_press < GLOBAL_DELAY or self.casting()):
            self.hold_attack_until = max(self.hold_attack_until, time.time() + 1.0)
            return False                   # global delay of the last skill, or a cast runs: a press lights the cursor
        if s["kind"] != BELT_SF or s["ready"] in (1, 2):
            return True
        if s["ready"] == -1 or s["left"] > 0.05:
            self.log_limited("actcd:" + a["name"], "%s: '%s' ready in %.0f s, waiting." % (a["name"], s["name"],
                                                                                         s["left"]), 30.0)
        else:                              # the global delay of the last skill: the attack key waits a moment
            self.hold_attack_until = max(self.hold_attack_until, time.time() + 1.5)
        return False

    def verify_action(self, snap, now):
        """
        Did the game use the last skill action? Its cooldown started or one of its effects came / got longer: yes.
        Not within SKILL_CHECK s (the game was busy: global delay, a cast; or only the cursor lit up): one more
        press (it casts a skill whose cursor is lit), up to ACTION_TRIES tries.
        True = still checking (the attack key waits, no other action meanwhile).
        """
        for rc in [rc for rc in self.renew_checks if now >= rc[2]]:
            self.renew_checks.remove(rc)
            self.check_renew(rc[0], rc[1])
        v = self.action_verify
        if v is None:
            return False
        a = v["a"]
        s = next((x for x in self.mem.belt() or [] if x["page"] == v["page"] and x["key"] == v["key"]), None)
        effects = self.effects_now(snap)
        gained = any(self.effect_left(effects, n) > self.effect_left(v["effects"], n) + 2.0 for n in a["effects"])
        if s is None or s["kind"] != BELT_SF or s["ready"] == -1 or s["left"] > 0.05 or gained:
            if a["when"] in ("ending", "missing_or_ending") and len(a["effects"]) > 1:
                self.renew_checks.append((a, v["effects"], v["since"] + 2.0))   # timers a moment later
            self.action_verify = None
            return False
        if now - v["since"] < SKILL_CHECK or (s["ready"] == 0 and now - v["since"] < 2.5):
            self.hold_attack_until = max(self.hold_attack_until, now + 0.5)
            return True                    # cast / server answer, or the global delay still runs
        if v["tries"] >= ACTION_TRIES:
            log("%s: the game did not use it after %d tries (busy?), next try after its cooldown (%.0f s)."
                % (a["name"], v["tries"], a["cooldown"]))
            self.action_verify = None
            return False
        if s["ready"] != 1:
            return False                   # not usable now: the action's own cooldown decides
        if self.casting():
            self.hold_attack_until = max(self.hold_attack_until, now + 0.5)
            return True                    # a cast runs: the retry press waits for its end
        log("%s: the game did not use it (busy or only the cursor lit up), one more press." % a["name"])
        self.press_slot(v["page"] - 1, BELT_KEYS.index(v["key"]))
        self.action_last[v["slot"]] = self.last_skill_press = time.time()
        v["tries"] += 1
        v["since"] = time.time()
        return True

    def check_renew(self, a, before):
        """
        After an action that renews several effects (a buff that extends buffs): an effect it did not extend
        twice in a row, while it extended others, is one it does not renew (a game rule). It is no longer
        checked by that action, so the action is not pressed again and again for it. Logged once.
        """
        snap = self.snapshot()
        if snap is None:
            return
        after = self.effects_now(snap)
        old = {n: self.effect_left(before, n) for n in a["effects"]}
        new = {n: self.effect_left(after, n) for n in a["effects"]}
        timed = [n for n in a["effects"] if 0 < old[n] < 1e8 and 0 < new[n] < 1e8]   # 1e9 = no timer
        extended = [n for n in timed if new[n] > old[n] + 2.0]
        if not extended:
            return                         # nothing extended (cooldown, interrupted): no conclusion
        for n in timed:
            key = (a["name"], n.lower())
            if n in extended:
                self.renew_misses.pop(key, None)
                continue
            self.renew_misses[key] = self.renew_misses.get(key, 0) + 1
            if self.renew_misses[key] == 2:
                self.not_renewed.setdefault(a["name"], set()).add(n.lower())
                log("%s does not extend %s (twice, while it extended %s): the bot no longer presses it for %s. "
                    "Remove %s from its effects (Actions tab) and keep it up with its own action ('effect missing "
                    "or ending')." % (a["name"], n, ", ".join(extended), n, n))

    def run_actions(self, snap, now, combats, first_only):
        """Press the actions due now whose combat setting is in `combats`. True if one was pressed."""
        effects = self.effects_now(snap)
        pressed = False
        for a in list(self.cfg["actions"]):
            if self.quit or not self.running:
                return pressed
            if not a["enabled"] or a["combat"] not in combats or not a["key"]:
                continue
            slot = (a["name"], a["key"], a["page"])
            if now - self.action_last.get(slot, 0.0) < a["cooldown"]:
                continue
            reason = self.action_reason(a, snap, effects)
            if reason is None:
                continue
            if not self.action_slot_ready(a):
                continue
            page, key, s = self.action_belt_slot(a)
            verify = s is not None and s["kind"] == BELT_SF and s["ready"] == 1   # the game's own check known
            presses = a["presses"]         # 2 for skills that light a cursor first: the second press casts it
            if a["page"]:
                if not self.belt_page_ok(a):
                    continue
                log("%s: %s, belt page %d key %s%s." % (a["name"], reason, a["page"], a["key"].upper(),
                                                         " x%d" % presses if presses > 1 else ""))
                self.press_slot(a["page"] - 1, belt_slot(a["key"]), presses, a["press_delay"])
            else:
                try:
                    vk = vk_from_name(a["key"])
                except ValueError:
                    if a["key"] not in self.bad_keys:
                        self.bad_keys.add(a["key"])
                        log("Action '%s': unknown key %r, skipped." % (a["name"], a["key"]))
                    continue
                log("%s: %s, key %s%s." % (a["name"], reason, a["key"].upper(),
                                            " x%d" % presses if presses > 1 else ""))
                self.press_vk(vk, presses, a["press_delay"])
            self.action_last[slot] = self.last_skill_press = time.time()
            pressed = True
            if verify:                     # the next ticks check it (verify_action), no blind wait
                self.action_verify = {"a": a, "page": page, "key": key, "since": time.time(), "tries": 1,
                                      "effects": dict(effects), "slot": slot}
                if first_only:
                    return True
                continue
            if a["wait"] > 0:
                self.wait_running(a["wait"])
                if a["when"] in ("ending", "missing_or_ending") and len(a["effects"]) > 1:
                    self.check_renew(a, effects)
            if first_only:
                return True
        return pressed

    # ---- animus ----------------------------------------------------------

    def own_animus(self, snap):
        """Your animus: the one the game has summoned for you ([] when none is out)."""
        index = self.mem.animus_index()
        return [e for e in snap.entities if e.type == OBJ_ANIMUS and e.index == index] if index is not None else []

    def animus_allowed(self, name):
        """False for an animus switched off (animus.never, exact name, case-insensitive)."""
        return name.strip().lower() not in [str(n).strip().lower() for n in self.anc["never"]]

    def rank_animus(self, animus):
        """(resting animus in summon order, None) or (None, why none). Empty order: the most HP first."""
        resting = [it for it in animus if not it["summoned"] and it["max_hp"] > 0]
        if not resting:
            if any(not it["summoned"] for it in animus):
                return None, ("the animus window lists %d animus (%s), but the module reads no HP for them (max HP 0: "
                              "not owned by this character, or the module reads the wrong place)"
                              % (len(animus), ", ".join(it["name"] for it in animus[:4])))
            return None, "no animus found in the animus window"
        resting = [it for it in resting if self.animus_allowed(it["name"])]
        if not resting:
            return None, "every resting animus is switched off (window, Animus tab)"
        order = [str(n).lower() for n in self.anc["order"] if str(n).strip()]
        if not order:
            return sorted(resting, key=lambda it: it["rate"], reverse=True), None
        ranked = []
        for n in order:
            ranked += [it for it in resting if n in it["name"].lower() and it not in ranked]
        return ranked, None

    def pick_animus(self, animus):
        """(animus to summon, None) or (None, why none): the first of animus.order with enough HP."""
        need = float(self.anc["summon_min_hp"])
        ranked, why = self.rank_animus(animus)
        if ranked is None:
            return None, why
        for it in ranked:
            if it["rate"] >= need:
                return it, None
        return None, "%s (needs %d%% HP)" % (", ".join("%s %d%%" % (it["name"], round(it["rate"] * 100))
                                                       for it in ranked) or "none of animus.order found",
                                            round(need * 100))

    def report_animus_attacks(self, snap):
        """Log (once a minute) monsters that attack an animus the bot does not count as yours."""
        window = self.tc["priority_window"] * 1000.0
        for e in snap.entities:
            if (e.type == OBJ_MONSTER and e.alive and e.victim_type == OBJ_ANIMUS and e.victim_age_ms <= window
                    and e.victim_index not in self.animus_ids):
                self.log_limited("foreign_animus", "%s attacks animus #%d, which the bot does not count as yours "
                                                   "(yours: %s)." % (e.label(), e.victim_index,
                                                                     sorted(self.animus_ids) or "none"), 60.0)
                return

    # ---- skills on the belt (the game's own cooldowns) ------------

    def belt_skill(self, name):
        """The belt slot of a skill / force by its name (case-insensitive, any page), None when not there."""
        name = str(name or "").strip().lower()
        if not name:
            return None
        for s in self.mem.belt() or []:
            if s["kind"] == BELT_SF and s["name"].strip().lower() == name:
                return s
        return None

    def skill_state(self, role, name, why):
        """
        ('ready', slot) when the game lets you use the skill now, ('busy', slot) during a global / shared delay
        (try again in a moment), ('soon', slot) when its own cooldown ends within SKILL_WAIT seconds,
        ('cooldown', slot) while a longer cooldown runs, ('missing', None). Logged.
        """
        if self.mem.belt() is None:
            self.log_limited("nobelt", "%s skill '%s': the module cannot read the belt in this client." % (role, name),
                             300)
            return "missing", None
        s = self.belt_skill(name)
        if s is None:
            self.log_limited("nobelt:" + name, "%s skill '%s' is not on your belt (any page): put it there, or "
                                               "check the name (Belt tab)." % (role, name), 120)
            return "missing", None
        if time.time() - self.last_skill_press < GLOBAL_DELAY or self.casting():
            return "busy", s               # global delay of our last skill, or a cast runs: a press lights the cursor
        if s["ready"] in (1, 2):           # 2 = the DLL could not read cooldowns: try it
            return "ready", s
        if s["ready"] == -1 or s["left"] > 0.05:
            if s["left"] <= SKILL_WAIT:
                return "soon", s           # waited for, not logged
            self.log_limited("cd:" + name, "%s skill '%s' ready in %.0f s (%s)." % (role, name, s["left"], why), 30)
            return "cooldown", s
        return "busy", s

    def press_skill(self, role, slot, why, presses=None):
        """
        Use a skill of the belt: animus.skill_presses presses (the first lights the cursor, the second casts it
        on you); presses=1 for a retry (a lit cursor is cast by one press).
        """
        if presses is None:
            presses = max(1, int(self.anc.get("skill_presses", 2)))
        log("%s skill '%s' (belt page %d key %s%s): %s." % (role, slot["name"], slot["page"], slot["key"],
                                                             " x%d" % presses if presses > 1 else "", why))
        self.press_slot(slot["page"] - 1, BELT_KEYS.index(slot["key"]), presses,
                        float(self.anc.get("skill_press_delay", 0.25)))
        self.last_skill_press = time.time()

    def stop_target_for_animus(self, why):
        """
        Clear the target before an animus skill or summon: the AUTO macro keeps casting while there is a target and
        the game ignores other skills meanwhile. A short pause lets the running cast end.
        """
        snap = self.snapshot()
        if snap is None or snap.target is None:
            return
        self.clear_target("Clearing the target for the animus (%s): the AUTO macro would take the skill presses."
                          % why)
        self.hold_attack_until = max(self.hold_attack_until, time.time() + 1.0)
        self.wait_running(0.4)

    @staticmethod
    def cooldown_started(s):
        """The belt slot of a skill shows its own cooldown running: the game used it."""
        return s is not None and (s["ready"] == -1 or s["left"] > 0.05)

    # ---- animus ----------------------------------------------------------

    def track_animus(self, animus, out, own):
        """Tell a death from a recall: the animus that was out is gone with (almost) no HP = it died."""
        need = float(self.anc["summon_min_hp"])
        summoned = [it for it in animus if it["summoned"]]
        if out and summoned:
            self.out_entry = summoned[0]["entry"]
            self.out_hp = min([summoned[0]["rate"]] + [e.hp if e.alive else 0.0 for e in own])   # dying = 0
            self.dead_entries.discard(self.out_entry)
        elif not out and self.out_entry is not None:
            it = next((x for x in animus if x["entry"] == self.out_entry), None)
            if it is not None:
                if it["rate"] <= DEAD_HP or self.out_hp <= DEAD_HP:
                    self.dead_entries.add(it["entry"])
                    log("Animus %s died." % it["name"])
                elif it["rate"] < need or self.out_hp < need:
                    # the last HP the client saw may be the one before the killing blow: below the summon
                    # threshold it cannot be summoned again anyway, so it is healed like a dead one
                    self.dead_entries.add(it["entry"])
                    log("Animus %s is gone with %d%% HP (died, or recalled with less than the %d%% a summon "
                        "needs): healing it." % (it["name"], round(min(it["rate"], self.out_hp) * 100),
                                                 round(need * 100)))
                else:
                    log("Animus %s is not out any more (HP %d%%): recalled." % (it["name"], round(it["rate"] * 100)))
            self.out_entry, self.out_hp = None, 1.0
        for it in animus:
            if it["entry"] in self.dead_entries and it["rate"] >= need:
                self.dead_entries.discard(it["entry"])   # healed or regenerated

    def start_heal(self, target, now):
        """
        Heal a dead animus with animus.heal_skill when the game says it is ready: 'used', 'busy' (the global delay
        of the last skill: the attack key waits a moment), 'soon' (ready within SKILL_WAIT s: waited for) or the
        reason it cannot ('cooldown', 'missing').
        """
        state, slot = self.skill_state("Heal animus", self.anc["heal_skill"],
                                       "for %s at %d%%" % (target["name"], round(target["rate"] * 100)))
        if state == "busy":
            self.hold_attack_until = now + 1.5
        if state != "ready":
            return state
        self.stop_target_for_animus("heal of %s" % target["name"])
        self.mem.command(BOT_CMD_ANIMUS_SELECT, index=target["entry"])   # as if clicked in the animus window
        self.press_skill("Heal animus", slot, "%s at %d%% HP" % (target["name"], round(target["rate"] * 100)))
        now = time.time()
        self.revive = {"entry": target["entry"], "name": target["name"], "before": target["rate"], "since": now,
                       "stage": "heal_check" if slot["ready"] != 2 else "heal", "tries": 1, "started": now,
                       "why": "after the heal of %s" % target["name"]}
        return "used"

    def revive_step(self, animus, now):
        """
        Next step of a heal: did the game use it (cooldown), wait for the HP, then the summon reset.
        True = busy, no summon this tick.
        """
        a, r = self.anc, self.revive
        need = float(a["summon_min_hp"])
        if r["stage"] == "heal_check":               # did the game use the heal? its cooldown starts then
            it = next((x for x in animus if x["entry"] == r["entry"]), None)
            healed = it is not None and it["rate"] >= max(need, r["before"] + 0.05)
            if healed or self.cooldown_started(self.belt_skill(a["heal_skill"])):
                r["stage"], r["since"] = "heal", now   # used: wait for the HP
            elif now - r["since"] < SKILL_CHECK:
                return True
            else:
                state, slot = self.skill_state("Heal animus", a["heal_skill"], "for %s" % r["name"])
                if state in ("busy", "soon") and now - r["started"] < 20.0:
                    self.hold_attack_until = now + 1.5
                    return True                      # global delay / cast: next tick
                if state == "ready" and r["tries"] < RESET_TRIES:
                    log("Heal animus skill '%s': the game did not use it (busy or only the cursor lit up), one "
                        "more press." % a["heal_skill"])
                    self.stop_target_for_animus("heal of %s" % r["name"])
                    self.mem.command(BOT_CMD_ANIMUS_SELECT, index=r["entry"])
                    self.press_skill("Heal animus", slot, "try %d for %s" % (r["tries"] + 1, r["name"]), presses=1)
                    r["tries"] += 1
                    r["since"] = time.time()
                    return True
                log("Heal animus skill '%s': the game did not use it after %d tries, again in 5 s."
                    % (a["heal_skill"], r["tries"]))
                self.revive = None
                self.heal_retry_after = now + 5.0
                self.last_summon = 0.0
                return False
        if r["stage"] == "heal":
            it = next((x for x in animus if x["entry"] == r["entry"]), None)
            healed = it is not None and it["rate"] >= max(need, r["before"] + 0.05)
            if not healed and now - r["since"] < 5.0:
                return True                          # cast time, server answer
            if healed:
                log("Animus %s healed: %d%% -> %d%% HP." % (r["name"], round(r["before"] * 100),
                                                            round(it["rate"] * 100)))
                self.dead_entries.discard(r["entry"])
            else:
                log("Animus %s: no HP from the heal within 5 s (%d%%)." % (
                    r["name"], round((it["rate"] if it else 0.0) * 100)))
            if not (healed and a["reset_after_heal"] and str(a["reset_skill"]).strip()):
                self.revive = None
                self.last_summon = 0.0
                return False
            r["stage"], r["since"] = "reset", now
        if r["stage"] == "reset":
            state, slot = self.skill_state("Summon reset", a["reset_skill"], r["why"])
            if state == "busy" and now - r["since"] < 3.0:
                self.hold_attack_until = now + 1.5   # the global delay of the last skill: next tick
                return True
            if state == "soon" and now - r["since"] < SKILL_WAIT + 3.0:
                return True                          # its cooldown ends in a moment
            if state == "ready":
                if slot["ready"] == 2 and now - self.last_reset_press < 30.0:
                    self.revive = None               # cooldowns unknown: not again so soon
                    self.last_summon = 0.0 if r["entry"] is not None else now
                    return False
                self.stop_target_for_animus(r["why"])
                self.press_skill("Summon reset", slot, r["why"])
                self.last_reset_press = time.time()
                r["tries"] = 1
                r["stage"], r["since"] = ("cast" if slot["ready"] == 2 else "reset_check"), time.time()
                return True
            self.revive = None
            self.last_summon = 0.0 if r["entry"] is not None else now   # healed: summon now; refused: wait
            return False
        if r["stage"] == "reset_check":              # did the game use it? its cooldown starts then
            if self.cooldown_started(self.belt_skill(a["reset_skill"])):
                r["stage"], r["since"] = "cast", now
                return True
            if now - r["since"] < SKILL_CHECK:
                return True
            if r["tries"] < RESET_TRIES:
                state, slot = self.skill_state("Summon reset", a["reset_skill"], r["why"])
                if state == "busy" and now - r["since"] < 3.0:
                    self.hold_attack_until = now + 1.5
                    return True              # global delay: next tick
                if state == "ready":
                    log("Summon reset skill '%s': the game did not use it (busy or only the cursor lit up), one "
                        "more press." % a["reset_skill"])
                    self.stop_target_for_animus(r["why"])
                    self.press_skill("Summon reset", slot, "try %d, %s" % (r["tries"] + 1, r["why"]), presses=1)
                    self.last_reset_press = time.time()
                    r["tries"] += 1
                    r["since"] = time.time()
                    return True
            log("Summon reset skill '%s': the game did not use it after %d tries, summoning without it."
                % (a["reset_skill"], r["tries"]))
            self.revive = None
            self.last_summon = 0.0
            return False
        if now - r["since"] < 1.0:                   # "cast": let the reset go through, then summon
            return True
        self.revive = None
        self.last_summon = 0.0
        return False

    def summon_from_list(self, animus, now):
        """
        Heal / reset / summon the right animus with the game's own animus window functions.
        True = busy with it (a heal, reset or summon is in progress or due in a moment): no fighting meanwhile.
        """
        a = self.anc
        need = float(a["summon_min_hp"])
        if self.summon_pending is not None:          # a summon that brought no animus out: refused
            name, since = self.summon_pending
            answering = self.mem.request_pending() and now - since < 20.0   # cast / no server answer yet
            if answering or now - since < float(a["summon_check_seconds"]):
                return True                          # no target until the animus is out (the macro would cancel it)
            self.summon_pending = None
            self.log_limited("refused", "Summon of %s: no animus out after %.0f s, the game refused it (summon "
                                        "wait after a death?)." % (name, now - since), 60.0)
            if str(a["reset_skill"]).strip():   # the reset step of a heal: waits out a global delay, then summons
                self.revive = {"entry": None, "name": name, "before": 0.0, "since": now, "stage": "reset",
                               "why": "the summon of %s was refused" % name}
            self.last_summon = now
        if self.revive is not None and self.revive_step(animus, now):
            return True
        ranked, why = self.rank_animus(animus)
        if ranked is None:
            if now - self.last_summon >= self.t["summon_interval"]:
                self.last_summon = now
                self.log_limited("noanimus", "No animus can be summoned now: %s." % why, 30.0)
            return False
        choice = next((it for it in ranked if it["rate"] >= need), None)
        # heal: a dead one, any low one (heal_recalled), or the first low one when none can be summoned at all
        target = next((it for it in ranked if it["rate"] < need
                       and (it["entry"] in self.dead_entries or a["heal_recalled"] or choice is None)), None)
        if (target is not None and str(a["heal_skill"]).strip() and now >= self.heal_retry_after
                and (choice is None or ranked.index(target) < ranked.index(choice))
                and self.start_heal(target, now) in ("used", "busy", "soon")):
            return True                              # healing, or the heal is ready in a moment
        if now - self.last_summon < self.t["summon_interval"]:
            return False
        self.last_summon = now
        if choice is None:
            _, why = self.pick_animus(animus)
            self.log_limited("noanimus", "No animus can be summoned now: %s." % why, 30.0)
            return False
        self.stop_target_for_animus("summon of %s" % choice["name"])
        result = self.mem.command(BOT_CMD_SUMMON, index=choice["entry"])
        if result == BOT_CMDR_OK:
            self.summon_pending = (choice["name"], time.time())
        self.log_limited("summon:" + choice["name"], "Summoning %s (HP %d%%): %s." % (
            choice["name"], round(choice["rate"] * 100),
            "requested" if result == BOT_CMDR_OK else BOT_CMDR_NAMES.get(result, "no answer")), 15.0)
        return result == BOT_CMDR_OK

    def handle_animus(self, snap, now):
        """Animus summon / heal; True = busy with it (no fighting meanwhile, combat.actions_first)."""
        a = self.anc
        own = self.own_animus(snap)
        index = self.mem.animus_index()
        self.animus_ids = {index} if index is not None else set()
        self.report_animus_attacks(snap)
        if not a["enabled"]:
            return False
        out = self.mem.animus_out()        # what the game itself says, None = unknown
        animus = self.mem.animus_list() if out is not None else None
        if animus is None:
            self.dll_can("animusList", "Summoning the animus")
            return False
        self.track_animus(animus, out, own)
        if out:
            if self.summon_pending is not None:
                log("Animus %s is out (%.1f s after the summon request)." % (self.summon_pending[0],
                                                                           now - self.summon_pending[1]))
            self.animus_absent_since = None   # summoned: a summon would recall it
            self.summon_pending = None
            return False
        if self.animus_absent_since is None:
            self.animus_absent_since = now
        # a known death (or a heal / reset / summon under way) needs no wait (no recall to tell apart)
        if (now - self.animus_absent_since < a["absent_confirm_seconds"] and not self.dead_entries
                and self.revive is None and self.summon_pending is None):
            return False
        return bool(self.summon_from_list(animus, now))

    # ---- main tick -------------------------------------------------------

    def side_actions(self, snap, now):
        """Actions that run alongside everything else: animus summon, 'any' (and in combat 'in') actions."""
        if self.quit or not self.running:
            return
        self.handle_animus(snap, now)
        if self.quit or not self.running:
            return
        self.run_actions(snap, now, ("any", "in") if snap.target is not None else ("any",), False)

    def poll_dll_log(self):
        """Once a second: new BotCore.log lines into the bot log (also while paused)."""
        now = time.time()
        if now - self.dll_log_polled < 1.0:
            return
        self.dll_log_polled = now
        snap = self.snapshot()
        if snap is not None:
            self.dll_log.attach(snap.pid)
        self.dll_log.poll()

    def loot_reason(self, it, av, now):
        """
        None when the drop is wanted, else why it is left: name filters, skipped (stayed on the ground), owner
        (loot.only_mine: free / party / no owner, or yours by your index or serial), farther than anchor.leash
        from the anchor (the walk back would fight the walk to the loot).
        """
        lc = self.loot
        nm = it["name"].lower()
        only = [str(n).lower() for n in (lc.get("only_names") or []) if str(n).strip()]
        skip = [str(n).lower() for n in (lc.get("skip_names") or []) if str(n).strip()]
        if only and not any(k in nm for k in only):
            return "not in only_names"
        if skip and any(k in nm for k in skip):
            return "in skip_names"
        if self.loot_skips.get(it["index"], 0.0) > now:
            return "skipped (stayed on the ground)"
        owner = it.get("owner", 0xFFFFFFFF)
        if lc.get("only_mine", True) and owner not in LOOT_FREE_OWNERS + (av.index, av.serial):
            return "another player's (owner 0x%X)" % owner
        if (self.anchor and self.ac["enabled"]
                and dist_xz(it["pos"][0], it["pos"][2], self.anchor[0], self.anchor[2]) > float(self.ac["leash"])):
            return "farther than the leash from the anchor"
        return None

    def loot_targets(self, snap, now, report=False):
        """
        Wanted drops [(squared distance to you, item)] (loot_reason). report: when drops lie around but none is
        wanted, or the module never wrote its ground list, log why (now and then).
        """
        items = self.mem.ground()
        if not items:
            self.loot_state.clear()
            if report:
                info = self.mem.ground_info()
                if items is None or (info is not None and info[0] == 0):
                    self.log_limited("lootnolist", "Loot: the module does not export the drops on the ground (old "
                                                   "Bagnon.dll? Rebuild and Remap): nothing can be picked up.", 300.0)
            return []
        av = snap.avatar
        present = {it["index"] for it in items}
        # forget drops that are gone (picked up, despawned)
        self.loot_state = {k: v for k, v in self.loot_state.items() if k in present}
        self.loot_skips = {k: v for k, v in self.loot_skips.items() if k in present and v > now}
        out, left = [], {}
        for it in items:
            reason = self.loot_reason(it, av, now)
            if reason is None:
                dx, dz = it["pos"][0] - av.x, it["pos"][2] - av.z
                out.append((dx * dx + dz * dz, it))
            else:
                left.setdefault(reason.split(" (")[0], []).append(it)
        if report and left and not out:
            self.log_limited("lootwhy", "Loot: %d drop(s) around, none taken: %s (you: index %d = 0x%X, serial %d = "
                                        "0x%X). Debug hotkey (%s) lists them; send me that output."
                             % (len(items), "; ".join("%d %s, e.g. '%s' owner 0x%X" % (
                                 len(v), k, v[0]["name"], v[0].get("owner", 0)) for k, v in left.items()),
                                av.index, av.index, av.serial, av.serial, self.hk_label("debug")), 20.0)
        return out

    def pick_up(self, it, dist, now):
        """
        One pickup request (packet 7/2) for a drop within loot.pickup_range. A drop still on the ground is retried
        every LOOT_RETRY s; the second try walks right onto it first; after loot.tries requests it is skipped for
        loot.skip_seconds.
        """
        lc = self.loot
        st = self.loot_state.setdefault(it["index"], {"tries": 0, "last": 0.0, "walked": False})
        if now - st["last"] < LOOT_RETRY:
            return                         # the server's answer may still come
        if st["tries"] >= max(1, int(lc.get("tries", 4))):
            skip = float(lc.get("skip_seconds", 60.0))
            self.loot_skips[it["index"]] = now + skip
            del self.loot_state[it["index"]]
            log("Loot '%s' (%.0f away): still on the ground after %d pickup requests, skipped for %.0f s (another "
                "player's, full inventory, or the server wants you closer?)." % (it["name"], dist, st["tries"], skip))
            return
        self.last_loot = st["last"] = now
        if st["tries"] and not st["walked"] and dist > LOOT_CLOSE and lc.get("walk") and self.mem.supports_moves():
            st["walked"] = True
            res = self.mem.command(BOT_CMD_MOVE, pos=(it["pos"][0], it["pos"][1], it["pos"][2]))
            log("Loot '%s' not picked up from %.0f away: walking onto it%s." % (
                it["name"], dist, "" if res == BOT_CMDR_OK else " (%s)" % (BOT_CMDR_NAMES.get(res, res)
                                                                          if res is not None else "no answer")))
            return
        st["tries"] += 1
        res = self.mem.command(BOT_CMD_LOOT, index=it["index"])
        if res == BOT_CMDR_NOT_FOUND:      # taken by someone or despawned meanwhile: nothing went to the server
            self.loot_skips[it["index"]] = now + float(lc.get("skip_seconds", 60.0))
            self.loot_state.pop(it["index"], None)
            self.log_limited("lootgone", "Loot '%s': already gone from the ground, skipped." % it["name"], 10.0)
            return
        if res in LOOT_REFUSED:
            # the module will not run this pickup at all: retrying or walking closer cannot help
            self.loot_skips[it["index"]] = now + float(lc.get("skip_seconds", 60.0))
            self.loot_state.pop(it["index"], None)
            self.loot_refused += 1
            self.log_limited("lootrefused", "Loot '%s' #%d (owner 0x%X, %.0f away): the module refused the pickup "
                                            "(%s), skipped. This is on the module side (see the 'bot loot' line "
                                            "in BotCore.log): send that line and BotCore.log."
                             % (it["name"], it["index"], it.get("owner", 0), dist, BOT_CMDR_NAMES.get(res, res)), 60.0)
            if self.loot_refused == LOOT_REFUSED_LIMIT:
                log("Loot: the module refused %d pickups in a row: no more walking to loot and no waiting for drops "
                    "before the next target until a pickup goes through." % self.loot_refused)
            return
        if res == BOT_CMDR_OK:
            if self.loot_refused >= LOOT_REFUSED_LIMIT:
                log("Loot: the module took a pickup again, walking to loot and 'Loot first' are back on.")
            self.loot_refused = 0
        self.log_limited("loot", "Loot '%s' (%.0f away, try %d): %s." % (
            it["name"], dist, st["tries"], BOT_CMDR_NAMES.get(res, res) if res is not None
            else "no answer (timeout)"), 3.0)

    def do_loot(self, snap, now, priority=False):
        """
        The nearest wanted drop: within loot.pickup_range -> pickup request (pick_up); farther -> walk to it first
        (walk_to_loot) and pick it up on arrival. Walked to: drops within loot.radius at once (also during a fight
        when in_combat is on), drops within loot.walk_radius when not fighting (loot.walk). A dead target is no
        fight. `priority`: no monster within loot.priority_no_mobs_radius -> also during a fight, faster.
        """
        lc = self.loot
        if not lc.get("enabled") or now - self.last_loot < float(lc.get("delay", 0.4)):
            return
        if not self.dll_can("loot", "Picking up loot"):
            return
        if self.casting():                 # walking to a drop would break the cast
            return
        fighting = snap.target is not None and snap.target.type == OBJ_MONSTER and snap.target.alive
        if fighting and not lc.get("in_combat") and not priority:
            return
        cands = self.loot_targets(snap, now, report=True)
        if not cands:
            self.loot_walk = None
            return
        pr = max(1.0, float(lc.get("pickup_range", 25.0)))
        bd, best = min(cands, key=lambda c: c[0])
        if bd <= pr * pr:
            self.loot_walk = None
            self.pick_up(best, bd ** 0.5, now)
            self.last_loot_walk = 0.0
            return
        # too far for a pickup: walk to the nearest drop the bot goes for now
        if self.loot_refused >= LOOT_REFUSED_LIMIT or not self.mem.supports_moves():
            return                     # the module refuses pickups / cannot walk: no walking for them
        reach = float(lc.get("radius", 120.0))
        if lc.get("walk") and (not fighting or priority):
            reach = max(reach, float(lc.get("walk_radius", 400.0)))
        near = [c for c in cands if c[0] <= reach * reach]
        if near:
            td, target = min(near, key=lambda c: c[0])
            self.walk_to_loot(target, td ** 0.5, now, fighting, priority)

    def walk_to_loot(self, it, dist, now, fighting, priority):
        """
        One walk request towards a drop (MoveRequest, like a click on the ground), repeated while the character
        walks there. No closer for LOOT_WALK_STUCK requests or walking longer than LOOT_WALK_MAX s: unreachable,
        skipped for loot.skip_seconds.
        """
        gap = 0.6 if priority or not fighting else 1.0
        if now - self.last_loot_walk < gap:
            return
        w = self.loot_walk
        if w is None or w["index"] != it["index"]:
            w = self.loot_walk = {"index": it["index"], "best": dist, "stuck": 0, "since": now}
        elif dist < w["best"] - 5.0:
            w["best"], w["stuck"] = dist, 0
        else:
            w["stuck"] += 1
        if w["stuck"] >= LOOT_WALK_STUCK or now - w["since"] > LOOT_WALK_MAX:
            skip = float(self.loot.get("skip_seconds", 60.0))
            self.loot_skips[it["index"]] = now + skip
            self.loot_walk = None
            log("Loot '%s' (%.0f away): the character does not get to it (blocked?), skipped for %.0f s."
                % (it["name"], dist, skip))
            return
        self.last_loot_walk = now
        res = self.mem.command(BOT_CMD_MOVE, pos=(it["pos"][0], it["pos"][1], it["pos"][2]))
        self.log_limited("lootwalk", "Walking to loot '%s' (%.0f away, picked up from %.0f)%s%s."
                         % (it["name"], dist, float(self.loot.get("pickup_range", 25.0)),
                            " [priority: no monsters near]" if priority else "",
                            "" if res == BOT_CMDR_OK else ": %s" % (BOT_CMDR_NAMES.get(res, res)
                                                                     if res is not None else "no answer")), 5.0)

    def attacked(self, snap):
        """A live monster attacked you or your animus within targeting.priority_window."""
        return any(e.type == OBJ_MONSTER and e.alive and self.priority(e, snap) < 2 for e in snap.entities)

    def loot_hold(self, snap, now):
        """
        loot.first: True = no new target and no walk back to the anchor yet, the loot comes first: a monster just
        died (its drop may come within loot.after_kill_wait s) or a wanted drop is within reach. Never while a
        monster attacks you or your animus; at most loot.max_hold_seconds in a row (then the drops in reach are
        skipped for loot.skip_seconds and the bot fights again).
        """
        lc = self.loot
        if (not lc.get("enabled") or not lc.get("first", True) or self.attacked(snap)
                or self.loot_refused >= LOOT_REFUSED_LIMIT or not self.mem.dll_flag("loot")):      # the module refuses pickups: do not wait for them
            self.loot_hold_since = None
            return False
        reach = float(lc.get("radius", 120.0))
        if lc.get("walk") and self.mem.supports_moves():
            reach = max(reach, float(lc.get("walk_radius", 400.0)))
        waiting = self.last_kill is not None and now - self.last_kill < float(lc.get("after_kill_wait", 2.0))
        drops = [it for d2, it in self.loot_targets(snap, now) if d2 <= reach * reach]
        if not waiting and not drops:
            self.loot_hold_since = None
            return False
        if self.loot_hold_since is None:
            self.loot_hold_since = now
        held = now - self.loot_hold_since
        if held > float(lc.get("max_hold_seconds", 10.0)):
            skip = float(lc.get("skip_seconds", 60.0))
            for it in drops:
                self.loot_skips[it["index"]] = now + skip
            self.loot_hold_since = None
            self.last_kill = None
            log("Loot first: %s not picked up within %.0f s, skipped for %.0f s; fighting again."
                % (", ".join("'%s'" % it["name"] for it in drops[:3]) or "no drop", held, skip))
            return False
        self.log_limited("lootfirst", "Loot first: %s before the next target." % (
            "picking up %s" % ", ".join("'%s'" % it["name"] for it in drops[:3]) if drops
            else "waiting for the drop of the monster just killed"), 10.0)
        return True

    def tick(self):
        self.poll_dll_log()
        if not self.poll_controls():
            return
        snap = self.snapshot()
        if snap is None:
            self.log_limited("nosnap", "Waiting for the game: %s." % self.mem.status, 10.0)
            return
        self.update_window(snap)
        if self.quit or not self.running:
            return
        if snap.avatar.hp <= 0:
            self.log_limited("dead", "Your character is dead (HP 0), waiting.", 15.0)
            self.was_dead = True
            self.homing = None
            return
        if self.was_dead:                  # back to life: in place (resurrected) or somewhere else (respawned)
            self.was_dead = False
            d = self.anchor_dist(snap) if self.anchor else 0.0
            if d > max(3.0 * float(self.ac["leash"]), 1000.0):
                self.running = False
                log("Your character is alive again %.0f from the anchor (respawned elsewhere?): bot PAUSED. Walk "
                    "back and start it again (%s)." % (d, self.hk_label("toggle")))
                return

        now = time.time()
        self.follow_markers(snap)
        no_mobs_near = False
        pr = float(self.loot.get("priority_no_mobs_radius", 0.0) or 0.0)
        if pr > 0:
            no_mobs_near = not any(e.type == OBJ_MONSTER and e.alive and e.distance <= pr
                                   for e in snap.entities)
        self.do_loot(snap, now, priority=no_mobs_near)
        if self.cc["actions_first"]:
            if self.handle_animus(snap, now):  # 1. the animus: a heal / reset / summon in progress, nothing else
                self.hold_attack_until = max(self.hold_attack_until, time.time() + 0.5)
                return
            if self.quit or not self.running:
                return
            if self.verify_action(snap, now):   # 2. buffs, potions, heals: did the game use the last one?
                return
            if self.homing is not None:     # walking back: no 'out' buffs (a cast stops the walk)
                combats = ("any", "in") if snap.target is not None else ("any",)
            else:
                combats = ("out", "any", "in") if snap.target is not None else ("out", "any")
            if self.run_actions(snap, now, combats, True):   # one per tick
                return
        else:
            self.side_actions(snap, now)
        if self.quit or not self.running:
            return
        self.idle_since = None if snap.target is not None else (self.idle_since or now)

        if self.homing is None and self.anchor and self.ac["enabled"] and now >= self.nav_blocked_until:
            d = self.anchor_dist(snap)
            if d > self.ac["leash"] and self.dll_can("moves", "Walking back to the anchor"):
                log("Too far from the anchor: %.0f (leash %.0f), walking back%s."
                    % (d, self.ac["leash"], " while keeping the target" if snap.target else ""))
                self.homing = {"steps": 0, "idle": 0, "sent": None, "anchor": self.anchor}
        if self.homing is not None and self.home_step(snap, now):
            return

        if snap.target is not None:
            self.handle_combat(snap, now)
            return
        if self.combat_key is not None:    # the bot did not clear it (clear_target resets combat_key)
            self.note_target_drop(snap, now)
        self.reset_combat()

        if not self.cc["actions_first"] and self.run_actions(snap, now, ("out",), True):
            return
        if self.quit or not self.running:
            return
        if self.loot_hold(snap, now):      # loot.first: the drop before the next target / the walk back
            return
        self.acquire_target(snap)
        if self.combat_key is None and self.running and not self.quit:   # nothing selected: 3. back to the anchor
            self.idle_return(snap, now)

    def idle_return(self, snap, now):
        """
        No target for anchor.idle_return_seconds: one walk request to the anchor through the game (repeated
        every 3 s while still away). Not blocking: a monster that shows up on the way is attacked at once.
        """
        ac = self.ac
        wait = float(ac["idle_return_seconds"])
        if (wait <= 0 or not self.anchor or not ac["enabled"] or self.idle_since is None
                or now - self.idle_since < wait or now - self.last_idle_walk < 3.0 or self.casting()):
            return
        d = self.anchor_dist(snap)
        if d <= ac["return_dist"] or not self.dll_can("moves", "Walking back to the anchor"):
            return
        self.last_idle_walk = now
        av = snap.avatar
        ax, ay, az = self.anchor
        result = self.mem.command(BOT_CMD_MOVE, pos=(ax, ay, az))
        if result != BOT_CMDR_OK and d > ac["step"]:   # no path to the anchor itself: a nearer point towards it
            f = ac["step"] / d
            result = self.mem.command(BOT_CMD_MOVE, pos=(av.x + (ax - av.x) * f, av.y + (ay - av.y) * f,
                                                         av.z + (az - av.z) * f))
        self.log_limited("idlewalk", "No target for %.0f s: walking back to the anchor (%.0f away)%s."
                         % (now - self.idle_since, d, "" if result == BOT_CMDR_OK else ": the game refused it"), 20.0)

    # ---- combat ----------------------------------------------------------

    def note_target_drop(self, snap, now):
        """
        The target is gone, but the bot did not clear it: if the monster is alive and took no damage, the game
        dropped it (hidden from you, out of reach / sight). Once: skip it 3 s; twice within a minute: 60 s.
        """
        e = snap.find(self.combat_key)
        if e is None or not e.alive:
            self.last_kill = now           # died (or vanished): its drop may come in a moment
            return
        if self.combat_start_hp is None or e.hp < self.combat_start_hp - 0.005:
            return
        drops = [t for t in self.target_drops.get(e.key, []) if now - t < 60.0] + [now]
        self.target_drops = {k: v for k, v in self.target_drops.items() if now - v[-1] < 60.0}
        self.target_drops[e.key] = drops
        if len(drops) < 2:
            self.skip(e.key, 3.0)
            return
        self.skip(e.key, 60.0)
        log("%s: the game dropped it as the target %d times within a minute, without damage: skipped for 60 s (%s, "
            "flags 0x%04X)." % (e.label(), len(drops), "hidden from you" if e.hidden else
                                "out of reach or out of sight?", e.flags))

    def reset_combat(self):
        self.combat_key = None
        self.combat_hp = None
        self.combat_start_hp = None
        self.dead_since = None
        self.far_since = None
        self.switch_far_since = None

    def rotation_slots(self, belt, page=None):
        """
        {slot 1..10: belt entry} for rotation entries without a page: the slot of the page the belt shows, else
        the first page (1..5) that has something on that slot.
        """
        page = page or self.mem.belt_page() or 1
        out = {}
        for b in belt:
            if b["page"] == page:          # the page the belt shows first
                out[BELT_KEYS.index(b["key"]) + 1] = b
        for b in belt:
            out.setdefault(BELT_KEYS.index(b["key"]) + 1, b)
        return out

    def rotation_entry_slot(self, entry, belt, shown):
        """The belt entry a rotation entry {'page', 'slot'} uses now, None when that slot is empty."""
        if entry["page"]:
            key = BELT_KEYS[entry["slot"] - 1]
            return next((b for b in belt if b["page"] == entry["page"] and b["key"] == key), None)
        return shown.get(entry["slot"])

    def rotation_pick(self):
        """
        The first rotation entry that can be used now ({'page' 1-5, 'slot' 1-10, 'entry'}); None when the
        rotation is off, empty, or nothing in it is ready (the plain attack key is pressed then).
        """
        if not self.rot.get("enabled", True):
            return None
        slots = list(self.rot.get("slots") or [])
        if not slots:
            return None
        belt = self.mem.belt() or []
        shown = self.rotation_slots(belt)
        only_ready = bool(self.rot.get("only_ready", True))
        now = time.time()
        for r in slots:
            entry = self.rotation_entry_slot(r, belt, shown)
            if entry is None:
                continue                    # nothing (known) on that slot
            if entry.get("kind") == BELT_SF and now - self.last_skill_press < GLOBAL_DELAY:
                continue                    # a skill pressed now would only light the skill cursor
            if only_ready and entry.get("ready", 2) in (-1, 0):
                continue                    # its own cooldown, or a global / shared delay runs
            return {"page": entry["page"], "slot": r["slot"], "entry": entry}
        return None

    def attack_key_entry(self):
        """The belt entry keys.attack uses now (a belt key, on the page the belt shows); None when the key is no
        belt key or the belt is not known."""
        slot = belt_slot(self.cfg["keys"].get("attack", ""))
        page = self.mem.belt_page()
        belt = self.mem.belt()
        if slot is None or not page or belt is None:
            return None
        key = BELT_KEYS[slot]
        return next((b for b in belt if b["page"] == page and b["key"] == key), None)

    def skill_press_ok(self, entry, now):
        """
        A skill / force of the belt may be pressed now: our last skill press is at least GLOBAL_DELAY ago and the
        game's own check says it can be used (1) or the module cannot tell (2). A press the game does not cast
        lights the skill cursor instead.
        """
        return now - self.last_skill_press >= GLOBAL_DELAY and entry.get("ready", 2) in (1, 2)

    def press_rotation(self):
        """
        One combat press: the first ready slot of the rotation (next press after rotation.interval_seconds), else
        the plain attack key keys.attack (next press after a random timing.attack_interval_min..max seconds).
        """
        now = time.time()
        if self.casting():                 # a press now would light the skill cursor: next tick
            self.attack_gap = 0.1
            return
        self.last_attack = now
        pick = self.rotation_pick()
        if pick:
            self.attack_gap = float(self.rot.get("interval_seconds", 1.0))
            self.press_slot(pick["page"] - 1, pick["slot"] - 1)
            self.last_skill_press = time.time()
            return
        entry = self.attack_key_entry()
        if entry is not None and entry["kind"] == BELT_SF:
            # the attack key holds a skill: pressed only when the game casts it (an early press lights the cursor)
            if not self.skill_press_ok(entry, now):
                self.attack_gap = 0.1      # look again next tick
                return
            self.log_limited("attackskill", "Attack key %s is the skill '%s' on the belt: pressed only when the game "
                                            "says it is ready, at least %.1f s apart (an early press lights the "
                                            "skill cursor). An AUTO macro on that key is pressed as often as "
                                            "timing.attack_interval says." % (self.cfg["keys"].get("attack", "?"),
                                                                               entry["name"], GLOBAL_DELAY), 600.0)
            self.attack_gap = GLOBAL_DELAY
            self.press_vk(self.keys["attack"])
            self.last_skill_press = time.time()
            return
        lo = max(0.05, float(self.t.get("attack_interval_min", 0.1)))
        hi = max(lo, float(self.t.get("attack_interval_max", 0.25)))
        self.attack_gap = random.uniform(lo, hi)
        self.press_vk(self.keys["attack"])
        self.last_skill_press = time.time()     # a macro may cast: actions wait out its global delay

    def handle_combat(self, snap, now):
        t = snap.target
        av = snap.avatar
        if t.type != OBJ_MONSTER:
            self.clear_target("Selected %s is not a monster, clearing it." % t.label())
            return
        self.my_monsters[t.key] = now
        if t.key != self.combat_key:
            self.combat_key = t.key
            self.combat_hp = self.combat_start_hp = t.hp
            self.combat_hp_changed = now
            self.my_monsters = {k: v for k, v in self.my_monsters.items() if now - v < 120.0}
            self.dead_since = None
            self.far_since = None
            self.switch_far_since = None
        elif abs(t.hp - self.combat_hp) >= 0.005:
            self.combat_hp = t.hp
            self.combat_hp_changed = now

        if not t.alive:
            if self.dead_since is None:
                self.dead_since = self.last_kill = now   # its drop may come in a moment (loot.first)
            elif now - self.dead_since >= self.t["dead_target_clear"]:
                self.skip(t.key, 60.0)
                self.clear_target("Target %s is dead, clearing it." % t.label())
            return
        self.dead_since = None

        if now - self.combat_hp_changed >= self.t["target_stuck_seconds"]:
            self.skip(t.key, 30.0)
            self.clear_target("Target %s HP has not changed for %.0f s, clearing it."
                              % (t.label(), self.t["target_stuck_seconds"]))
            return

        max_dist = float(self.cc["max_attack_distance"])
        if max_dist > 0:
            d = t.dist(av.x, av.z)
            if d > max_dist:
                if self.far_since is None:
                    self.far_since = now
                self.log_limited("fardist", "Target %s is out of attack range (%.0f, max %.0f), not attacking."
                                 % (t.label(), d, max_dist), 10.0)
                if now - self.far_since >= self.cc["far_target_timeout"]:
                    self.skip(t.key, self.tc["miss_seconds"])
                    self.clear_target("Target %s stayed out of range for %.0f s, clearing it."
                                      % (t.label(), self.cc["far_target_timeout"]))
                return
            self.far_since = None

        if self.switch_far_target(t, snap, now):
            return
        if self.switch_target(t, snap, now):
            return
        if time.time() < self.hold_attack_until:
            return                         # a heal / reset skill waits for the global delay of the last skill
        wait = self.attack_gap - (time.time() - self.last_attack)
        if wait < float(self.t.get("tick_seconds", TICK_SECONDS)):   # due within this tick: press on time
            if wait > 0 and not self.wait_running(wait):
                return
            self.press_rotation()

    def switch_far_target(self, t, snap, now):
        """
        combat.switch_distance: the target is farther than that from you for switch_distance_seconds -> another
        monster nearer to you (the far one is skipped for targeting.miss_seconds). None nearer: keep it.
        """
        limit = float(self.cc.get("switch_distance", 0.0) or 0.0)
        av = snap.avatar
        d = t.dist(av.x, av.z)
        if limit <= 0 or d <= limit:
            self.switch_far_since = None
            return False
        if self.switch_far_since is None:
            self.switch_far_since = now
        if now - self.switch_far_since < float(self.cc.get("switch_distance_seconds", 1.0)):
            return False
        if not self.mem.supports_commands():
            return False
        other = next((e for e in self.candidates(snap) if e.key != t.key and e.dist(av.x, av.z) < d), None)
        if other is None:
            self.log_limited("swfar", "Target %s is %.0f from you (switch distance %.0f), no other monster nearer: "
                                      "keeping it." % (t.label(), d, limit), 10.0)
            return False
        self.skip(t.key, self.tc["miss_seconds"])
        self.switch_far_since = None
        self.last_switch = now
        log("Target %s is %.0f from you (more than %.0f): switching to %s (%.0f)."
            % (t.label(), d, limit, other.label(), other.dist(av.x, av.z)))
        self.select_entity(other, snap)
        return True

    def switch_target(self, t, snap, now):
        """Leave the current target for a monster that attacks your animus."""
        tc = self.tc
        if not tc["switch_to_animus_attackers"] or now - self.last_switch < tc["switch_cooldown"]:
            return False
        if self.priority(t, snap) == 0 or not self.mem.supports_commands():
            return False
        best = next((e for e in self.candidates(snap)
                     if e.key != t.key and self.priority(e, snap) == 0), None)
        if best is None:
            return False
        self.last_switch = now
        log("Switching from %s to %s: it attacks your animus." % (t.label(), best.label()))
        self.select_entity(best, snap)
        return True

    # ---- targeting -------------------------------------------------------

    def center(self, snap):
        """Search center: the anchor, else your character."""
        if self.anchor:
            return self.anchor[0], self.anchor[2]
        return snap.avatar.x, snap.avatar.z

    def target_filters(self, snap):
        """targeting settings prepared once per search (lower-case names, search center, distances)."""
        tc = self.tc
        return {"only": [] if tc.get("attack_any") else [str(n).lower() for n in tc["only_names"]],
                "skip": [str(n).lower() for n in tc["skip_names"]],
                "center": self.center(snap),
                "max_dist": float(self.cc["max_attack_distance"]),
                "fight_back": max(tc["search_radius"], self.ac["leash"])}

    def is_candidate(self, e, snap, now, prio, flt):
        """A live monster we may attack (prio: self.priority(e, snap), flt: self.target_filters(snap))."""
        tc = self.tc
        if e.type != OBJ_MONSTER or not e.alive or e.hidden:   # hidden: the game would drop it as the target
            return False
        if self.is_skipped(e.key, now):
            return False
        if prio < 2:                      # it attacks you or your animus: fight back, whatever its name / level
            return e.distance <= flt["fight_back"]
        name = e.name.lower()
        if flt["only"] and not any(n in name for n in flt["only"]):   # attack_any: no only_names whitelist
            return False
        if flt["skip"] and any(n in name for n in flt["skip"]):        # skip_names always wins
            return False
        if e.hp < tc["min_hp"] or (tc["skip_damaged"] and e.hp < 0.999):
            return False
        if (tc["min_level"] and e.level < tc["min_level"]) or (tc["max_level"] and e.level > tc["max_level"]):
            return False
        if e.dist(*flt["center"]) > tc["search_radius"]:
            return False
        return not (flt["max_dist"] > 0 and e.distance > flt["max_dist"])

    def priority(self, e, snap):
        """0 = attacked your animus, 1 = attacked you (within targeting.priority_window), 2 = any other."""
        if e.victim_age_ms <= self.tc["priority_window"] * 1000.0:
            if e.victim_type == OBJ_ANIMUS and e.victim_index in self.animus_ids:
                return 0
            if e.victim_type in (OBJ_PLAYER, OBJ_AVATAR) and e.victim_index == snap.avatar.index:
                return 1
        return 2

    def someone_elses(self, e, snap, now):
        """1 = probably someone else's monster: not yours, lost HP or attacks another player; 0 = untouched."""
        if not self.tc["prefer_untouched"] or now - self.my_monsters.get(e.key, -1e9) < 120.0:
            return 0
        if e.hp < 0.999:
            return 1
        if (e.victim_type in (OBJ_PLAYER, OBJ_AVATAR) and e.victim_index != snap.avatar.index
                and e.victim_age_ms <= self.tc["priority_window"] * 1000.0):
            return 1
        return 0

    def candidates(self, snap):
        """
        Monsters to attack: attackers of your animus, then your attackers, then the rest (untouched ones before
        those someone else fights); inside each group by targeting.sort ('mixed': within near_radius of you
        nearest first, then nearest to the anchor).
        """
        now = time.time()
        flt = self.target_filters(snap)
        cx, cz = flt["center"]
        result = []
        for e in snap.entities:
            if e.type != OBJ_MONSTER:
                continue
            prio = self.priority(e, snap)
            if not self.is_candidate(e, snap, now, prio, flt):
                continue
            others = self.someone_elses(e, snap, now) if prio == 2 else 0
            d_you, d_anchor = e.distance, e.dist(cx, cz)
            if self.tc["sort"] == "anchor":
                order = (prio, others, d_anchor, d_you)
            elif self.tc["sort"] == "avatar":
                order = (prio, others, d_you, d_anchor)
            elif d_you <= float(self.tc["near_radius"]):   # mixed: close to you first, nearest first
                order = (prio, others, 0, d_you, d_anchor)
            else:                                          # then the ones nearest to the anchor (yellow marker)
                order = (prio, others, 1, d_anchor, d_you)
            result.append((order, e))
        result.sort(key=lambda item: item[0])
        return [e for _, e in result]

    def acquire_target(self, snap):
        """The best candidate selected through the game (what a click does), then wait for the server."""
        if time.time() - self.last_select < self.t["select_guard"]:
            return
        if not self.dll_can("commands", "Selecting monsters"):
            return
        cands = self.candidates(snap)
        if not cands:
            mobs = sum(1 for e in snap.entities if e.type == OBJ_MONSTER and e.alive)
            self.log_limited("idle", "No monster to attack within %.0f of the %s (%d live monsters around)."
                             % (self.tc["search_radius"], "anchor" if self.anchor else "character", mobs), 10.0)
            return
        self.select_entity(cands[0], snap)

    def select_entity(self, ent, snap):
        """Select one monster through the game and wait until the server confirms it as the target."""
        why = {0: ", it attacks your animus", 1: ", it attacks you"}.get(self.priority(ent, snap), "")
        started = self.last_select = time.time()
        result = self.mem.command(BOT_CMD_SELECT, ent.type, ent.index, ent.serial)
        if result != BOT_CMDR_OK:
            self.skip(ent.key, self.tc["skip_seconds"])
            log("Could not select %s through the game: %s." % (ent.label(), BOT_CMDR_NAMES.get(result, result)
                                                               if result is not None else "no answer (timeout)"))
            return
        while time.time() - started < self.t["target_confirm"]:
            if self.quit or not self.running:
                return
            snap = self.snapshot()
            if snap is not None and snap.target is not None and snap.target.key == ent.key:
                t = snap.target
                av = snap.avatar
                log("Target acquired: %s HP %d%%, dist %.0f (%.2f s%s)."
                    % (t.label(), round(t.hp * 100), t.dist(av.x, av.z), time.time() - started, why))
                self.combat_key = t.key
                self.combat_hp = self.combat_start_hp = t.hp
                self.combat_hp_changed = self.my_monsters[t.key] = time.time()
                self.dead_since = None
                self.far_since = None
                self.press_rotation()
                return
            time.sleep(0.03)
        self.skip(ent.key, self.tc["miss_seconds"])
        log("Selected %s, but the server did not confirm it (too far, out of sight?), skipping it for %.0f s."
            % (ent.label(), self.tc["miss_seconds"]))

    # ---- leash -----------------------------------------------------------

    def anchor_dist(self, snap):
        av = snap.avatar
        return dist_xz(self.anchor[0], self.anchor[2], av.x, av.z)

    def home_failed(self, now, why):
        self.homing = None
        self.nav_blocked_until = now + float(self.ac["retry_cooldown"])
        log("%s Return failed, next attempt in %.0f s, fighting meanwhile." % (why, self.ac["retry_cooldown"]))

    def home_step(self, snap, now):
        """
        One tick of the walk back to the anchor through the game (MoveRequest, what a click on the ground does):
        the anchor itself, else a nearer point towards it when the game finds no way. A walk request runs until
        the character stops for anchor.step_wait s (a nearer point reached, or blocked) or anchor.walk_timeout s,
        then the next one. Not blocking: the other ticks go on. True = still walking (no fighting this tick).
        """
        ac, h = self.ac, self.homing
        if not self.anchor:
            self.homing = None
            return False
        d = self.anchor_dist(snap)
        if d <= ac["return_dist"]:
            log("Back at the anchor (%.0f)." % d)
            self.homing = None
            return False
        av = snap.avatar
        pos = (av.x, av.z)
        if h["anchor"] != self.anchor:       # a new anchor while walking: a new walk request now
            h["anchor"], h["sent"] = self.anchor, None
        if h["sent"] is not None:            # a walk request runs
            if dist_xz(pos[0], pos[1], h["pos"][0], h["pos"][1]) > 3.0:
                h["pos"], h["moved_at"], h["moved"] = pos, now, True
            if now - h["sent"] < ac["walk_timeout"] and now - h["moved_at"] < ac["step_wait"]:
                return True
            h["idle"] = 0 if h["moved"] else h["idle"] + 1
            if h["idle"] >= 3:
                self.home_failed(now, "The character does not move towards the anchor (blocked?).")
                return False
            if h["steps"] >= int(ac["max_steps"]):
                self.home_failed(now, "Could not reach the anchor in %d walk requests." % h["steps"])
                return False
        ax, ay, az = self.anchor
        goals = [(ax, ay, az)]
        for s in sorted({ac["step"] * k for k in (2.0, 1.0, 0.5)}, reverse=True):
            if s < d:
                f = s / d
                goals.append((av.x + (ax - av.x) * f, av.y + (ay - av.y) * f, av.z + (az - av.z) * f))
        result = None
        for goal in goals:
            result = self.mem.command(BOT_CMD_MOVE, pos=goal)
            if result == BOT_CMDR_OK:
                break
            if result is None:
                self.home_failed(now, "The game did not answer the walk request (%s)." % self.mem.status)
                return False
        if result != BOT_CMDR_OK:
            self.home_failed(now, "The game does not walk towards the anchor: %s."
                             % BOT_CMDR_NAMES.get(result, result))
            return False
        h.update(sent=now, moved_at=now, pos=pos, moved=False, steps=h["steps"] + 1)
        return True

# ---------------------------------------------------------------------------
# Window (tkinter, part of the standard Python install)
# ---------------------------------------------------------------------------


WHEN_LABELS = {"missing": "effect missing", "ending": "effect ending", "missing_or_ending": "effect missing or ending",
               "hp_below": "my HP below %", "animus_hp_below": "animus HP below %"}
COMBAT_LABELS = {"out": "out of combat", "any": "any time", "in": "in combat"}
PAGE_LABELS = ["shown page"] + [str(i) for i in range(1, BELT_PAGES + 1)]   # index = action "page"


def belt_state_text(s):
    """Cooldown state of a belt slot for the window."""
    if s is None:
        return "not on the belt"
    if s["kind"] != BELT_SF:
        return ""
    if s["ready"] == 2:
        return "cooldown unknown"
    if s["ready"] == 1:
        return "ready"
    if s["ready"] == -1 or s["left"] > 0.05:
        return "cooldown %.0f s of %.0f s" % (s["left"], s["total"])
    return "wait (global delay)"


def action_detail(a):
    """Short text of an action's condition for the list."""
    if a["when"] in ("hp_below", "animus_hp_below"):
        return "< %g%%" % a["percent"]
    text = ", ".join(a["effects"]) or "(no effect)"
    if a["when"] in ("ending", "missing_or_ending"):
        text += " < %gs" % a["seconds"]
    return text


class ActionDialog:
    """Modal editor of one action; .result = the action (normalized) or None when cancelled."""

    def __init__(self, parent, action, effect_names):
        import tkinter as tk
        from tkinter import ttk
        a = normalize_action(action)
        self.result = None
        self.win = win = tk.Toplevel(parent)
        win.title("Action")
        win.transient(parent)
        win.resizable(False, False)
        f = ttk.Frame(win, padding=8)
        f.pack(fill="both", expand=True)
        self.vars = {}

        def row(r, label, widget):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
            widget.grid(row=r, column=1, sticky="we", pady=2)

        def var(key, value, kind=tk.StringVar):
            v = kind(value=value)
            self.vars[key] = v
            return v

        row(0, "Name", ttk.Entry(f, textvariable=var("name", a["name"]), width=32))
        row(1, "Enabled", ttk.Checkbutton(f, variable=var("enabled", a["enabled"], tk.BooleanVar)))
        keys = ttk.Frame(f)
        ttk.Combobox(keys, textvariable=var("key", a["key"].upper()), width=8, values=list(BELT_KEYS)).pack(
            side="left")
        ttk.Label(keys, text="  belt page").pack(side="left")
        ttk.Combobox(keys, textvariable=var("page", PAGE_LABELS[a["page"]]), state="readonly", width=12,
                     values=PAGE_LABELS).pack(side="left", padx=(4, 0))
        row(2, "Key (belt 1-0)", keys)
        row(3, "When", ttk.Combobox(f, textvariable=var("when", WHEN_LABELS[a["when"]]), state="readonly",
                                    values=[WHEN_LABELS[w] for w in ACTION_WHEN], width=30))
        eff = ttk.Frame(f)
        ttk.Entry(eff, textvariable=var("effects", ", ".join(a["effects"])), width=32).pack(fill="x")
        pick = ttk.Combobox(eff, values=effect_names, width=30)
        pick.set("add an effect that is on you now...")
        pick.pack(fill="x", pady=(2, 0))
        pick.bind("<<ComboboxSelected>>", lambda _e: self.add_effect(pick.get()))
        row(4, "Effects (comma)", eff)
        row(5, "Seconds left (ending)", ttk.Spinbox(f, from_=0, to=100000, increment=5, width=10,
                                                   textvariable=var("seconds", "%g" % a["seconds"])))
        row(6, "Percent (HP below)", ttk.Spinbox(f, from_=0, to=100, increment=5, width=10,
                                                textvariable=var("percent", "%g" % a["percent"])))
        row(7, "Combat", ttk.Combobox(f, textvariable=var("combat", COMBAT_LABELS[a["combat"]]), state="readonly",
                                      values=[COMBAT_LABELS[c] for c in ACTION_COMBAT], width=30))
        row(8, "Presses", ttk.Spinbox(f, from_=1, to=5, width=10, textvariable=var("presses", str(a["presses"]))))
        row(9, "Delay between presses, s", ttk.Spinbox(f, from_=0, to=5, increment=0.1, width=10,
                                                      textvariable=var("press_delay", "%g" % a["press_delay"])))
        row(10, "Cooldown, s", ttk.Spinbox(f, from_=0, to=3600, increment=1, width=10,
                                          textvariable=var("cooldown", "%g" % a["cooldown"])))
        row(11, "Wait after (cast), s", ttk.Spinbox(f, from_=0, to=10, increment=0.5, width=10,
                                                   textvariable=var("wait", "%g" % a["wait"])))
        self.lbl_error = ttk.Label(f, text="", foreground="red")
        self.lbl_error.grid(row=12, column=0, columnspan=2, sticky="w")
        buttons = ttk.Frame(f)
        buttons.grid(row=13, column=0, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Button(buttons, text="OK", command=self.ok).pack(side="left", padx=4)
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="left")
        win.grab_set()
        win.wait_window()

    def add_effect(self, name):
        name = name.rsplit("  (", 1)[0].strip()
        current = [e.strip() for e in self.vars["effects"].get().split(",") if e.strip()]
        if name and name not in current:
            self.vars["effects"].set(", ".join(current + [name]))

    def ok(self):
        v = {k: var.get() for k, var in self.vars.items()}
        when = {label: w for w, label in WHEN_LABELS.items()}[v["when"]]
        combat = {label: c for c, label in COMBAT_LABELS.items()}[v["combat"]]
        key = str(v["key"]).strip().lower()
        page = PAGE_LABELS.index(v["page"])
        if page and belt_slot(key) is None:
            self.lbl_error.configure(text="A belt page needs a belt key 1-0 (the slot on that page).")
            return
        try:
            vk_from_name(key)
            numbers = {k: float(str(v[k]).replace(",", ".")) for k in ("seconds", "percent", "press_delay",
                                                                         "cooldown", "wait", "presses")}
        except ValueError as exc:
            self.lbl_error.configure(text="Check the key and the numbers (%s)." % exc)
            return
        effects = [e.strip() for e in v["effects"].split(",") if e.strip()]
        if when in ("missing", "ending", "missing_or_ending") and not effects:
            self.lbl_error.configure(text="This condition needs at least one effect name.")
            return
        self.result = normalize_action(dict(numbers, name=v["name"].strip() or key.upper(), enabled=v["enabled"],
                                            key=key, page=page, when=when, combat=combat, effects=effects,
                                            presses=int(numbers["presses"])))
        self.win.destroy()


class BotGui:
    """Control window: status, character, target, monsters, actions (buffs / potions / heals), animus, log."""
    REFRESH_MS = 150
    SEEN_REFRESH = 1.0
    LOG_LINES = 1000

    def __init__(self, bot):
        import tkinter as tk
        from tkinter import ttk, scrolledtext, messagebox, simpledialog
        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.simpledialog = simpledialog
        self.bot = bot
        self.mem = SharedMemory(bot.cfg["shared"]["name"], bot.cfg["shared"]["stale_seconds"],
                                lock=bot.mem.lock, cmd_lock=bot.mem.cmd_lock)   # own reader, SHARED locks
        self.last_seen = 0.0
        self.last_profiles = 0.0
        self.seen_names = []
        self.position = None
        self.effect_names = []
        self.animus_now = []
        self.belt_now = []

        root = self.root = tk.Tk()
        _title = os.environ.get("RF_BOT_TITLE", "Overwolf")
        if ACTIVE_PROFILE != "main":
            _title = "%s - %s" % (_title, ACTIVE_PROFILE)
        root.title(_title)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.minsize(700, 680)
        mono = ("Consolas", 10)

        top = ttk.Frame(root, padding=6)
        top.pack(fill="x")
        prof_row = ttk.Frame(top)
        prof_row.pack(fill="x")
        ttk.Label(prof_row, text="Client profile:").pack(side="left")
        self.var_profile = tk.StringVar(value=ACTIVE_PROFILE)
        self.cmb_profile = ttk.Combobox(prof_row, textvariable=self.var_profile, width=16,
                                        values=list_profiles() or [ACTIVE_PROFILE])
        self.cmb_profile.pack(side="left", padx=(4, 4))
        ttk.Button(prof_row, text="New client", command=self.do_new_client).pack(side="left", padx=(0, 4))
        ttk.Button(prof_row, text="Open profile", command=self.do_switch_profile).pack(side="left", padx=(0, 4))
        ttk.Button(prof_row, text="Bind pid", command=self.choose_client_pid).pack(side="left")
        # one Inject button per profile (inject that profile's module into its client from this window); the
        # row follows the profiles folder (refresh_profiles)
        self.inj_row = ttk.Frame(top)
        self.inj_row.pack(fill="x", pady=(2, 0))
        ttk.Label(self.inj_row, text="Inject profile:").pack(side="left")
        self.inj_buttons = []
        self.profiles_now = None
        self.refresh_profiles()
        self.lbl_game = ttk.Label(top, text="Game: -")
        self.lbl_game.pack(anchor="w")
        self.lbl_mode = ttk.Label(top, text="")
        self.lbl_mode.pack(anchor="w")
        buttons = ttk.Frame(top)
        buttons.pack(fill="x", pady=(4, 0))
        self.btn_toggle = ttk.Button(buttons, text="Start (%s)" % bot.hk_label("toggle"), command=self.toggle)
        self.btn_toggle.pack(side="left")
        ttk.Button(buttons, text="Anchor here (%s)" % bot.hk_label("anchor"),
                   command=lambda: setattr(bot, "pending_anchor", True)).pack(side="left", padx=4)
        ttk.Button(buttons, text="Anchor = my position", command=self.do_anchor_here).pack(side="left", padx=4)
        ttk.Button(buttons, text="Debug dump (%s)" % bot.hk_label("debug"),
                   command=lambda: setattr(bot, "pending_debug", True)).pack(side="left")
        ttk.Button(buttons, text="Record actions (%s)" % bot.hk_label("record"),
                   command=lambda: setattr(bot, "pending_record", True)).pack(side="left", padx=(4, 0))
        ttk.Button(buttons, text="Inject (this client)", command=self.do_map).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Eject", command=self.do_eject).pack(side="left", padx=(4, 0))
        ttk.Button(buttons, text="Remap", command=self.do_remap).pack(side="left", padx=(4, 0))
        self.btn_admin = ttk.Button(buttons, text="Restart as admin", command=self.do_restart_admin)
        if not have_admin():
            self.btn_admin.pack(side="left", padx=(4, 0))
        ttk.Button(buttons, text="Config", command=self.do_open_config).pack(side="left", padx=(4, 0))
        ttk.Button(buttons, text="Debug folder", command=self.do_open_debug).pack(side="left", padx=(4, 0))
        ttk.Button(buttons, text="Module log", command=self.do_open_module_log).pack(side="left", padx=(4, 0))
        ttk.Button(buttons, text="Quit (%s)" % bot.hk_label("quit"), command=self.close).pack(side="right")

        tabs = self.tabs = ttk.Notebook(root)
        tabs.pack(fill="both", expand=False, padx=6)
        main = ttk.Frame(tabs, padding=4)
        tabs.add(main, text="Main")

        char = ttk.LabelFrame(main, text="Character", padding=6)
        char.pack(fill="x")
        self.lbl_char = ttk.Label(char, text="-")
        self.lbl_char.grid(row=0, column=0, columnspan=3, sticky="w")
        self.lbl_pos = ttk.Label(char, text="X -  Y -  Z -", font=mono)
        self.lbl_pos.grid(row=1, column=0, sticky="w")
        ttk.Button(char, text="Copy", width=6, command=self.copy_position).grid(row=1, column=1, padx=4)
        ttk.Button(char, text="Add point", command=self.add_point).grid(row=1, column=2)
        self.lbl_anchor = ttk.Label(char, text="Anchor: -", font=mono)
        self.lbl_anchor.grid(row=2, column=0, columnspan=3, sticky="w")
        self.txt_points = tk.Text(char, height=3, width=60, font=mono)
        self.txt_points.grid(row=3, column=0, columnspan=3, sticky="we", pady=(4, 0))
        char.columnconfigure(0, weight=1)

        target = ttk.LabelFrame(main, text="Target", padding=6)
        target.pack(fill="x", pady=(4, 0))
        self.lbl_target = ttk.Label(target, text="-")
        self.lbl_target.pack(anchor="w")

        dist = ttk.LabelFrame(main, text="Distances (world units)", padding=6)
        dist.pack(fill="x", pady=(4, 0))
        self.spin = {}
        for i, (key, label) in enumerate((("search_radius", "Search radius"), ("leash", "Leash"),
                                          ("near_radius", "Close to you"),
                                          ("max_attack_distance", "Max attack distance (0 = off)"),
                                          ("switch_distance", "Switch target farther than (0 = off)"))):
            row, col = (i // 3) * 2, i % 3
            ttk.Label(dist, text=label).grid(row=row, column=col, sticky="w", padx=(0, 8))
            var = tk.StringVar(value="%g" % self.setting(key))
            ttk.Spinbox(dist, from_=0, to=5000, increment=25, width=8, textvariable=var).grid(
                row=row + 1, column=col, sticky="w", padx=(0, 8))
            self.spin[key] = var
        ttk.Button(dist, text="Save", command=self.save_distances).grid(row=3, column=2, sticky="e")
        ttk.Label(dist, text="Next target: monsters close to you first, then the ones nearest to the anchor "
                             "(yellow marker). A target farther from you than the switch distance is left for "
                             "a monster nearer to you.", wraplength=600).grid(row=4, column=0, columnspan=3,
                                                                              sticky="w")

        loot = ttk.LabelFrame(main, text="Loot (ground drops)", padding=6)
        loot.pack(fill="x", pady=(4, 0))
        self.var_loot_on = tk.BooleanVar(value=bool(bot.loot.get("enabled")))
        self.var_loot_walk = tk.BooleanVar(value=bool(bot.loot.get("walk")))
        self.var_loot_combat = tk.BooleanVar(value=bool(bot.loot.get("in_combat")))
        self.var_loot_mine = tk.BooleanVar(value=bool(bot.loot.get("only_mine", True)))
        ttk.Checkbutton(loot, text="Pick up loot", variable=self.var_loot_on).grid(
            row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Checkbutton(loot, text="Walk to it if farther", variable=self.var_loot_walk).grid(
            row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Checkbutton(loot, text="Also while fighting", variable=self.var_loot_combat).grid(
            row=0, column=2, sticky="w", padx=(0, 12))
        ttk.Checkbutton(loot, text="Only our loot", variable=self.var_loot_mine).grid(
            row=0, column=3, sticky="w", padx=(0, 12))
        ttk.Label(loot, text="Go for loot within").grid(row=1, column=0, sticky="w", padx=(0, 4))
        self.var_loot_radius = tk.StringVar(value="%g" % float(bot.loot.get("radius", 120.0)))
        ttk.Spinbox(loot, from_=0, to=2000, increment=20, width=8, textvariable=self.var_loot_radius).grid(
            row=1, column=1, sticky="w", padx=(0, 12))
        ttk.Label(loot, text="Walk radius").grid(row=1, column=2, sticky="w", padx=(0, 4))
        self.var_loot_walk_radius = tk.StringVar(value="%g" % float(bot.loot.get("walk_radius", 400.0)))
        ttk.Spinbox(loot, from_=0, to=5000, increment=25, width=8, textvariable=self.var_loot_walk_radius).grid(
            row=1, column=3, sticky="w", padx=(0, 12))
        ttk.Button(loot, text="Save", command=self.save_loot).grid(row=1, column=4, sticky="e")
        ttk.Label(loot, text="Loot priority when no monster within").grid(row=2, column=0, columnspan=2, sticky="w")
        self.var_loot_prio = tk.StringVar(value="%g" % float(bot.loot.get("priority_no_mobs_radius", 0.0)))
        ttk.Spinbox(loot, from_=0, to=5000, increment=25, width=8, textvariable=self.var_loot_prio).grid(
            row=2, column=2, sticky="w")
        ttk.Label(loot, text="(0 = off)").grid(row=2, column=3, sticky="w")
        self.var_loot_first = tk.BooleanVar(value=bool(bot.loot.get("first", True)))
        ttk.Checkbutton(loot, text="Loot first (before the next target)", variable=self.var_loot_first).grid(
            row=3, column=0, columnspan=2, sticky="w")
        ttk.Label(loot, text="Wait for the drop after a kill, s").grid(row=3, column=2, sticky="w", padx=(0, 4))
        self.var_loot_wait = tk.StringVar(value="%g" % float(bot.loot.get("after_kill_wait", 2.0)))
        ttk.Spinbox(loot, from_=0, to=10, increment=0.5, width=8, textvariable=self.var_loot_wait).grid(
            row=3, column=3, sticky="w")
        ttk.Label(loot, text="Pick up from (game range)").grid(row=4, column=0, columnspan=2, sticky="w")
        self.var_loot_pickup = tk.StringVar(value="%g" % float(bot.loot.get("pickup_range", 25.0)))
        ttk.Spinbox(loot, from_=1, to=300, increment=5, width=8, textvariable=self.var_loot_pickup).grid(
            row=4, column=2, sticky="w")
        ttk.Label(loot, text="(farther: walks to it first)").grid(row=4, column=3, columnspan=2, sticky="w")
        ttk.Label(loot, text="The game says 'too far': lower 'Pick up from'. 'Go for loot within' = drops the bot "
                             "walks to (also in a fight with 'Also while fighting'), 'Walk radius' = drops it walks "
                             "to when not fighting. Empty item name lists = pick up everything (only_names / "
                             "skip_names in the config file). Monsters that attack you or your animus are fought "
                             "even with 'Loot first'.", wraplength=600).grid(row=5, column=0, columnspan=5,
                                                                             sticky="w")

        mobs = ttk.Frame(tabs, padding=6)
        tabs.add(mobs, text="Monsters")
        self.var_any = tk.BooleanVar(value=bool(bot.tc.get("attack_any", True)))
        ttk.Checkbutton(mobs, text="Attack any monsters (ignore the attack list below)", variable=self.var_any,
                        command=self.save_attack_any).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(mobs, text="Monsters to attack: empty list = every monster; a name matches when it contains "
                             "the text.").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 4))
        ttk.Label(mobs, text="Around you").grid(row=2, column=0, sticky="w")
        ttk.Label(mobs, text="Attack list").grid(row=2, column=2, sticky="w")
        self.lst_seen = tk.Listbox(mobs, height=9, selectmode="extended", exportselection=False, font=mono)
        self.lst_seen.grid(row=3, column=0, sticky="nsew")
        middle = ttk.Frame(mobs)
        middle.grid(row=3, column=1, padx=4)
        ttk.Button(middle, text="Add >", command=self.add_selected).pack(fill="x")
        ttk.Button(middle, text="< Remove", command=self.remove_selected).pack(fill="x", pady=2)
        ttk.Button(middle, text="Clear", command=self.clear_list).pack(fill="x")
        self.lst_attack = tk.Listbox(mobs, height=9, selectmode="extended", exportselection=False, font=mono)
        self.lst_attack.grid(row=3, column=2, sticky="nsew")
        entry_row = ttk.Frame(mobs)
        entry_row.grid(row=4, column=0, columnspan=3, sticky="we", pady=(4, 0))
        self.ent_name = ttk.Entry(entry_row)
        self.ent_name.pack(side="left", fill="x", expand=True)
        ttk.Button(entry_row, text="Add name", command=self.add_typed).pack(side="left", padx=(4, 0))
        self.var_untouched = tk.BooleanVar(value=bool(bot.tc["prefer_untouched"]))
        ttk.Checkbutton(mobs, text="Monsters someone else fights (not yours, lost HP or attack another player): "
                                   "attack them last", variable=self.var_untouched,
                        command=self.save_untouched).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        mobs.columnconfigure(0, weight=1)
        mobs.columnconfigure(2, weight=1)

        acts = ttk.Frame(tabs, padding=6)
        tabs.add(acts, text="Actions")
        ttk.Label(acts, text="Buffs, potions, heals: checked top to bottom. Keys are belt keys 1-0 (used through "
                             "the game); with a belt page (1-5) the slot of that page is used, "
                             "whatever page the belt shows.", wraplength=580).pack(anchor="w")
        cols = ("on", "name", "key", "when", "detail", "combat", "cooldown")
        self.tree_actions = ttk.Treeview(acts, columns=cols, show="headings", height=8, selectmode="browse")
        for c, label, width in (("on", "On", 34), ("name", "Name", 110), ("key", "Key", 56),
                                ("when", "When", 160), ("detail", "Effects / value", 160),
                                ("combat", "Combat", 100), ("cooldown", "Cooldown", 70)):
            self.tree_actions.heading(c, text=label)
            self.tree_actions.column(c, width=width, stretch=c == "detail")
        self.tree_actions.pack(fill="x", pady=4)
        self.tree_actions.bind("<Double-1>", lambda _e: self.edit_action())
        bar = ttk.Frame(acts)
        bar.pack(fill="x")
        for text, cmd in (("Add", self.add_action), ("Edit", self.edit_action), ("Remove", self.remove_action),
                          ("Up", lambda: self.move_action(-1)), ("Down", lambda: self.move_action(1)),
                          ("On / Off", self.toggle_action)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 4))
        ttk.Label(acts, text="Effects on you now (double click: new action that keeps it up)").pack(
            anchor="w", pady=(8, 0))
        self.lst_effects = tk.Listbox(acts, height=5, exportselection=False, font=mono)
        self.lst_effects.pack(fill="x")
        self.lst_effects.bind("<Double-1>", lambda _e: self.action_from_effect())

        rot = ttk.Frame(tabs, padding=6)
        tabs.add(rot, text="Rotation")
        ttk.Label(rot, text="Combat rotation: while you have a live monster target the bot presses these belt "
                            "slots top to bottom (most important first) - the first one whose skill is ready, "
                            "then waits. '5' = slot 5 of the page the belt shows, 'p3:5' = slot 5 of page 3. "
                            "Rotation off, empty list or nothing ready = the plain attack key.",
                  wraplength=600).grid(row=0, column=0, columnspan=3, sticky="w")
        head = ttk.Frame(rot)
        head.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.var_rot_on = tk.BooleanVar(value=bool(bot.rot["enabled"]))
        ttk.Checkbutton(head, text="Rotation on", variable=self.var_rot_on).pack(side="left")
        ttk.Label(head, text="  Interval, s").pack(side="left")
        self.var_rot_int = tk.StringVar(value="%g" % float(bot.rot["interval_seconds"]))
        ttk.Spinbox(head, from_=0.2, to=10, increment=0.1, width=6, textvariable=self.var_rot_int).pack(side="left")
        self.var_rot_ready = tk.BooleanVar(value=bool(bot.rot["only_ready"]))
        ttk.Checkbutton(head, text="  only when the skill is ready (cooldown)",
                        variable=self.var_rot_ready).pack(side="left")
        ttk.Button(head, text="Save", command=self.save_rotation).pack(side="left", padx=6)
        ttk.Label(rot, text="Rotation (top = first)").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(rot, text="Belt now (double click adds)").grid(row=2, column=2, sticky="w", pady=(6, 0))
        self.lst_rot = tk.Listbox(rot, height=10, selectmode="extended", exportselection=False, font=mono)
        self.lst_rot.grid(row=3, column=0, sticky="nsew")
        rmid = ttk.Frame(rot)
        rmid.grid(row=3, column=1, padx=4)
        ttk.Button(rmid, text="Add >", command=self.rot_add_typed).pack(fill="x")
        ttk.Button(rmid, text="< Remove", command=self.rot_remove).pack(fill="x", pady=2)
        ttk.Button(rmid, text="Up", command=lambda: self.rot_move(-1)).pack(fill="x", pady=2)
        ttk.Button(rmid, text="Down", command=lambda: self.rot_move(1)).pack(fill="x")
        self.lst_rot_belt = tk.Listbox(rot, height=10, exportselection=False, font=mono)
        self.lst_rot_belt.grid(row=3, column=2, sticky="nsew")
        self.lst_rot_belt.bind("<Double-1>", lambda _e: self.rot_add_from_belt())
        erow = ttk.Frame(rot)
        erow.grid(row=4, column=0, columnspan=3, sticky="we", pady=(4, 0))
        ttk.Label(erow, text="Add slot (5 or 3:5):").pack(side="left")
        self.ent_rot = ttk.Entry(erow, width=6)
        self.ent_rot.pack(side="left", padx=4)
        ttk.Button(erow, text="Add", command=self.rot_add_typed).pack(side="left")
        rot.columnconfigure(0, weight=1)
        rot.columnconfigure(2, weight=1)
        self.refresh_rotation()

        anim = ttk.Frame(tabs, padding=6)
        tabs.add(anim, text="Animus")
        self.var_anim_on = tk.BooleanVar(value=bool(bot.anc["enabled"]))
        self.var_anim_min = tk.StringVar(value="%g" % round(float(bot.anc["summon_min_hp"]) * 100))
        head = ttk.Frame(anim)
        head.pack(fill="x")
        ttk.Checkbutton(head, text="Summon automatically", variable=self.var_anim_on).pack(side="left")
        ttk.Label(head, text="  min HP to summon, %").pack(side="left")
        ttk.Spinbox(head, from_=0, to=100, increment=5, width=6, textvariable=self.var_anim_min).pack(side="left")
        ttk.Button(head, text="Save", command=self.save_animus).pack(side="left", padx=6)
        ttk.Label(anim, text="Your animus (from the game; HP regenerates while they rest)").pack(anchor="w",
                                                                                              pady=(6, 0))
        self.tree_animus = ttk.Treeview(anim, columns=("name", "on", "hp", "rate", "state"), show="headings",
                                        height=5, selectmode="browse")
        for c, label, width in (("name", "Animus", 150), ("on", "Summon", 70), ("hp", "HP", 110),
                                ("rate", "%", 50), ("state", "State", 170)):
            self.tree_animus.heading(c, text=label)
            self.tree_animus.column(c, width=width, stretch=c == "state")
        self.tree_animus.pack(fill="x")
        self.tree_animus.bind("<Double-1>", lambda _e: self.toggle_animus())
        abar = ttk.Frame(anim)
        abar.pack(fill="x", pady=(2, 0))
        ttk.Button(abar, text="Summon on / off", command=self.toggle_animus).pack(side="left")
        ttk.Label(abar, text="  (double click a row too: an animus that is off is never summoned)").pack(side="left")
        ttk.Label(anim, text="Summon order (first one with enough HP; empty = the one with the most HP)").pack(
            anchor="w", pady=(6, 0))
        order_row = ttk.Frame(anim)
        order_row.pack(fill="x")
        self.lst_order = tk.Listbox(order_row, height=5, exportselection=False, font=mono)
        self.lst_order.pack(side="left", fill="x", expand=True)
        obar = ttk.Frame(order_row)
        obar.pack(side="left", padx=4)
        for text, cmd in (("Add selected", self.add_order), ("Remove", self.remove_order),
                          ("Up", lambda: self.move_order(-1)), ("Down", lambda: self.move_order(1))):
            ttk.Button(obar, text=text, command=cmd).pack(fill="x", pady=1)
        rev = ttk.LabelFrame(anim, text="Animus died: heal it, reset the summon cooldown, summon it",
                             padding=4)
        rev.pack(fill="x", pady=(8, 0))
        self.var_heal = tk.StringVar(value=str(bot.anc["heal_skill"]))
        self.var_reset = tk.StringVar(value=str(bot.anc["reset_skill"]))
        self.var_reset_after = tk.BooleanVar(value=bool(bot.anc["reset_after_heal"]))
        self.var_heal_recalled = tk.BooleanVar(value=bool(bot.anc["heal_recalled"]))
        ttk.Label(rev, text="Heal skill").grid(row=0, column=0, sticky="w")
        self.cmb_heal = ttk.Combobox(rev, textvariable=self.var_heal, width=26)
        self.cmb_heal.grid(row=0, column=1, sticky="w", padx=4, pady=1)
        self.lbl_heal = ttk.Label(rev, text="")
        self.lbl_heal.grid(row=0, column=2, sticky="w")
        ttk.Label(rev, text="Summon reset skill").grid(row=1, column=0, sticky="w")
        self.cmb_reset = ttk.Combobox(rev, textvariable=self.var_reset, width=26)
        self.cmb_reset.grid(row=1, column=1, sticky="w", padx=4, pady=1)
        self.lbl_reset = ttk.Label(rev, text="")
        self.lbl_reset.grid(row=1, column=2, sticky="w")
        ttk.Checkbutton(rev, text="use the reset right after the heal (a refused summon uses it anyway)",
                        variable=self.var_reset_after).grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(rev, text="also heal an animus that was recalled with too little HP (not only a dead one)",
                        variable=self.var_heal_recalled).grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Button(rev, text="Save", command=self.save_revive).grid(row=4, column=0, sticky="w", pady=(4, 0))
        rev.columnconfigure(2, weight=1)

        beltf = ttk.Frame(tabs, padding=6)
        tabs.add(beltf, text="Belt")
        ttk.Label(beltf, text="Your belt, all 5 pages: skills and forces with the game's own check "
                              "and cooldown. The animus heal / reset skills are found here by name, on any page.",
                  wraplength=580).pack(anchor="w")
        self.tree_belt = ttk.Treeview(beltf, columns=("page", "key", "name", "kind", "state"), show="headings",
                                      height=16, selectmode="browse")
        for c, label, width in (("page", "Page", 44), ("key", "Key", 40), ("name", "Name", 210),
                                ("kind", "Kind", 100), ("state", "State", 170)):
            self.tree_belt.heading(c, text=label)
            self.tree_belt.column(c, width=width, stretch=c == "state")
        self.tree_belt.pack(fill="both", expand=True, pady=4)

        self.txt_log = scrolledtext.ScrolledText(root, height=10, font=mono, state="disabled")
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)

        self.fill_attack_list()
        self.fill_actions()
        self.fill_order()
        root.after(self.REFRESH_MS, self.refresh)

    # ---- settings in the config -------------------------------------------

    def setting(self, key):
        b = self.bot
        if key == "search_radius":
            return float(b.tc["search_radius"])
        if key == "leash":
            return float(b.ac["leash"])
        if key == "near_radius":
            return float(b.tc["near_radius"])
        if key == "switch_distance":
            return float(b.cc["switch_distance"])
        return float(b.cc["max_attack_distance"])

    def save_config(self):
        write_json(CFG_PATH, self.bot.cfg)

    def save_untouched(self):
        self.bot.tc["prefer_untouched"] = bool(self.var_untouched.get())
        self.save_config()
        log("Monsters someone else fights: %s." % ("attacked last" if self.bot.tc["prefer_untouched"]
                                                   else "same priority as the others"))

    def save_attack_any(self):
        self.bot.tc["attack_any"] = bool(self.var_any.get())
        self.save_config()
        log("Attack any monsters: %s." % ("on (the attack list is ignored)" if self.bot.tc["attack_any"]
                                          else "off (only names in the attack list)"))

    def save_distances(self):
        b = self.bot
        try:
            values = {key: max(0.0, float(var.get().replace(",", "."))) for key, var in self.spin.items()}
        except ValueError:
            log("Distances: enter numbers.")
            return
        b.tc["search_radius"] = values["search_radius"]
        b.ac["leash"] = values["leash"]
        b.tc["near_radius"] = values["near_radius"]
        b.cc["max_attack_distance"] = values["max_attack_distance"]
        b.cc["switch_distance"] = values["switch_distance"]
        self.save_config()
        log("Distances saved: search radius %.0f, leash %.0f, close to you %.0f, max attack distance %.0f, "
            "switch target farther than %.0f." % (values["search_radius"], values["leash"], values["near_radius"],
                                                   values["max_attack_distance"], values["switch_distance"]))

    def save_loot(self):
        lc = self.bot.loot
        lc["enabled"] = bool(self.var_loot_on.get())
        lc["walk"] = bool(self.var_loot_walk.get())
        lc["in_combat"] = bool(self.var_loot_combat.get())
        lc["only_mine"] = bool(self.var_loot_mine.get())
        lc["first"] = bool(self.var_loot_first.get())
        try:
            lc["radius"] = max(0.0, float(self.var_loot_radius.get().replace(",", ".")))
            lc["pickup_range"] = max(1.0, float(self.var_loot_pickup.get().replace(",", ".")))
            lc["walk_radius"] = max(0.0, float(self.var_loot_walk_radius.get().replace(",", ".")))
            lc["priority_no_mobs_radius"] = max(0.0, float(self.var_loot_prio.get().replace(",", ".")))
            lc["after_kill_wait"] = max(0.0, float(self.var_loot_wait.get().replace(",", ".")))
        except ValueError:
            log("Loot: enter numbers for the radii and the wait.")
            return
        self.save_config()
        log("Loot: %s, walk: %s, in combat: %s, only our loot: %s, loot first: %s (wait %.1f s after a kill), "
            "pick up from %.0f, go for loot within %.0f, walk radius %.0f, priority when no monster within %.0f."
            % ("on" if lc["enabled"] else "off", "on" if lc["walk"] else "off",
               "on" if lc["in_combat"] else "off", "on" if lc["only_mine"] else "off",
               "on" if lc["first"] else "off", lc["after_kill_wait"], lc["pickup_range"],
               lc["radius"], lc["walk_radius"], lc["priority_no_mobs_radius"]))

    # ---- rotation --------------------------------------------------------

    def save_rotation(self):
        rot = self.bot.rot
        rot["enabled"] = bool(self.var_rot_on.get())
        rot["only_ready"] = bool(self.var_rot_ready.get())
        try:
            rot["interval_seconds"] = max(0.2, float(self.var_rot_int.get().replace(",", ".")))
        except ValueError:
            pass
        self.save_config()
        log("Rotation: %s, interval %.1f s, only-ready %s, slots %s." % (
            "on" if rot["enabled"] else "off", rot["interval_seconds"],
            "on" if rot["only_ready"] else "off",
            ", ".join(rotation_label(r) for r in rot["slots"]) or "(attack key)"))

    # ---- module eject / map ----------------------------------------------

    def do_eject(self):
        if self.messagebox.askyesno("Eject module", "Remove the module from the game memory?\n"
                                                    "The bot must be re-mapped after this (game restart or "
                                                    "run_bot.py)."):
            self.bot.running = False   # pause: a tick command would otherwise race the eject command block
            log("Bot PAUSED for eject.")
            self.bot.eject_module()

    def do_map(self):
        """Inject this profile's module into its game client (its bound pid)."""
        self._inject_profile(ACTIVE_PROFILE)

    def do_remap(self):
        """Eject (unhook + free) then map fresh, in one click: what you need after a rebuild or a stale module
        (after an eject the idle module no longer receives commands, so a plain Inject would double-map)."""
        if not self.messagebox.askyesno("Remap module", "Rebuild the module in the game?\n\n"
                                                        "The hooks are removed, the memory freed, then the "
                                                        "module is mapped fresh."):
            return
        self.bot.running = False   # pause: a tick command would otherwise race the eject command block
        log("Bot PAUSED for remap.")
        # unhook + free the current module if one is present (also when it no longer answers: it was ejected
        # before and its hooks are gone). The slots-clean check inside still gates the free.
        self.bot.eject_module(force_free=True)
        self._inject_profile(ACTIVE_PROFILE)

    def _inject_profile(self, prof):
        """Inject a specific profile's module into its bound client (works for any profile, not just this
        window's), so each client can be injected with its own button."""
        if _mm is None:
            self.messagebox.showerror("Inject", "manualmap not available: %s" % _mm_error)
            return
        if not have_admin():
            if self.messagebox.askyesno("Not elevated", "Injecting needs administrator rights.\n\n"
                                                        "Restart this window elevated now? (UAC appears)"):
                self.relaunch_admin()
            return
        dll = profile_dll(prof)
        pid = profile_target_pid(prof)
        try:
            pid, base, reused = find_and_map(dll=dll, prefer_pid=pid)
        except Exception as e:
            self.messagebox.showerror("Inject '%s'" % prof, "%s%s" % (
                "" if isinstance(e, RuntimeError) else "%s: " % type(e).__name__, e))
            return
        set_profile_target_pid(prof, pid)
        log("Inject '%s': %s into game pid %d (base 0x%08X)."
            % (prof, "already mapped, reused" if reused else "mapped", pid, base))

    def refresh_profiles(self):
        """The Inject buttons and the profile list follow the profiles folder (new profiles show up)."""
        profiles = list_profiles() or [ACTIVE_PROFILE]
        if profiles == self.profiles_now:
            return
        self.profiles_now = profiles
        for b in self.inj_buttons:
            b.destroy()
        self.inj_buttons = []
        for prof in profiles:
            b = self.ttk.Button(self.inj_row, text=prof, width=10, command=lambda p=prof: self._inject_profile(p))
            b.pack(side="left", padx=(4, 0))
            self.inj_buttons.append(b)
        self.cmb_profile.configure(values=profiles)

    def choose_client_pid(self):
        """Pick which running game client this profile should bind to (when several are open)."""
        if _mm is None:
            self.messagebox.showerror("Client", "manualmap not available: %s" % _mm_error)
            return
        pids = _mm.find_game_pids()
        if not pids:
            self.messagebox.showinfo("Client", "No game client is running.")
            return
        cur = profile_target_pid(ACTIVE_PROFILE)
        # show the game path + its hwid profile/bot profile, so the right window is obvious
        options = []
        for p in pids:
            gp = hwid_game_profile(p)
            tag = ""
            if gp:
                tag = " [game %s%s, bot %s]" % (gp.get("id"), " " + str(gp.get("label") or ""),
                                                gp.get("bot_profile") or "-")
            options.append("%d%s%s" % (p, "  (current)" if p == cur else "",
                                       "  " + (process_image_path(p) or "?") + tag))
        choice = self.simpledialog.askstring("Bind client",
                                             "Game clients (pid, path, hwid profile, bot profile):\n%s\n\n"
                                             "Enter the pid this profile should use:" % "\n".join(options),
                                             initialvalue=str(cur or pids[0]))
        if not choice:
            return
        try:
            pid = int(choice.strip().split()[0])
        except ValueError:
            self.messagebox.showerror("Client", "Not a pid: %s" % choice)
            return
        set_profile_target_pid(ACTIVE_PROFILE, pid)
        gp = hwid_game_profile(pid)
        want = (gp or {}).get("bot_profile")
        log("Profile '%s' bound to game pid %d%s. Press Inject."
            % (ACTIVE_PROFILE, pid, " (game %s)" % gp.get("id") if gp else ""))
        if want and want != ACTIVE_PROFILE:
            log("  note: game profile %s is served by bot profile '%s', not '%s'; "
                "start rfbot.py --profile %s for its shared memory."
                % (gp.get("id"), want, ACTIVE_PROFILE, want))

    def relaunch_admin(self):
        """Close this window and start a fresh elevated copy of the bot (stays open when UAC is declined)."""
        args = [a for a in sys.argv[1:] if a not in ("--no-elevate", "--elevated")]
        if relaunch_elevated(args):
            self.close()

    def do_restart_admin(self):
        if self.messagebox.askyesno("Restart as admin", "Close this window and start an elevated copy "
                                                        "(UAC prompt)?"):
            self.relaunch_admin()

    def do_switch_profile(self):
        """Start a new bot instance for the chosen/new client profile (each profile = own config/dll/shm)."""
        name = (self.var_profile.get() or "").strip()
        if not name:
            return
        if not valid_profile_name(name):
            self.messagebox.showerror("Switch client", "Invalid profile name '%s'.\nUse ASCII letters, digits, "
                                                       "'.', '_', '-' only." % name)
            return
        if name == ACTIVE_PROFILE and name in list_profiles():
            if not self.messagebox.askyesno("Switch client", "Restart the bot for profile '%s'?" % name):
                return
        new = name not in list_profiles()
        try:
            create_profile(name, clone_from=None if new else ACTIVE_PROFILE)
        except Exception as e:
            self.messagebox.showerror("Switch client", "Cannot create profile '%s': %s" % (name, e))
            return
        log("Starting profile '%s' (%s)." % (name, "new" if new else "existing"))
        args = strip_args(sys.argv[1:]) + ["--profile", name]
        if have_admin():
            args.append("--elevated")      # already elevated -> the new one inherits it, no second UAC prompt
        if relaunch_into(args):
            self.close()
        else:
            self.messagebox.showerror("Switch client", "Could not start the bot for profile '%s' (see the log)."
                                      % name)

    def do_new_client(self):
        name = self.simpledialog.askstring("New client profile", "Profile name (e.g. bot2):")
        if not name:
            return
        name = name.strip()
        if not valid_profile_name(name):
            self.messagebox.showerror("New client", "Invalid profile name '%s'.\nUse ASCII letters, digits, "
                                                    "'.', '_', '-' only." % name)
            return
        self.var_profile.set(name)
        self.do_switch_profile()       # this window closes only when the new one has started

    def _open_path(self, path):
        try:
            os.startfile(path)                       # opens with the default app / Explorer
        except Exception as e:
            self.messagebox.showerror("Open", "Cannot open %s: %s" % (path, e))

    def do_open_config(self):
        self._open_path(CFG_PATH)

    def do_open_debug(self):
        path = os.path.join(HERE, DEBUG_DIR)
        os.makedirs(path, exist_ok=True)
        self._open_path(path)

    def do_open_module_log(self):
        path = os.path.join(HERE, "build", "BotCore.log")
        if not os.path.isfile(path):
            self.messagebox.showinfo("Module log", "No %s yet (is the module mapped?)" % path)
            return
        self._open_path(path)

    @staticmethod
    def fill_listbox(lst, rows):
        """Refill a Listbox only when its rows changed, keeping the selection (a refresh must not drop it)."""
        if list(lst.get(0, "end")) == rows:
            return
        sel = [i for i in lst.curselection() if i < len(rows)]
        lst.delete(0, "end")
        for row in rows:
            lst.insert("end", row)
        for i in sel:
            lst.selection_set(i)

    def refresh_rotation(self):
        if not hasattr(self, "lst_rot"):
            return
        belt = self.mem.belt() or []
        shown = self.bot.rotation_slots(belt, self.mem.belt_page())
        rows = []
        for r in self.bot.rot["slots"]:
            b = self.bot.rotation_entry_slot(r, belt, shown)
            rows.append("%-6s %s" % (rotation_label(r), b["name"] if b else "(empty)"))
        self.fill_listbox(self.lst_rot, rows)
        self.rot_belt_items = [(b["page"], BELT_KEYS.index(b["key"]) + 1) for b in belt]
        self.fill_listbox(self.lst_rot_belt, [
            "p%d %s  %s%s" % (b["page"], b["key"], b["name"],
                              "  [cd %.1fs]" % b.get("left", 0.0) if b.get("ready", 2) == -1 else "")
            for b in belt])

    def set_rotation_slots(self, slots, select=None):
        """Save a new rotation list (one assignment: the bot thread sees the old or the new list)."""
        self.bot.rot["slots"] = slots
        self.save_config()
        self.refresh_rotation()
        if select:
            self.lst_rot.selection_clear(0, "end")
            for i in select:
                if 0 <= i < len(slots):
                    self.lst_rot.selection_set(i)

    def rot_add(self, entry):
        if entry is None or entry in self.bot.rot["slots"]:
            return
        self.set_rotation_slots(list(self.bot.rot["slots"]) + [entry])
        log("Rotation: %s." % ", ".join(rotation_label(r) for r in self.bot.rot["slots"]))

    def rot_add_typed(self):
        entry = rotation_entry(self.ent_rot.get().strip())
        if entry is None:
            log("Rotation: enter a slot 1..10 (page the belt shows) or page:slot, e.g. 3:5.")
            return
        self.ent_rot.delete(0, "end")
        self.rot_add(entry)

    def rot_add_from_belt(self):
        sel = self.lst_rot_belt.curselection()
        items = getattr(self, "rot_belt_items", [])
        if sel and sel[0] < len(items):
            page, slot = items[sel[0]]
            self.rot_add({"page": page, "slot": slot})    # that page: what you clicked is what is pressed

    def rot_remove(self):
        drop = set(self.lst_rot.curselection())
        self.set_rotation_slots([r for i, r in enumerate(self.bot.rot["slots"]) if i not in drop])

    def rot_move(self, step):
        slots = list(self.bot.rot["slots"])
        sel = list(self.lst_rot.curselection())
        moved = []
        for i in (sel if step < 0 else list(reversed(sel))):
            j = i + step
            if 0 <= j < len(slots) and j not in moved:
                slots[i], slots[j] = slots[j], slots[i]
                moved.append(j)
            else:
                moved.append(i)
        self.set_rotation_slots(slots, moved)

    # ---- monster list -----------------------------------------------------

    def attack_list(self):
        return self.bot.tc["only_names"]

    def fill_attack_list(self):
        self.lst_attack.delete(0, "end")
        for name in self.attack_list():
            self.lst_attack.insert("end", name)

    def set_attack_list(self, names, message):
        self.bot.tc["only_names"] = names        # one assignment: the bot thread sees the old or the new list
        self.save_config()
        self.fill_attack_list()
        log(message)

    def add_names(self, names):
        lst = list(self.attack_list())
        added = [n for n in names if n and n not in lst]
        if added:
            self.set_attack_list(lst + added, "Attack list: %s." % ", ".join(lst + added))

    def add_selected(self):
        self.add_names([self.seen_names[i] for i in self.lst_seen.curselection() if i < len(self.seen_names)])

    def add_typed(self):
        self.add_names([self.ent_name.get().strip()])
        self.ent_name.delete(0, "end")

    def remove_selected(self):
        drop = set(self.lst_attack.curselection())
        lst = [n for i, n in enumerate(self.attack_list()) if i not in drop]
        self.set_attack_list(lst, "Attack list: %s." % (", ".join(lst) or "empty, every monster is attacked"))

    def clear_list(self):
        self.set_attack_list([], "Attack list cleared: every monster is attacked.")

    def refresh_seen(self, snap):
        """Monsters around you, one line per name: count and nearest distance."""
        av = snap.avatar
        seen = {}
        for e in snap.entities:
            if e.type == OBJ_MONSTER and e.alive:
                count, nearest, prio = seen.get(e.name, (0, None, 2))
                d = e.dist(av.x, av.z)
                seen[e.name] = (count + 1, d if nearest is None else min(nearest, d),
                                min(prio, self.bot.priority(e, snap)))
        names = sorted(seen, key=lambda n: (seen[n][2], seen[n][1]))
        selected = {self.seen_names[i] for i in self.lst_seen.curselection() if i < len(self.seen_names)}
        self.seen_names = names
        self.lst_seen.delete(0, "end")
        for i, name in enumerate(names):
            count, nearest, prio = seen[name]
            mark = {0: "  << animus", 1: "  << you"}.get(prio, "")
            self.lst_seen.insert("end", "%s  x%d  %.0f%s" % (name, count, nearest, mark))
            if name in selected:
                self.lst_seen.selection_set(i)

    # ---- actions ------------------------------------------------------------

    def actions(self):
        return self.bot.cfg["actions"]

    def set_actions(self, acts, message):
        self.bot.cfg["actions"] = acts           # one assignment: the bot thread sees the old or the new list
        self.save_config()
        self.fill_actions()
        log(message)

    def fill_actions(self, select=None):
        tree = self.tree_actions
        tree.delete(*tree.get_children())
        for i, a in enumerate(self.actions()):
            tree.insert("", "end", iid=str(i), values=("on" if a["enabled"] else "off", a["name"], action_key_label(a),
                                                       WHEN_LABELS[a["when"]], action_detail(a),
                                                       COMBAT_LABELS[a["combat"]], "%gs" % a["cooldown"]))
        if select is not None and 0 <= select < len(self.actions()):
            tree.selection_set(str(select))
            tree.see(str(select))

    def selected_action(self):
        sel = self.tree_actions.selection()
        return int(sel[0]) if sel else None

    def add_action(self, template=None):
        dlg = ActionDialog(self.root, template or {"name": "", "key": "", "when": "missing"}, self.effect_names)
        if dlg.result:
            self.set_actions(self.actions() + [dlg.result], "Action added: %s." % dlg.result["name"])
            self.fill_actions(len(self.actions()) - 1)

    def edit_action(self):
        i = self.selected_action()
        if i is None:
            return
        dlg = ActionDialog(self.root, self.actions()[i], self.effect_names)
        if dlg.result:
            acts = list(self.actions())
            acts[i] = dlg.result
            self.set_actions(acts, "Action changed: %s." % dlg.result["name"])
            self.fill_actions(i)

    def remove_action(self):
        i = self.selected_action()
        if i is not None:
            acts = list(self.actions())
            gone = acts.pop(i)
            self.set_actions(acts, "Action removed: %s." % gone["name"])

    def move_action(self, step):
        i = self.selected_action()
        if i is None or not 0 <= i + step < len(self.actions()):
            return
        acts = list(self.actions())
        acts[i], acts[i + step] = acts[i + step], acts[i]
        self.set_actions(acts, "Action order: %s." % ", ".join(a["name"] for a in acts))
        self.fill_actions(i + step)

    def toggle_action(self):
        i = self.selected_action()
        if i is None:
            return
        acts = list(self.actions())
        acts[i] = dict(acts[i], enabled=not acts[i]["enabled"])
        self.set_actions(acts, "Action %s: %s." % (acts[i]["name"], "on" if acts[i]["enabled"] else "off"))
        self.fill_actions(i)

    def action_from_effect(self):
        sel = self.lst_effects.curselection()
        if sel and sel[0] < len(self.effect_names):
            name = self.effect_names[sel[0]].rsplit("  (", 1)[0]
            self.add_action({"name": name, "key": "", "when": "missing", "effects": [name]})

    def refresh_effects(self, snap):
        """Effects on you now, for the action editor."""
        effects = self.bot.effects_now(snap)
        names = ["%s  (%s)" % (n, "%.0fs" % r if r < 1e8 else "no timer") for n, r in sorted(effects.items())]
        if names != self.effect_names:
            self.effect_names = names
            self.lst_effects.delete(0, "end")
            for n in names:
                self.lst_effects.insert("end", n)

    # ---- animus -------------------------------------------------------------

    def fill_order(self):
        self.lst_order.delete(0, "end")
        for n in self.bot.anc["order"]:
            self.lst_order.insert("end", n)

    def set_order(self, order, select=None):
        self.bot.anc["order"] = order
        self.save_config()
        self.fill_order()
        if select is not None and 0 <= select < len(order):
            self.lst_order.selection_set(select)
        log("Animus summon order: %s." % (", ".join(order) or "empty (the one with the most HP)"))

    def add_order(self):
        sel = self.tree_animus.selection()
        if not sel:
            return
        name = self.tree_animus.item(sel[0], "values")[0]
        order = list(self.bot.anc["order"])
        if name and name not in order:
            self.set_order(order + [name], len(order))

    def remove_order(self):
        sel = self.lst_order.curselection()
        if sel:
            order = list(self.bot.anc["order"])
            del order[sel[0]]
            self.set_order(order)

    def move_order(self, step):
        sel = self.lst_order.curselection()
        order = list(self.bot.anc["order"])
        if not sel or not 0 <= sel[0] + step < len(order):
            return
        i = sel[0]
        order[i], order[i + step] = order[i + step], order[i]
        self.set_order(order, i + step)

    def save_animus(self):
        try:
            rate = max(0.0, min(100.0, float(self.var_anim_min.get().replace(",", ".")))) / 100.0
        except ValueError:
            log("Animus: min HP to summon must be a number.")
            return
        self.bot.anc["summon_min_hp"] = rate
        self.bot.anc["enabled"] = bool(self.var_anim_on.get())
        self.save_config()
        log("Animus: summon automatically %s, min HP %d%%." % ("on" if self.bot.anc["enabled"] else "off",
                                                               round(rate * 100)))

    def toggle_animus(self):
        """Switch the selected animus off (never summoned) or back on."""
        sel = self.tree_animus.selection()
        if not sel:
            return
        name = self.tree_animus.item(sel[0], "values")[0]
        if not name or name.startswith("("):
            return
        never = [n for n in self.bot.anc["never"] if str(n).strip().lower() != name.lower()]
        on = len(never) != len(self.bot.anc["never"])     # it was off: switch it on
        if not on:
            never.append(name)
        self.bot.anc["never"] = never
        self.save_config()
        self.animus_now = []                              # redraw the table now
        self.refresh_animus()
        if sel[0] in self.tree_animus.get_children():
            self.tree_animus.selection_set(sel[0])
        log("Animus %s: %s." % (name, "summoned again when needed" if on else "OFF, never summoned"))

    def refresh_animus(self):
        animus = self.mem.animus_list()
        rows = []
        if animus is None:
            rows.append(("(The module cannot read it)", "", "", "", ""))
        else:
            need = float(self.bot.anc["summon_min_hp"])
            for it in animus:
                allowed = self.bot.animus_allowed(it["name"])
                if it["summoned"]:
                    state = "summoned"
                elif not allowed:
                    state = "off: never summoned"
                else:
                    state = "can be summoned" if it["max_hp"] and it["rate"] >= need else "resting, HP too low"
                rows.append((it["name"], "yes" if allowed else "no", "%d / %d" % (it["hp"], it["max_hp"]),
                             "%d" % round(it["rate"] * 100), state))
        if rows != self.animus_now:
            self.animus_now = rows
            tree = self.tree_animus
            sel = tree.selection()
            tree.delete(*tree.get_children())
            for i, row in enumerate(rows):
                tree.insert("", "end", iid=str(i), values=row)
            if sel and sel[0] in tree.get_children():
                tree.selection_set(sel[0])

    def save_revive(self):
        a = self.bot.anc
        a["heal_skill"] = self.var_heal.get().strip()
        a["reset_skill"] = self.var_reset.get().strip()
        a["reset_after_heal"] = bool(self.var_reset_after.get())
        a["heal_recalled"] = bool(self.var_heal_recalled.get())
        self.save_config()
        log("Animus revive: heal skill %s, summon reset skill %s (%s), heal %s." % (
            "'%s'" % a["heal_skill"] if a["heal_skill"] else "off", "'%s'" % a["reset_skill"] if a["reset_skill"]
            else "off", "right after the heal" if a["reset_after_heal"] else "only when a summon is refused",
            "dead and recalled animus" if a["heal_recalled"] else "dead animus only"))

    def refresh_belt(self):
        """Belt tab, the skill lists and the heal / reset states of the Animus tab."""
        belt = self.mem.belt()
        if belt is None:
            rows = [("", "", "(The module cannot read it)", "", "")]
        else:
            rows = [(str(s["page"]), s["key"], s["name"], BELT_KIND_NAMES.get(s["kind"], "?"), belt_state_text(s))
                    for s in belt] or [("", "", "(the belt is empty)", "", "")]
        if rows != self.belt_now:
            self.belt_now = rows
            tree = self.tree_belt
            tree.delete(*tree.get_children())
            for i, row in enumerate(rows):
                tree.insert("", "end", iid=str(i), values=row)
        names = []
        for s in belt or []:
            if s["kind"] == BELT_SF and s["name"] and s["name"] not in names:
                names.append(s["name"])
        for cmb, var, lbl in ((self.cmb_heal, self.var_heal, self.lbl_heal),
                              (self.cmb_reset, self.var_reset, self.lbl_reset)):
            if list(cmb.cget("values") or ()) != [""] + names:
                cmb.configure(values=[""] + names)
            name = var.get().strip()
            if not name:
                text = "off"
            elif belt is None:
                text = "The module cannot read the belt"
            else:
                s = next((x for x in belt if x["kind"] == BELT_SF and x["name"].strip().lower() == name.lower()), None)
                text = ("page %d key %s: %s" % (s["page"], s["key"], belt_state_text(s))) if s else "not on the belt"
            lbl.configure(text=text)

    # ---- position -----------------------------------------------------------

    def copy_position(self):
        if self.position:
            self.root.clipboard_clear()
            self.root.clipboard_append("%.2f, %.2f, %.2f" % self.position)
            log("Position copied: %.2f, %.2f, %.2f" % self.position)

    def add_point(self):
        if self.position:
            self.txt_points.insert("end", "%.2f, %.2f, %.2f\n" % self.position)
            self.txt_points.see("end")

    def do_anchor_here(self):
        self.bot.set_anchor_here()

    # ---- loop ---------------------------------------------------------------

    def toggle(self):
        b = self.bot
        b.running = not b.running
        if b.running:
            b.pending_start = True
        log("Bot %s." % ("STARTED" if b.running else "PAUSED"))

    def drain_log(self):
        lines = []
        while LOG_QUEUE is not None and not LOG_QUEUE.empty() and len(lines) < 200:
            lines.append(LOG_QUEUE.get_nowait())
        if not lines:
            return
        t = self.txt_log
        t.configure(state="normal")
        t.insert("end", "\n".join(lines) + "\n")
        extra = int(t.index("end-1c").split(".")[0]) - self.LOG_LINES
        if extra > 0:
            t.delete("1.0", "%d.0" % (extra + 1))
        t.configure(state="disabled")
        t.see("end")

    def refresh(self):
        b = self.bot
        if b.quit:
            self.close()
            return
        self.drain_log()
        self.btn_toggle.configure(text="%s (%s)" % ("Pause" if b.running else "Start", b.hk_label("toggle")))
        snap = self.mem.read()
        target_pid = profile_target_pid(ACTIVE_PROFILE)
        if snap is None:
            self.lbl_game.configure(text="Client: pid %s | Game: %s"
                                         % (target_pid or "-", self.mem.status))
        else:
            self.lbl_game.configure(text="Client: pid %d | snapshot #%d | Bot: %s"
                                         % (snap.pid, snap.counter, "RUNNING" if b.running else "paused"))
            def on(ok):
                return "on" if ok else "OFF"
            has_keys = self.mem.supports_keys()
            keys = on(has_keys)
            if has_keys and not self.mem.dll_flag("keysInactive"):
                keys += " (game window active)"
            self.lbl_mode.configure(text="Through the game: targeting %s | keys %s | walking %s | animus %s | belt %s"
                                         " | loot %s"
                                         % (on(self.mem.supports_commands()), keys, on(self.mem.supports_moves()),
                                            on(self.mem.dll_flag("animusList")), on(self.mem.belt_pages()),
                                            on(self.mem.dll_flag("loot"))))
            av = snap.avatar
            self.position = (av.x, av.y, av.z)
            act = b.action_now()
            self.lbl_char.configure(text="%s  Lv.%d  HP %d%%%s" % (
                av.name, av.level, round(av.hp * 100),
                "" if act is None else "  action 0x%08X%s" % (act[0], " (casting)" if act[0] >> 28 == ACTION_KIND_CAST
                                                               else "")))
            self.lbl_pos.configure(text="X %9.2f   Y %8.2f   Z %9.2f" % self.position)
            if b.anchor:
                self.lbl_anchor.configure(text="Anchor %9.2f %8.2f %9.2f   dist %.0f (leash %.0f)"
                                               % (b.anchor + (dist_xz(b.anchor[0], b.anchor[2], av.x, av.z),
                                                              b.ac["leash"])))
            else:
                self.lbl_anchor.configure(text="Anchor: not set")
            t = snap.target
            self.lbl_target.configure(text="%s  HP %d%%  dist %.0f" % (t.label(), round(t.hp * 100), t.dist(av.x, av.z))
                                      if t else "-")
            if time.time() - self.last_seen >= self.SEEN_REFRESH:
                self.last_seen = time.time()
                self.refresh_seen(snap)
                self.refresh_effects(snap)
                self.refresh_animus()
                self.refresh_belt()
                self.refresh_rotation()
        if time.time() - self.last_profiles >= 2.0:     # also without a game: profiles made by another window
            self.last_profiles = time.time()
            self.refresh_profiles()
        self.root.after(self.REFRESH_MS, self.refresh)

    def close(self):
        self.bot.quit = True
        self.bot.running = False
        try:
            self.root.destroy()
        except self.tk.TclError:
            pass

    def run(self):
        self.root.mainloop()
        self.mem.close()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_bot_loop(bot):
    """The bot itself: one tick every timing.tick_seconds until quit (an error is logged, the loop goes on)."""
    tick_seconds = float(bot.t.get("tick_seconds", TICK_SECONDS))
    bot.start_hotkeys()
    try:
        while not bot.quit:
            started = time.time()
            try:
                bot.tick()
            except Exception as e:
                # the same error at the same line every tick: its traceback once per 30 s, with the repeat count
                where = traceback.extract_tb(e.__traceback__)[-1]
                log_limited("loop:%s:%s:%d" % (type(e).__name__, where.filename, where.lineno),
                            "ERROR in the bot loop:\n%s" % traceback.format_exc().rstrip(), 30.0)
                time.sleep(1.0)
            time.sleep(max(0.0, tick_seconds - (time.time() - started)))
    finally:
        bot.stop_hotkeys()
        bot.mem.close()


_TARGET_PID_CACHE = {}   # {profile: (time read, pid or None)}


def profile_target_pid(profile):
    """The game pid this profile is bound to (from profiles/<name>/.target), or None = pick automatically.
    Cached for 2 s (the window asks on every refresh)."""
    cached = _TARGET_PID_CACHE.get(profile)
    if cached is not None and time.time() - cached[0] < 2.0:
        return cached[1]
    pid = _read_target_pid(profile)
    _TARGET_PID_CACHE[profile] = (time.time(), pid)
    return pid


def _read_target_pid(profile):
    path = os.path.join(profile_dir(profile), ".target")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except FileNotFoundError:                    # not bound yet
        return None
    except Exception as e:                       # read on every GUI refresh: rate-limited
        log_limited("target:" + profile, "Profile '%s': unreadable %s (%s: %s), picking a client automatically."
                    % (profile, path, type(e).__name__, e), 60.0)
        return None


def set_profile_target_pid(profile, pid):
    _TARGET_PID_CACHE[profile] = (time.time(), pid)
    try:
        os.makedirs(profile_dir(profile), exist_ok=True)
        with open(os.path.join(profile_dir(profile), ".target"), "w", encoding="utf-8") as f:
            f.write(str(pid))
    except Exception as e:
        log("Could not save the client pid for profile '%s': %s" % (profile, e))


def _shm_name_for_dll(dll):
    """The SharedName the module mapped from <dll> will use: its BotCore.ini [Bot] SharedName (or the default).
    The module derives its ini from the DLL folder, so this reads the per-profile name without loading anything."""
    if not dll:
        return "Local\\RFBotState"
    try:
        import configparser
        cp = configparser.ConfigParser()
        cp.read(os.path.join(os.path.dirname(os.path.abspath(dll)), "BotCore.ini"), encoding="latin1")
        return cp.get("Bot", "SharedName") or "Local\\RFBotState"
    except Exception:
        return "Local\\RFBotState"


def _module_state(pid, dll):
    """
    What a BotCore mapping in pid publishes to the DLL's shared memory: {'version', 'unhooked'}, None when no module
    runs for pid. Version 10+ modules write their pid into the status block at start, so they count as present
    also at the login screen (no snapshot yet) or while the game is minimized; older ones only by a fresh snapshot
    of that pid (the status tick changed within 5 s).
    """
    name = _shm_name_for_dll(dll)
    k = kernel32
    k.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenFileMappingW.restype = wintypes.HANDLE
    h = k.OpenFileMappingW(FILE_MAP_READ, False, name)
    if not h:
        return None
    p = k.MapViewOfFile(h, FILE_MAP_READ, 0, 0, 0)
    if not p:
        k.CloseHandle(h)
        return None
    try:
        magic = U32.from_address(p).value
        version = U32.from_address(p + 4).value
        st = BotStatus.from_address(p + BOT_STATUS_OFFSET)
        status_ok = st.magic == BOT_STATUS_MAGIC
        tick = st.tick
        unhooked = bool(st.unhooked) if status_ok else False
        status_pid = st.pid if status_ok and version >= 10 else 0
        pid_seen = BotSnapshot.from_address(p).pid
    finally:
        k.UnmapViewOfFile(ctypes.c_void_p(p))
        k.CloseHandle(h)
    if magic != BOT_MAGIC or not status_ok:
        return None
    if status_pid:                                 # version 10+: present whether or not it publishes snapshots
        return {"version": version, "unhooked": unhooked} if status_pid == pid else None
    if pid_seen != pid:                            # older module: only a fresh snapshot of this pid tells
        return None
    age = (get_tick() - tick) & 0xFFFFFFFF
    if age >= 5000:
        return None
    return {"version": version, "unhooked": unhooked}


def _module_live(pid, dll):
    """True when a BotCore mapping of this bot's version in pid already publishes to the DLL's shared memory."""
    if _mm is None:
        return False
    st = _module_state(pid, dll)
    return st is not None and not st["unhooked"] and st["version"] == BOT_VERSION


def _module_other_version(pid, dll):
    """The version of a live, hooked BotCore of ANOTHER version in pid (mapping over it would hook twice), else None."""
    if _mm is None:
        return None
    st = _module_state(pid, dll)
    if st is None or st["unhooked"] or st["version"] == BOT_VERSION:
        return None
    return st["version"]


def _pid_alive(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    kernel32.CloseHandle(h)
    return True


def find_and_map(dll=None, prefer_pid=None):
    """Locate the game (or use prefer_pid), then map the module into it (unless one is already live).
    Returns (pid, base, reused) or raises RuntimeError. Self-contained: needs only manualmap (_mm)."""
    if _mm is None:
        raise RuntimeError("manualmap not available (%s)" % _mm_error)
    _mm.enable_debug_privilege()
    dll = _mm.newest_dll(dll or BUILD_DLL)
    if not os.path.isfile(dll):
        raise RuntimeError("missing %s - run build.ps1" % dll)
    pids = list(_mm.find_game_pids() or [])
    pid = prefer_pid
    if pid is not None and (pid not in pids or not _pid_alive(pid)):
        # the bound pid is no game client any more (game restarted: Windows may give that pid to another program,
        # and mapping into it fails or, worse, works): pick the game itself
        log("Bound game pid %d is not a running game client%s: picking the game itself."
            % (pid, " (now: %s)" % process_image_path(pid) if _pid_alive(pid) else ""))
        pid = None
    if pid is None:
        if not pids:
            raise RuntimeError("game not running (looked for rf_online*/cerberus-games)")
        pid = next((p for p in pids if _module_live(p, dll)), None) or pids[0]
    if _module_live(pid, dll):
        base = _mm.read_base_file(dll)[1]
        return pid, (base or 0), True          # already live, reused
    other = _module_other_version(pid, dll)
    if other is not None:                      # mapping now would hook the game a second time
        raise RuntimeError("an older Bagnon.dll (version %d, this bot needs %d) is still hooked in game pid %d: "
                           "press Remap (it ejects the old one and maps the new one)" % (other, BOT_VERSION, pid))
    try:
        base = _mm.manual_map(pid, dll, then_unlink=True)
    except Exception as e:                     # say which process it was: the wrong one is the usual cause
        raise RuntimeError("mapping into pid %d (%s) failed: %s: %s; game clients found: %s"
                           % (pid, process_image_path(pid) or "path unknown", type(e).__name__, e,
                              ", ".join("%d (%s)" % (p, os.path.basename(process_image_path(p) or "?"))
                                        for p in pids) or "none"))
    return pid, base, False


def autostart_map(bot):
    """Unless --no-map: map this profile's DLL into its game client if it is not mapped yet, so the bot can
    start on its own. Needs admin (the game runs elevated); without it or on failure a hint is logged."""
    if not have_admin():
        log("Autostart: not elevated, the game's module may not map (start as administrator).")
    dll = profile_dll(ACTIVE_PROFILE)
    pid = profile_target_pid(ACTIVE_PROFILE)
    log("Autostart: mapping %s into the game%s..." % (dll, " (pid %d)" % pid if pid else ""))
    try:
        pid, base, reused = find_and_map(dll=dll, prefer_pid=pid)
    except RuntimeError as e:
        log("Autostart: map failed: %s%s" % (e, "" if have_admin() else " (run as administrator)"))
        return
    except Exception as e:                       # manualmap / Win32 errors: logged, the bot still starts
        log("Autostart: map failed (%s: %s)%s" % (type(e).__name__, e, "" if have_admin()
                                                   else " (run as administrator)"))
        return
    set_profile_target_pid(ACTIVE_PROFILE, pid)
    if reused:
        log("Autostart: BotCore already mapped in game pid %d, reusing." % pid)
    else:
        log("Autostart: BotCore mapped into game pid %d at 0x%08X." % (pid, base))


def _shell_execute(verb, args):
    """
    Start this script again with the same interpreter and `args` (ShellExecute: 'runas' = elevated through UAC,
    'open' = as it is). True when Windows started it (result > 32), else logged and False.
    """
    exe = sys.executable if sys.executable and os.path.isfile(sys.executable) else "pythonw.exe"
    params = ' "%s"' % os.path.abspath(__file__) + "".join(' "%s"' % a for a in args)
    try:
        rc = shell32.ShellExecuteW(None, verb, exe, params, HERE, 1) or 0
    except Exception as e:
        log("Could not start a new bot window (%s: %s)." % (type(e).__name__, e))
        return False
    if rc > 32:
        return True
    log("Could not start a new bot window: ShellExecute '%s' returned %d%s." % (
        verb, rc, " (administrator rights declined in the UAC prompt?)" if verb == "runas" else ""))
    return False


def strip_args(argv, drop=()):
    """argv without --profile (and its value), --elevated and the flags in `drop`."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a == "--profile":
            skip = True
            continue
        if a.startswith("--profile=") or a == "--elevated" or a in drop:
            continue
        out.append(a)
    return out


def relaunch_elevated(args):
    """
    Start this script elevated (UAC) with `args`. True when the elevated copy was started (the caller exits);
    False when it was not (UAC declined, error): the caller goes on without administrator rights.
    """
    return _shell_execute("runas", [a for a in args if a != "--elevated"] + ["--elevated"])


def relaunch_into(args):
    """Start a second copy of the bot with `args` (another client profile). True when it was started."""
    return _shell_execute("open", args)


def have_admin():
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception as e:
        log_limited("isadmin", "IsUserAnAdmin failed (%s: %s), treated as not elevated."
                    % (type(e).__name__, e), 300.0)
        return False


def main():
    global LOG_QUEUE, ACTIVE_PROFILE, CFG_PATH
    set_dpi_aware()
    args = sys.argv[1:]
    use_gui = "--nogui" not in args
    want_admin = "--no-elevate" not in args
    ACTIVE_PROFILE = profile_arg(args)
    if not valid_profile_name(ACTIVE_PROFILE):
        _EARLY_ERRORS.append("--profile '%s' is not a valid profile name (ASCII letters, digits, '.', '_', '-'): "
                             "using the profile 'main'." % ACTIVE_PROFILE)
        ACTIVE_PROFILE = "main"
    CFG_PATH = profile_config_file(ACTIVE_PROFILE)
    try:
        os.makedirs(profile_dir(ACTIVE_PROFILE), exist_ok=True)
    except Exception as e:                       # before the window log exists: shown with the early errors
        _EARLY_ERRORS.append("Cannot create the profile folder %s (%s: %s): using %s instead of %s."
                             % (profile_dir(ACTIVE_PROFILE), type(e).__name__, e, CONFIG_FILE, CFG_PATH))
        CFG_PATH = CONFIG_FILE
    # Self-elevate once (the game runs elevated; OpenProcess for the map needs admin). Skipped with --no-elevate
    # or when already elevated / already relaunched.
    if not have_admin() and want_admin and "--elevated" not in args and os.environ.get("RF_NO_ELEVATE") != "1":
        if relaunch_elevated(args):
            return
        _EARLY_ERRORS.append("Running without administrator rights: mapping the module into the game may fail.")
    if use_gui and importlib.util.find_spec("tkinter") is None:
        use_gui = False
        log("tkinter is not installed, running without the window.")
    if use_gui:
        LOG_QUEUE = queue.Queue()
    for msg in _EARLY_ERRORS:
        log(msg)
    del _EARLY_ERRORS[:]
    try:
        cfg = load_config()
        bot = Bot(cfg)
    except (ValueError, KeyError, TypeError) as exc:
        log("Config error: %s" % exc)
        if not use_gui:
            input("Press Enter to close...")
        return
    log("RF bot v%s | profile '%s' | shared memory '%s'. Hotkeys: %s = anchor, %s = start/pause, %s = quit."
        % (VERSION, ACTIVE_PROFILE, cfg["shared"]["name"], bot.hk_label("anchor"), bot.hk_label("toggle"),
           bot.hk_label("quit")))
    # The external guard (rfguard.py) now owns mapping Bagnon for the profile. Do not inject by
    # default; --map keeps the old standalone behaviour, --no-map is still accepted.
    autostart = "--map" in args
    if not use_gui:
        if autostart:
            autostart_map(bot)
        try:
            run_bot_loop(bot)
        except KeyboardInterrupt:
            log("Interrupted.")
        return

    def worker_main():
        """The bot thread: autostart (it may take a while) and then the bot loop, while the window already runs."""
        if autostart:
            try:
                autostart_map(bot)
            except Exception as e:
                log("Autostart failed (%s: %s); press Inject in the window." % (type(e).__name__, e))
        if not bot.quit:
            run_bot_loop(bot)

    worker = threading.Thread(target=worker_main, name="rf-bot", daemon=True)
    worker.start()
    BotGui(bot).run()
    bot.quit = True
    bot.running = False
    worker.join(timeout=3.0)


if __name__ == "__main__":
    main()