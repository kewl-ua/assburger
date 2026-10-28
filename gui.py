# -*- coding: utf-8 -*-
"""
gui.py - control panel for running several isolated CERBERUS launcher instances.

Each profile = one launcher window with its own fake hardware, own SOCKS5 proxy and own CEF
user-data-dir. Buttons: start/stop per profile and start/stop all.

Requires: launcher.py, config.py, hwgen.py, rfspoof.dll (build via build.ps1).
Run as admin (injection needs it). Double-click start.cmd.
"""
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import config
import hwgen
import launcher

HW_FIELDS = [
    ("serial", "Volume serial (C:)"),
    ("cname", "Computer name"),
    ("macaddr", "MAC address"),
    ("guid", "MachineGuid"),
    ("uuid", "System UUID (SMBIOS)"),
    ("biosvendor", "BIOS vendor"),
    ("biosver", "BIOS version"),
    ("biosserial", "BIOS serial"),
    ("boardmfr", "Board manufacturer"),
    ("boardprod", "Board product"),
    ("boardserial", "Board serial"),
    ("sysprod", "System product"),
    ("monid", "Monitor HardwareID"),
    ("cpu", "CPU name"),
    ("diskserial", "Disk serial"),
    ("rammb", "RAM (MB)"),
    ("build", "Windows build"),
]


