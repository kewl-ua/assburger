r"""
run_bot.py - start the bot against a running RF client via the manual-mapped BotCore module.

Flow:
  1. find the game process (rf_online*.bin / cerberus-games.exe),
  2. manual-map a Bagnon.dll into it (no LoadLibrary, module unlinked from the PEB),
  3. the module hooks 2 vtable slots and starts publishing the game state to shared memory,
  4. (rfbot.py reads the shared memory and sends commands).

The module derives BotCore.ini / BotCore.log / the shared-memory name from the folder the DLL is mapped
from, so each client can be mapped from its own folder (profiles\<name>\Bagnon.dll) with its own SharedName.

Run as admin (the game may run as admin / spoofed).
Usage:
    python run_bot.py                    # map the default DLL into the first game client
    python run_bot.py --pid 1234         # map into a specific pid
    python run_bot.py --dll <path>       # map a specific DLL (its folder = its ini / log)
    python run_bot.py --exe name.exe     # force a target exe name
    python run_bot.py --list             # list running game clients
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))

import manualmap as mm  # noqa: E402


def is_admin():
    try:
        import ctypes
        return bool(ctypes.WinDLL("shell32").IsUserAnAdmin())
    except Exception:
        return False


def _shm_name(dll=None):
    """The SharedName the module mapped from <dll> will use: read BotCore.ini next to it ([Bot] SharedName)."""
    if not dll:
        return "Local\\RFBotState"
    ini = os.path.join(os.path.dirname(os.path.abspath(dll)), "BotCore.ini")
    try:
        import configparser
        cp = configparser.ConfigParser()
        cp.read(ini, encoding="latin1")
        return cp.get("Bot", "SharedName") or "Local\\RFBotState"
    except Exception:
        return "Local\\RFBotState"


def module_live(pid, dll=None):
    """True when a BotCore mapping in pid is already publishing to shared memory (fresh, right version)."""
    import ctypes
    import struct
    from ctypes import wintypes
    import rfbot
    name = _shm_name(dll)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenFileMappingW.restype = wintypes.HANDLE
    k.MapViewOfFile.restype = ctypes.c_void_p
    k.GetTickCount.restype = wintypes.DWORD
    h = k.OpenFileMappingW(6, False, name)
    if not h:
        return False
    p = k.MapViewOfFile(h, 6, 0, 0, 0)
    if not p:
        k.CloseHandle(h)
        return False
    try:
        buf = ctypes.string_at(p, rfbot.BotSnapshot.pid.offset + 4)
    finally:
        k.UnmapViewOfFile(ctypes.c_void_p(p))
        k.CloseHandle(h)
    magic = struct.unpack_from("<I", buf, rfbot.BotSnapshot.magic.offset)[0]
    version = struct.unpack_from("<I", buf, rfbot.BotSnapshot.version.offset)[0]
    counter = struct.unpack_from("<I", buf, rfbot.BotSnapshot.counter.offset)[0]
    tick = struct.unpack_from("<I", buf, rfbot.BotSnapshot.tick.offset)[0]
    pid_seen = struct.unpack_from("<I", buf, rfbot.BotSnapshot.pid.offset)[0]
    if magic != rfbot.BOT_MAGIC or version != rfbot.BOT_VERSION:
        return False
    t = int(k.GetTickCount()) & 0xFFFFFFFF
    age = (t - tick) & 0xFFFFFFFF
    return age < 5000 and counter > 0 and pid_seen == pid


def find_and_map(dll=None, exe=None, then_unlink=True, pid=None, prefer_pid=None):
    """Locate the game (or use `pid`), map the module into it (unless one is already live).
    Returns (pid, base, reused) or raises RuntimeError.

    Multi-client: when `pid` is None, bind to `prefer_pid` if it is alive, else pick a game client that has
    no module at this DLL's shm yet (so two profiles do not both land in the same process when possible)."""
    mm.enable_debug_privilege()
    dll = mm.newest_dll(dll or os.path.join(HERE, "build", "Bagnon.dll"))
    if not os.path.isfile(dll):
        raise RuntimeError("missing %s - run build.ps1" % dll)
    if pid is None:
        pid = prefer_pid
        if pid is not None and not _pid_alive(pid):
            pid = None
        if pid is None:
            pids = mm.find_game_pids(exe)
            if not pids:
                raise RuntimeError("game not running (looked for %s)" % (exe or "rf_online*/cerberus-games"))
            # prefer a client where this profile's module is already live (reuse), else a client without one
            live = next((p for p in pids if module_live(p, dll)), None)
            pid = live or pids[0]
    if module_live(pid, dll):
        base = mm.read_base_file(dll)[1]
        return pid, (base or 0), True          # already live, reused
    base = mm.manual_map(pid, dll, then_unlink=then_unlink)
    return pid, base, False


def _pid_alive(pid):
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    k.CloseHandle(h)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=None, help="target process name (default rf_online*/cerberus-games)")
    ap.add_argument("--pid", type=int, default=None, help="map into this pid")
    ap.add_argument("--dll", default=os.path.join(HERE, "build", "Bagnon.dll"))
    ap.add_argument("--list", action="store_true", help="list running game clients and exit")
    ap.add_argument("--keep", action="store_true", help="keep the PEB entry (module stays listed)")
    ap.add_argument("--method", default=None, choices=["auto", "apc", "nt", "crt"], help="entry-run method")
    ap.add_argument("--nohead", action="store_true", help="do not zero the PE headers")
    args = ap.parse_args()

    if args.method:
        os.environ["RF_METHOD"] = args.method
    if args.nohead:
        os.environ["RF_NOHEAD"] = "1"

    if args.list:
        pids = mm.find_game_pids(args.exe)
        print("game clients: %s" % (", ".join("%d%s" % (p, " (mapped)" if module_live(p, args.dll) else "")
                                              for p in pids) or "none"))
        return 0

    try:
        pid, base, reused = find_and_map(args.dll, args.exe, then_unlink=not args.keep, pid=args.pid)
    except RuntimeError as e:
        print("%s" % e)
        if "admin" in str(e).lower() or not is_admin():
            print("run this as administrator (the game runs elevated)")
        return 1
    if reused:
        print("module already mapped in game pid %d (base 0x%08X), reused" % (pid, base))
        return 0
    print("game pid = %d" % pid)
    print("mapped BotCore at 0x%08X%s" % (base, " (PEB entry kept)" if args.keep
                                          else " (unlinked, invisible to Module32)"))
    print("the module writes BotCore.log next to the DLL; watch it for 'client unpacked' and 'bot export'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
