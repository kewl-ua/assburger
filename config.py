# -*- coding: utf-8 -*-
"""
config.py - profiles store for the multi-instance launcher.

profiles.json lives next to this file. Each profile describes one independent launcher window:
its own fake hardware, its own proxy, its own CEF user-data-dir.

Schema:
{
  "game_exe": "C:\\\\SHARE\\\\CERBERUS\\\\CERBERUS-GAMES.exe",
  "profiles": [
    {
      "id": "1",                         # unique, used as SPOOF_ID / cfg name
      "label": "Instance 1",
      "user": "",                        # optional windows account; "" = same session
      "password": "",
      "proxy": "user:pass@host:port",    # SOCKS5; "" = direct
      "inject_children": false,
      "enabled": true,
      "hw": { ...hwgen fields... }        # see hwgen.py
    }
  ]
}
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILES_PATH = os.path.join(HERE, "profiles.json")
DEFAULT_GAME = r"C:\SHARE\CERBERUS\CERBERUS-GAMES.exe"


def default():
    import hwgen
    return {
        "game_exe": DEFAULT_GAME if os.path.isfile(DEFAULT_GAME) else "",
        "profiles": [
            {
                "id": "1", "label": "Instance 1", "user": "", "password": "",
                "proxy": "", "inject_children": True, "enabled": True,
                "hw": hwgen.generate("1"),
            },
            {
                "id": "2", "label": "Instance 2", "user": "", "password": "",
                "proxy": "", "inject_children": True, "enabled": True,
                "hw": hwgen.generate("2"),
            },
        ],
    }


def load():
    if not os.path.isfile(PROFILES_PATH):
        cfg = default()
        save(cfg)
        return cfg
    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("game_exe", DEFAULT_GAME)
    cfg.setdefault("profiles", [])
    return cfg


def save(cfg):
    tmp = PROFILES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PROFILES_PATH)


def next_id(cfg):
    used = {p.get("id") for p in cfg.get("profiles", [])}
    i = 1
    while str(i) in used:
        i += 1
    return str(i)