def is_admin():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cerberus Multi-Launcher")
        self.geometry("920x640")
        self.cfg = config.load()
        self.current = None          # selected profile id
        self.procs = {}              # id -> (pid, handle)
        self.threads = {}            # id -> hThread (while suspended)
        self.vars = {}
        self._build()
        self._refresh_list()
        self._select(self.cfg["profiles"][0]["id"] if self.cfg["profiles"] else None)
        self.after(1500, self._poll)

    # ---------------------------------------------------------------- layout
    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Game exe:").pack(side="left")
        self.game_var = tk.StringVar(value=self.cfg.get("game_exe", ""))
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
        for i, (key, label) in enumerate(HW_FIELDS):
            self._row(hw, i, label, key, None)

        act = ttk.Frame(right)
        act.pack(fill="x", pady=6)
        ttk.Button(act, text="Start selected", command=lambda: self._start([self.current])).pack(side="left")
        ttk.Button(act, text="Stop selected", command=lambda: self._stop([self.current])).pack(side="left", padx=4)
        ttk.Button(act, text="START ALL", command=self._start_all).pack(side="left", padx=16)
        ttk.Button(act, text="STOP ALL", command=self._stop_all).pack(side="left")
        self.apply_btn = ttk.Button(act, text="Apply changes", command=self._apply)
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
            if hint:
                ttk.Label(parent, text=hint, foreground="gray").grid(row=r, column=2, sticky="w")

    # ---------------------------------------------------------------- helpers
    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _pick_game(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(filetypes=[("exe", "*.exe"), ("all", "*.*")])
        if p:
            self.game_var.set(p)

    def _save_game(self):
        self.cfg["game_exe"] = self.game_var.get()
        config.save(self.cfg)
        self._log("game exe saved")

    def _profile(self, pid):
        for p in self.cfg["profiles"]:
            if p["id"] == pid:
                return p
        return None

    def _refresh_list(self):
        self.listbox.delete(0, "end")
        for p in self.cfg["profiles"]:
            alive = " ●" if p["id"] in self.procs and launcher.alive(self.procs[p["id"]][0]) else ""
            self.listbox.insert("end", "%s  [%s]%s" % (p.get("label", p["id"]), p["id"], alive))

    def _select(self, pid):
        self.current = pid
        if pid is None:
            return
        p = self._profile(pid)
        if not p:
            return
        self.vars["label"].set(p.get("label", ""))
        self.vars["game_exe"].set(p.get("game_exe", ""))
        self.vars["user"].set(p.get("user", ""))
        self.vars["password"].set(p.get("password", ""))
        self.vars["proxy"].set(p.get("proxy", ""))
        self.vars["inject_children"].set(bool(p.get("inject_children")))
        hw = p.get("hw") or {}
        for key, _ in HW_FIELDS:
            self.vars[key].set(str(hw.get(key, "")))

    def _on_select(self, _e):
        sel = self.listbox.curselection()
        if not sel:
            return
        self._apply(silent=True)
        pid = self.cfg["profiles"][sel[0]]["id"]
        self._select(pid)

    def _collect_into(self, p):
        p["label"] = self.vars["label"].get()
        p["game_exe"] = self.vars["game_exe"].get().strip()
        p["user"] = self.vars["user"].get()
        p["password"] = self.vars["password"].get()
        p["proxy"] = self.vars["proxy"].get().strip()
        p["inject_children"] = bool(self.vars["inject_children"].get())
        hw = p.get("hw") or {}
        for key, _ in HW_FIELDS:
            val = self.vars[key].get().strip()
            if key in ("build", "rammb"):
                hw[key] = int(val) if val.isdigit() else 0
            else:
                hw[key] = val
        p["hw"] = hw

    def _apply(self, silent=False):
        if self.current is None:
            return
        p = self._profile(self.current)
        if p:
            self._collect_into(p)
            config.save(self.cfg)
            if not silent:
                self._log("saved profile %s" % self.current)
            self._refresh_list()

    def _add(self):
        self._apply(silent=True)
        pid = config.next_id(self.cfg)
        self.cfg["profiles"].append({
            "id": pid, "label": "Instance %s" % pid, "user": "", "password": "",
            "proxy": "", "inject_children": False, "enabled": True, "hw": hwgen.generate(pid),
        })
        config.save(self.cfg)
        self._refresh_list()
        self._select(pid)
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(len(self.cfg["profiles"]) - 1)
        self._log("added profile %s" % pid)

    def _remove(self):
        if self.current is None:
            return
        if self.current in self.procs and launcher.alive(self.procs[self.current][0]):
            if not messagebox.askyesno("Remove", "Profile running. Stop and remove?"):
                return
            self._stop([self.current])
        self.cfg["profiles"] = [p for p in self.cfg["profiles"] if p["id"] != self.current]
        config.save(self.cfg)
        self._log("removed profile %s" % self.current)
        self.current = None
        self._refresh_list()
        if self.cfg["profiles"]:
            self._select(self.cfg["profiles"][0]["id"])
            self.listbox.selection_set(0)

    def _gen_hw(self):
        if self.current is None:
            return
        hw = hwgen.generate(self.current + os.urandom(2).hex())
        for key, _ in HW_FIELDS:
            self.vars[key].set(str(hw.get(key, "")))
        # new identity -> drop the hidden HWID marker folder so the launcher creates a fresh UUID
        mdir = os.path.join(launcher.METADIR, "profile_%s" % self.current)
        import shutil
        shutil.rmtree(mdir, ignore_errors=True)
        self._apply(silent=True)
        self._log("generated new realistic hardware + new HWID marker for profile %s" % self.current)

    # ---------------------------------------------------------------- start/stop
    def _start(self, ids):
        self._apply(silent=True)
        ids = [i for i in ids if i]
        game = self.game_var.get()
        for pid in ids:
            p = self._profile(pid)
            exe = p.get("game_exe") or game
            if not exe or not os.path.isfile(exe):
                self._log("profile %s: no valid game exe" % pid)
                continue
            if pid in self.procs and launcher.alive(self.procs[pid][0]):
                self._log("profile %s already running" % pid)
                continue
            try:
                pr, h, ht = launcher.start(p, game, suspended=True)
                self.procs[pid] = (pr, h)
                self.threads[pid] = ht
                self._log("started %s (pid %d, suspended)" % (pid, pr))
            except Exception as e:
                self._log("start %s failed: %s" % (pid, e))
        # inject each while suspended + resume + watch children, in a worker thread
        threading.Thread(target=self._inject_worker, args=(ids,), daemon=True).start()
        self._refresh_list()

    def _inject_worker(self, ids):
        game = self.game_var.get()
        main_dlls = {}
        # resume all first (LDR builds on first run), tiny settle, then inject
        for pid in ids:
            ht = self.threads.pop(pid, None)
            try:
                launcher.resume(ht)
            except Exception:
                pass
        time.sleep(0.1)
        for pid in ids:
            if pid not in self.procs:
                continue
            pr, hproc = self.procs[pid]
            p = self._profile(pid)
            try:
                launcher.inject_instance(pr, p["_dll"], hproc)
                main_dlls[pr] = (p["_dll"], bool(p.get("inject_children")))
                self._log("injected main %s (pid %d)" % (pid, pr))
            except Exception as e:
                self._log("inject %s failed: %s" % (pid, e))
        # watch children, inject into their own instance (only for profiles that want it)
        name = os.path.basename(game).lower()
        seen = set(main_dlls.keys())
        first_seen = {}
        end = time.time() + 15
        while time.time() < end:
            now = time.time()
            for q in launcher.inj.find_pids_by_name(name):
                if q in seen:
                    continue
                if q not in first_seen:
                    first_seen[q] = now
                    continue
                if now - first_seen[q] < 1.5:      # let the child settle
                    continue
                seen.add(q)
                dll, want = launcher._dll_for_child(q, main_dlls)
                if not want:
                    continue
                try:
                    if launcher.inject_instance(q, dll):
                        self._log("  child %d injected" % q)
                except Exception:
                    pass
            time.sleep(0.05)
        self._refresh_list()

    def _stop(self, ids):
        for pid in ids:
            if pid in self.procs:
                pr, h = self.procs[pid]
                try:
                    if launcher.alive(pr):
                        launcher.kill_pid(pr)
                    self._log("stopped %s (pid %d)" % (pid, pr))
                except Exception as e:
                    self._log("stop %s failed: %s" % (pid, e))
                self.procs.pop(pid, None)
        self._refresh_list()

    def _start_all(self):
        self._start([p["id"] for p in self.cfg["profiles"]])

    def _stop_all(self):
        self._stop(list(self.procs.keys()))

    def _poll(self):
        changed = False
        for pid, (pr, h) in list(self.procs.items()):
            if not launcher.alive(pr):
                self._log("profile %s exited" % pid)
                self.procs.pop(pid, None)
                changed = True
        if changed:
            self._refresh_list()
        self.after(1500, self._poll)


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
