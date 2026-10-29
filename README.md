# assburger — RF Online / CERBERUS spoofer + bot sources

Один репозиторий с исходниками двух частей:

- **spoofer** — `spoof.c`, `app.py`, `manualmap.py`, `rfguard.py`, `rfprofiles.py`,
  `start.cmd`, `build.ps1`, `profiles.example.json`;
- **bot** — `bot/` (копия `C:\SHARE\rfbot2`): `src/botcore.c`, `src/win32_min.h`,
  `rfbot.py`, `run_bot.py`, `tools/manualmap.py`, `build.ps1`, профили `bot1`/`bot2`.

Рабочие пути на машине остаются прежними: `C:\SHARE\hwid` и `C:\SHARE\rfbot2`.
Репозиторий — исходники + конфиги + собранный `rfspoof.dll`/`Bagnon.dll`;
секреты (`profiles.json`, `spoof_*.cfg`, proxy/пароли) в git не попадают.

## Build

Spoofer (32-bit MinGW, `C:\SHARE\hwid\tools\mingw32`):

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Bot (LLVM в `C:\Program Files\LLVM\bin`):

```powershell
powershell -ExecutionPolicy Bypass -File bot\build.ps1
```

`rfspoof` требует `.reloc` + TLS (проверяется `manualmap.py --check`); `Bagnon` —
clang/lld, без TLS. Оба мапятся manual map, не LoadLibrary.

## Run (as designed)

```text
start.cmd                 -> app.py + rfguard.py (elevated)
run_bot1.cmd / run_bot2.cmd (в bot/) -> rfbot.py --profile bot1|bot2
```

- `rfguard.py` — единственный маппер: full spoofer в launcher/CEF/game, `Bagnon` в game
  (per-profile `bot_profile` из `profiles.json`);
- `rfbot.py` больше не мапит Bagnon по умолчанию (`--map` возвращает старое поведение);
- per-profile маркер: `meta\profile_<id>\vcredist_x86.exe` (unique UUID, не общий).

## Profiles

`profiles.json` — локальный, с паролями/прокси (ignored). Формат — `profiles.example.json`.
Game profile `1` -> `bot1` (`C:\SHARE\CERBERUS`), `2` -> `bot2` (`C:\SHARE\CERBERUS2`).
`bot/profiles/bot1|bot2` — отдельные `Bagnon.dll`/`BotCore.ini`/SharedName.

## Notes

- `tools/`, `logs/`, `meta/`, `state/`, `cef/`, dumps — runtime/generated, ignored.
- `re_hackshield/` — отчёты и исходники PoC; логи/бинарники/бэкапы ignored.
- `commit_push.ps1` — после утверждённого обновления: commit + push origin master.
