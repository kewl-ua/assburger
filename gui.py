# -*- coding: utf-8 -*-
"""
gui.py - control panel for running several isolated CERBERUS launcher instances.

Each profile = one launcher window with its own fake hardware, own SOCKS5 proxy and own CEF
user-data-dir. Buttons: start/stop per profile and start/stop all.

Architecture (why it's split this way):
  * Model/view separation. All profile data and validation live in profiles_model (no tkinter),
    so the editor can never silently lose an edit on a profile switch: the view commits the
    current profile through model.commit() BEFORE loading the next one, and a bad numeric value
    aborts the switch with a highlight instead of being coerced to 0 behind your back.
  * Non-blocking mainloop. Button handlers never call launcher.* directly. They push a command
    onto a queue; a single background worker thread owns every process/injection call and never
    touches Tk. The worker reports back through a second queue, drained on the Tk thread by an
    after() pump. This keeps the UI responsive during CreateProcess/inject/child-watch and keeps
    all widget access on the main thread (tkinter is not thread-safe).

Requires: launcher.py, config.py, profiles_model.py, hwgen.py, rfspoof.dll (build via build.ps1).
Run as admin (injection needs it). Double-click start.cmd.
"""
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import config
import hwgen
import profiles_model as pm

# launcher is imported lazily inside the worker only: it pulls in Windows-only ctypes.WinDLL,
# so importing it at module load would make gui.py unimportable off Windows (and in tests).


def is_admin():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


class App(tk.Tk):
    POLL_MS = 1500
    DRAIN_MS = 100

    def __init__(self):
        super().__init__()
        self.title("Cerberus Multi-Launcher")
        self.geometry("920x640")

        # --- model ---
        try:
            self.model = pm.AppModel.load()
        except config.ConfigError as e:
            messagebox.showerror(
                "profiles.json error",
                "%s\n\nStarting with an empty list. Your existing file was left untouched." % e)
            self.model = pm.AppModel(game_exe=config.DEFAULT_GAME, profiles=[])

        self.current_id = None       # profile id currently loaded in the editor
        self.running = {}            # id -> pid, mirror of worker state (read-only on this thread)
        self.vars = {}               # key -> StringVar/BooleanVar
        self.entries = {}            # key -> ttk.Entry (for error highlighting)
        self._errored = set()        # keys currently highlighted

        # --- worker plumbing ---
        self.cmd_q = queue.Queue()   # main thread -> worker (process/inject commands)
        self.evt_q = queue.Queue()   # worker -> main thread (log lines, running-state)
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)

        self._build()
        self._refresh_list()
        if self.model.profiles:
            self._select_id(self.model.profiles[0].id)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._worker.start()
        self.after(self.DRAIN_MS, self._drain_events)
        self.after(self.POLL_MS, self._tick_poll)

    # ---------------------------------------------------------------- layout
    def _build(self):
        style = ttk.Style(self)
        try:
            style.configure("Error.TEntry", fieldbackground="#ffd4d4")
        except Exception:
            pass

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Game exe:").pack(side="left")
        self.game_var = tk.StringVar(value=self.model.game_exe)
        ttk.Entry(top, textvariable=self.game_var, width=70).pack(side="left", padx=6)
        ttk.Button(top, text="...", width=3, command=self._pick_game).pack(side="left")
        ttk.Button(top, text="Save", command=self._save_game).pack(side="left", padx=6)
        if not is_admin():
            ttk.Label(top, text="(not admin!)", foreground="red").pack(side="left", padx=6)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=4)

        # left: profile list
        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Profiles").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=26, height=22, exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        bf = ttk.Frame(left)
        bf.pack(fill="x", pady=4)
        ttk.Button(bf, text="+ Add", command=self._add).pack(side="left")
        ttk.Button(bf, text="Remove", command=self._remove).pack(side="left", padx=4)
        ttk.Button(bf, text="Gen HW", command=self._gen_hw).pack(side="left")

        # right: editor
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=10)

        gen = ttk.LabelFrame(right, text="General")
        gen.pack(fill="x", pady=4)
        self._row(gen, 0, "Label", "label", None)
        self._row(gen, 1, "Game exe (this profile)", "game_exe", "пусто = общий сверху")
        self._row(gen, 2, "Windows user (opt.)", "user", None)
        self._row(gen, 3, "Password (opt.)", "password", None)
        self._row(gen, 4, "SOCKS5 proxy", "proxy", "user:pass@host:port")
        self._row(gen, 5, "Inject children", "inject_children", None, check=True)

        hw = ttk.LabelFrame(right, text="Fake hardware  (Gen HW fills realistic values)")
        hw.pack(fill="both", expand=True, pady=4)
        for i, (key, label) in enumerate(pm.HW_FIELDS):
            self._row(hw, i, label, key, None)

        act = ttk.Frame(right)
        act.pack(fill="x", pady=6)
        ttk.Button(act, text="Start selected", command=lambda: self._start([self.current_id])).pack(side="left")
        ttk.Button(act, text="Stop selected", command=lambda: self._stop([self.current_id])).pack(side="left", padx=4)
        ttk.Button(act, text="START ALL", command=self._start_all).pack(side="left", padx=16)
        ttk.Button(act, text="STOP ALL", command=self._stop_all).pack(side="left")
        self.apply_btn = ttk.Button(act, text="Apply changes", command=self._apply_clicked)
        self.apply_btn.pack(side="right")

        # status/log
        bot = ttk.LabelFrame(self, text="Log")
        bot.pack(fill="both", expand=False, padx=8, pady=4)
        self.log = tk.Text(bot, height=8, state="disabled")
        self.log.pack(fill="both", expand=True)

    def _row(self, parent, r, label, key, hint, check=False):
        ttk.Label(parent, text=label, width=20, anchor="w").grid(row=r, column=0, sticky="w", padx=4, pady=1)
        if check:
            v = tk.BooleanVar()
            self.vars[key] = v
            ttk.Checkbutton(parent, variable=v).grid(row=r, column=1, sticky="w")
        else:
            v = tk.StringVar()
            self.vars[key] = v
            e = ttk.Entry(parent, textvariable=v, width=58)
            e.grid(row=r, column=1, sticky="w", padx=4, pady=1)
            self.entries[key] = e
            # clear a red highlight as soon as the user edits that field
            v.trace_add("write", lambda *_a, k=key: self._unmark_error(k))
            if hint:
                ttk.Label(parent, text=hint, foreground="gray").grid(row=r, column=2, sticky="w")

    # ---------------------------------------------------------------- editor <-> model
    def _values_from_widgets(self):
        v = {}
        for k in ("label", "game_exe", "user", "password", "proxy"):
            v[k] = self.vars[k].get()
        v["inject_children"] = bool(self.vars["inject_children"].get())
        for k, _ in pm.HW_FIELDS:
            v[k] = self.vars[k].get()
        return v

    def _load_into_editor(self, pid):
        p = self.model.find(pid)
        if not p:
            return
        self.vars["label"].set(p.label)
        self.vars["game_exe"].set(p.game_exe)
        self.vars["user"].set(p.user)
        self.vars["password"].set(p.password)
        self.vars["proxy"].set(p.proxy)
        self.vars["inject_children"].set(bool(p.inject_children))
        for k, _ in pm.HW_FIELDS:
            self.vars[k].set(str(p.hw.get(k, "")))
        self._clear_error()

    def _try_commit_current(self):
        """Commit the editor into the current profile. Returns True on success; on a bad numeric
        value, highlights the field, shows a message and returns False (nothing saved)."""
        if self.current_id is None:
            return True
        try:
            self.model.commit(self.current_id, self._values_from_widgets())
            self._clear_error()
            return True
        except pm.ValidationError as e:
            self._mark_error(e.field)
            messagebox.showerror("Invalid value", e.message)
            return False
        except config.ConfigError as e:
            messagebox.showerror("Save failed", str(e))
            return False

    # ---------------------------------------------------------------- selection
    def _on_select(self, _e):
        sel = self.listbox.curselection()
        if not sel:
            return
        target = self.model.profiles[sel[0]].id
        if target == self.current_id:
            return
        # commit the profile we're leaving before switching; revert the listbox if it won't commit
        if not self._try_commit_current():
            self._reselect_listbox(self.current_id)
            return
        self.current_id = target
        self._load_into_editor(target)
        self._refresh_list()

    def _select_id(self, pid):
        self.current_id = pid
        self._load_into_editor(pid)
        self._reselect_listbox(pid)

    def _reselect_listbox(self, pid):
        """Set the listbox selection to *pid* without firing <<ListboxSelect>> (programmatic
        selection changes don't generate the virtual event)."""
        self.listbox.selection_clear(0, "end")
        for i, p in enumerate(self.model.profiles):
            if p.id == pid:
                self.listbox.selection_set(i)
                self.listbox.see(i)
                break

    # ---------------------------------------------------------------- helpers
    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _mark_error(self, key):
        e = self.entries.get(key)
        if e is not None:
            e.configure(style="Error.TEntry")
            self._errored.add(key)

    def _unmark_error(self, key):
        if key in self._errored:
            e = self.entries.get(key)
            if e is not None:
                e.configure(style="TEntry")
            self._errored.discard(key)

    def _clear_error(self):
        for key in list(self._errored):
            self._unmark_error(key)

    def _refresh_list(self):
        self.listbox.delete(0, "end")
        for p in self.model.profiles:
            alive = " ●" if p.id in self.running else ""
            self.listbox.insert("end", "%s  [%s]%s" % (p.label or p.id, p.id, alive))
        if self.current_id is not None:
            self._reselect_listbox(self.current_id)

    def _pick_game(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(filetypes=[("exe", "*.exe"), ("all", "*.*")])
        if p:
            self.game_var.set(p)

    def _save_game(self):
        self.model.game_exe = self.game_var.get()
        try:
            self.model.save()
        except config.ConfigError as e:
            messagebox.showerror("Save failed", str(e))
            return
        self._log("game exe saved")

    # ---------------------------------------------------------------- profile edit buttons
    def _apply_clicked(self):
        if self._try_commit_current():
            self._log("saved profile %s" % self.current_id)
            self._refresh_list()

    def _add(self):
        if not self._try_commit_current():
            return
        p = self.model.add()
        try:
            self.model.save()
        except config.ConfigError as e:
            self.model.remove(p.id)
            messagebox.showerror("Add failed", str(e))
            return
        self._refresh_list()
        self._select_id(p.id)
        self._log("added profile %s" % p.id)

    def _remove(self):
        if self.current_id is None:
            return
        pid = self.current_id
        if pid in self.running:
            if not messagebox.askyesno("Remove", "Profile running. Stop and remove?"):
                return
            self._stop([pid])
        self.model.remove(pid)
        try:
            self.model.save()
        except config.ConfigError as e:
            messagebox.showerror("Remove failed", str(e))
            return
        self._log("removed profile %s" % pid)
        self.current_id = None
        self._refresh_list()
        if self.model.profiles:
            self._select_id(self.model.profiles[0].id)

    def _gen_hw(self):
        if self.current_id is None:
            return
        hw = hwgen.generate(self.current_id + os.urandom(2).hex())
        for k, _ in pm.HW_FIELDS:
            self.vars[k].set(str(hw.get(k, "")))
        if not self._try_commit_current():
            return
        # new identity -> ask the worker to drop the hidden HWID marker so launcher makes a fresh one
        self.cmd_q.put(("drop_marker", self.current_id))
        self._log("generated new realistic hardware for profile %s (HWID marker reset requested)"
                  % self.current_id)

    # ---------------------------------------------------------------- start/stop (non-blocking)
    def _start(self, ids):
        if not self._try_commit_current():
            return
        ids = [i for i in ids if i]
        if not ids:
            return
        game = self.game_var.get()
        snaps = {}
        for pid in ids:
            p = self.model.find(pid)
            if p is not None:
                snaps[pid] = p.to_dict()
        self.cmd_q.put(("start", ids, game, snaps))

    def _stop(self, ids):
        ids = [i for i in ids if i]
        if ids:
            self.cmd_q.put(("stop", ids))

    def _start_all(self):
        self._start(self.model.ids())

    def _stop_all(self):
        self.cmd_q.put(("stop_all",))

    def _tick_poll(self):
        self.cmd_q.put(("poll",))
        self.after(self.POLL_MS, self._tick_poll)

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.evt_q.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "running":
                    self.running = payload
                    self._refresh_list()
        except queue.Empty:
            pass
        self.after(self.DRAIN_MS, self._drain_events)

    def _on_close(self):
        try:
            self.cmd_q.put(("quit",))
        except Exception:
            pass
        self.destroy()

    # ---------------------------------------------------------------- worker thread (owns launcher)
    def _emit(self, kind, payload):
        self.evt_q.put((kind, payload))

    def _worker_loop(self):
        """Single background consumer of cmd_q. Owns every launcher.* call and the live process
        table; posts logs and running-state back through evt_q. Never touches Tk widgets."""
        try:
            import launcher
        except Exception as e:                       # pragma: no cover - Windows-only import
            self._emit("log", "FATAL: cannot import launcher: %s" % e)
            return
        procs = {}                                   # id -> (pid, hproc)
        while True:
            cmd = self.cmd_q.get()
            op = cmd[0]
            if op == "quit":
                break
            try:
                if op == "start":
                    self._w_start(launcher, procs, cmd[1], cmd[2], cmd[3])
                elif op == "stop":
                    self._w_stop(launcher, procs, cmd[1])
                elif op == "stop_all":
                    self._w_stop(launcher, procs, list(procs.keys()))
                elif op == "poll":
                    self._w_poll(launcher, procs)
                elif op == "drop_marker":
                    self._w_drop_marker(launcher, cmd[1])
            except Exception as e:
                self._emit("log", "worker error on %s: %s" % (op, e))

    def _emit_running(self, launcher, procs):
        run = {}
        for pid, (pr, _h) in procs.items():
            try:
                if launcher.alive(pr):
                    run[pid] = pr
            except Exception:
                pass
        self._emit("running", run)

    def _w_start(self, launcher, procs, ids, game, snaps):
        ids = [i for i in ids if i]
        hts = {}
        # 1) create every instance suspended
        for pid in ids:
            p = snaps.get(pid)
            if p is None:
                continue
            exe = p.get("game_exe") or game
            if not exe or not os.path.isfile(exe):
                self._emit("log", "profile %s: no valid game exe" % pid)
                continue
            if pid in procs and launcher.alive(procs[pid][0]):
                self._emit("log", "profile %s already running" % pid)
                continue
            try:
                pr, h, ht = launcher.start(p, game, suspended=True)
                procs[pid] = (pr, h)
                hts[pid] = ht
                self._emit("log", "started %s (pid %d, suspended)" % (pid, pr))
            except Exception as e:
                self._emit("log", "start %s failed: %s" % (pid, e))
        # 2) resume all first (LDR builds on first run), tiny settle, then inject
        for pid in list(hts):
            try:
                launcher.resume(hts[pid])
            except Exception:
                pass
        time.sleep(0.1)
        # 3) inject each main process
        main_dlls = {}
        for pid in ids:
            if pid not in procs:
                continue
            pr, hproc = procs[pid]
            p = snaps.get(pid, {})
            if "_dll" not in p:
                try:
                    launcher.prepare(p)          # ensure p["_dll"] exists; preserves call contract
                except Exception:
                    pass
            try:
                launcher.inject_instance(pr, p.get("_dll"), hproc)
                main_dlls[pr] = (p.get("_dll"), bool(p.get("inject_children")))
                self._emit("log", "injected main %s (pid %d)" % (pid, pr))
            except Exception as e:
                self._emit("log", "inject %s failed: %s" % (pid, e))
        self._emit_running(launcher, procs)
        # 4) watch children in a short-lived daemon so the worker stays responsive to stop/quit
        threading.Thread(target=self._w_watch_children,
                         args=(launcher, game, dict(main_dlls)), daemon=True).start()

    def _w_watch_children(self, launcher, game, main_dlls):
        name = os.path.basename(game).lower()
        seen = set(main_dlls.keys())
        first_seen = {}
        end = time.time() + 15
        while time.time() < end:
            now = time.time()
            try:
                pids = launcher.inj.find_pids_by_name(name)
            except Exception:
                pids = []
            for q in pids:
                if q in seen:
                    continue
                if q not in first_seen:
                    first_seen[q] = now
                    continue
                if now - first_seen[q] < 1.5:       # let the child settle
                    continue
                seen.add(q)
                dll, want = launcher._dll_for_child(q, main_dlls)
                if not want:
                    continue
                try:
                    if launcher.inject_instance(q, dll):
                        self._emit("log", "  child %d injected" % q)
                except Exception:
                    pass
            time.sleep(0.05)

    def _w_stop(self, launcher, procs, ids):
        for pid in ids:
            if pid in procs:
                pr, _h = procs[pid]
                try:
                    if launcher.alive(pr):
                        launcher.kill_pid(pr)
                    self._emit("log", "stopped %s (pid %d)" % (pid, pr))
                except Exception as e:
                    self._emit("log", "stop %s failed: %s" % (pid, e))
                procs.pop(pid, None)
        self._emit_running(launcher, procs)

    def _w_poll(self, launcher, procs):
        changed = False
        for pid, (pr, _h) in list(procs.items()):
            if not launcher.alive(pr):
                self._emit("log", "profile %s exited" % pid)
                procs.pop(pid, None)
                changed = True
        if changed:
            self._emit_running(launcher, procs)

    def _w_drop_marker(self, launcher, pid):
        import shutil
        mdir = os.path.join(launcher.METADIR, "profile_%s" % pid)
        shutil.rmtree(mdir, ignore_errors=True)
        self._emit("log", "HWID marker reset for profile %s" % pid)


if __name__ == "__main__":
    if not is_admin():
        # relaunch elevated so injection works
        import ctypes
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable,
                                                '"%s"' % os.path.abspath(__file__), None, 1)
            sys.exit(0)
        except Exception:
            pass
    App().mainloop()
