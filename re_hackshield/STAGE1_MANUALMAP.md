# Этап 1: manual map спуфера + объединение с ботом (Phase 1a)

Дата: 2026-10-29. Профиль: `C:\SHARE\hwid` (Instance 2, `C:\SHARE\CERBERUS2`).
Артефакты: `re_hackshield/STAGE1_MANUALMAP.md`, `re_hackshield/HACKSHIELD_REPORT.md`,
`re_hackshield/poc/*.bak_stage1_*`, `logs/rfguard.log`, `state/<pid>/*.json`.

## Выбранный вариант

Phase 1a (согласован с пользователем): **один elevated guard/loader**, который manual-map'ит
**два модуля** в игру (`rfspoof` + `Bagnon/BotCore`) и **spoofer-only** в лаунчер/CEF. Исходники
`spoof.c` и `botcore.c` не сливались в одну DLL — это снижает риск из-за разных CRT/TLS
(MinGW/UCRT у спуфера, clang/lld + msvcrt у бота).

С точки зрения пользователя это одно целое:
- один запуск (`start.cmd` → `app.py`, `app.py` сам поднимает guard);
- один per-profile конфиг (HWID + proxy/relay + bot profile);
- один manual mapper (`manualmap.py`) для спуфера, один guard (`rfguard.py`);
- один статус на процесс (`Local\RFSpoofState_<pid>`) + существующий `Local\RFBotState_<bot>`;
- запрет двойного map: mutex в `spoof.c` + loader-lock в `manualmap.py` + проверка статуса.

## Что изменено / добавлено

Новое:
- `manualmap.py` — общий 32-битный manual mapper: SEC_IMAGE (MEM_IMAGE), IAT fix,
  **догрузка отсутствующих import-DLL в target** (`LoadLibraryA` через remote stdcall),
  **TLS index + TLS callbacks** (rfspoof — MinGW DLL с `.tls`), entry через `NtCreateThreadEx`
  (fallback `CreateRemoteThread`), PEB unlink, затирание DOS/PE-заголовков, статус/учёт.
- `rfprofiles.py` — единое per-profile представление: cfg (HWID+net), пути DLL/логов/меты,
  выбор bot-профиля (`C:\SHARE\rfbot2\profiles\bot2` для Instance 2), `.target`, SharedName.
- `rfguard.py` — постоянный elevated guard: лаунчер main + CEF-дети → full spoofer;
  игра → full spoofer + `Bagnon.dll`; рестарт игры снова покрывается; fail-closed.
- `re_hackshield/poc/run_guard.cmd` — теперь запускает `rfguard.py` (старое имя файла сохранено).

Изменено:
- `spoof.c` — manual-map-friendly:
  - путь к cfg: `reserved` (вторая строка `"<dll>\0<cfg>\0"`) → `SPOOF_NET_CFG`/`SPOOF_CFG`
    (env) → `<dll>.cfg` из `reserved` → `GetModuleFileNameA` → `<dir>\rfspoof.cfg` →
    `C:\SHARE\hwid\spoof_<id>.cfg` → `C:\SHARE\hwid\rfspoof.cfg`;
  - лог: `log=` из cfg → `SPOOF_LOG` → `<dir>\spoof.log` → `logs\spoof_<id>.log`;
  - `g_hself`/`GetModuleFileNameA` больше не единственный источник пути (для unlinked модуля);
  - одиночная копия: `Local\RFSpoofMutex_<pid>` (вторая копия в процессе не ставит хуки);
  - статус: `Local\RFSpoofState_<pid>` (`magic "RFS1"`, version 1, pid, tick, ready, hooks, cfg);
    `ready=1` ставится сразу после хука main-модуля + inline net (не ждёт 40-проходный sweep);
  - heartbeat-поток обновляет `tick`; `DisableThreadLibraryCalls` сохранён.
- `app.py` — вместо LoadLibrary:
  - `inject_dll()` = `manualmap.map_module()` (fail-closed, ждёт `ready`);
  - один cfg `net=1` (HWID + relay) вместо пары full/net-only; launcher env `SPOOF_CFG` + reserved;
  - main/CEF/игра получают full spoofer; игра — ещё и bot через guard;
  - при неудаче map лаунчер убивается и relay останавливается (fail-closed);
  - `ensure_guard()` при старте и перед каждым запуском профиля.
- `start.cmd` — больше не поднимает `watchinj_multi`; запускает `app.py`, который поднимает guard.
- `build.ps1` — сборка в первый свободный `rfspoof*.dll` (файл может быть занят SEC_IMAGE),
  `-Wl,--dynamicbase`, обнуление `TimeDateStamp`, статическая проверка `.reloc`/TLS через `manualmap --check`.

Бэкапы (до правок): `re_hackshield/poc/spoof.c.bak_stage1_20261029_114244`,
`app.py.bak_stage1_...`, `start.cmd.bak_stage1_...`, `build.ps1.bak_stage1_...`,
`profiles.json.bak_stage1_...` (профили не менялись).

## Manual map: что именно делает `manualmap.py`

1. `OpenProcess(PROCESS_ALL_ACCESS)` (guard elevated; `SeDebugPrivilege` включается).
2. `NtCreateSection(SEC_IMAGE, PAGE_READONLY)` + `NtMapViewOfSection` — регион `MEM_IMAGE`
   (как настоящий модуль), relocations применяет ядро.
3. IAT: для каждой import-DLL ищется база в PEB; если DLL не загружена — `LoadLibraryA` в
   target; имя резолвится **через `GetProcAddress` в target** (это важно: exports API-set/UCRT —
   forwarders, сырой RVA указывал бы на строку-forwarder), ordinal — через
   `GetProcAddress(MAKEINTRESOURCE(ord))`; fallback — разбор export directory. Ошибка =
   исключение (не пишем нулевой thunk).
4. TLS: `TlsAlloc` в target, запись индекса в `AddressOfIndex`, затем вызовы callbacks
   (`DllMain`-подобный stdcall `(hinst, DLL_PROCESS_ATTACH, 0)`) — до entry. Это важно:
   у `rfspoof.dll` два TLS callback (`__dyn_tls_init`-подобные), у Bagnon TLS нет.
5. `reserved` = `"<dll path>\0<cfg path>\0"`; entry-stub: `push reserved; push 1; push hinst;
   call entry; ret`; поток через `NtCreateThreadEx`.
6. PEB unlink (для SEC_IMAGE записи обычно нет — no-op) + затирание DOS/PE заголовков.
7. `Local\RFSpoofLoad_<pid>` сериализует app.py и guard; `Local\RFSpoofMutex_<pid>` —
   финальный запрет двойных хуков.
8. `map_module(wait_ready=True)` ждёт `ready` в `Local\RFSpoofState_<pid>`; иначе fail.

## Конфиг/статус (без секретов в логах)

- cfg: `C:\SHARE\hwid\spoof_<id>.cfg` (и копия `profiles\<id>\rfspoof.cfg`): `net=1`, `rega=1`,
  `proxy=127.0.0.1:<relay>` (или upstream, если relay нет), `proxymain=1`, HWID-поля.
- spoof status: `Local\RFSpoofState_<pid>` (layout: 7×DWORD + `char cfg[260]`; Python:
  `"<IIIIIII260s"`, 288 байт).
- bot: `Local\RFBotState_bot2` (из `C:\SHARE\rfbot2\profiles\bot2\BotCore.ini`), `.target`
  пишется guard'ом; сам бот ждёт `client unpacked` (`StartDelayMs`).
- учёт: `state\<pid>\spoof.json` / `bot.json` (pid, base, dll, cfg, method, time).

## Проверка (статическая, live не запускался)

- `build.ps1`: `rfspoof.dll` собран (60416 байт), `rfspoof.net.next.dll` (40960; старый
  `rfspoof.net.dll` занят live-процессом).
- PE check (`manualmap.py --check`): i386, ImageBase 0x6DBC0000, SizeOfImage 0x1B000,
  **`.reloc` = true** (RVA 0x1A000), **TLS = true**, 2 TLS callback, импорты KERNEL32,
  api-ms-win-crt-*, USER32, WS2_32; `TimeDateStamp=0`, секции переименованы `.gex0..8`.
- `python -m py_compile app.py rfguard.py manualmap.py rfprofiles.py` — OK.
- Импорт всех модулей и read-only dry-scan guard'а (map-функции замоканы): лаунчер main
  (7148) → `launcher`, CEF (8788/13968) → `cef`, игра (5112) → `game` + `bot`; профиль 2
  определяется по каталогу exe. Реальной инъекции при этом не было.
- Read-only проверка процессов: launcher main/CEF (7148/8788/13968) и игра (5112) матчатся
  на профиль 2 по каталогу exe; `command_line` читается из 32-битного PEB; `.target`
  для bot2 = `Local\RFBotState_bot2`.
- В текущих live-процессах ещё сидит **старый LoadLibrary-спуфер** (`rfspoof.new.dll` /
  `rfspoof.net.dll`). Guard это видит (`spoof_modules`) и **не** добавляет вторую копию,
  чтобы не было двойных хуков (graceful handover: пишет `watch_inject_multi.stop`).
  Для доказательства manual map нужен рестарт лаунчера/игры — это этап 2.

## Этап 2 (не выполнялся)

1. Рестарт на `CERBERUS3` (или копии), проверить: в `EnumProcessModules`/Module32 нет
   `rfspoof`/`Bagnon`; регион `MEM_IMAGE`; DOS/PE заголовки затёрты.
2. `Local\RFSpoofState_<pid>.ready=1`, `hooks>0`; HWID A/W: `MachineGuid`, `HardwareConfig`
   (`BIOSVendor/BaseBoard*/System*/ProcessorNameString/HardwareID`), `GetComputerNameExW`,
   SMBIOS/disk/monitor/RAM; `regA=1`.
3. net: relay `127.0.0.1:<port>`, `socks5 CONNECT rep=0`, нет прямых IP/утечек DNS; main/CEF/игра.
4. Bot: `Bagnon` в игре, `Local\RFBotState_bot2` свежий, vtable-слоты `0x00A41ED0`/`0x00A4FE74`
   указывают в регион Bagnon.
5. Рестарт игры из лаунчера → новый PID снова получает full+net+bot; fail-closed при отказе map.
6. RFOCliMod scan (K32EnumProcessModules/VirtualQuery/ReadProcessMemory/NtQueryInformationProcess/
   IsDebuggerPresent) с caller-address; canary SEC_IMAGE + vtable-hook; бан-тест на тестовом
   аккаунте.

## Ограничения / риски

- `manualmap` грузит отсутствующие import-DLL (UCRT) в target через `LoadLibraryA`; это
  единственный LoadLibrary, но он грузит **системные** DLL, а не спуфер. Если target держит
  loader lock (ранняя инициализация), будет retry/fail-closed.
- `TlsAlloc`-блок для `__thread` не выделяется; `spoof.c` не использует `__thread`, но при
  будущем добавлении TLS-переменных это надо учесть.
- В логах нет proxy-кредов/паролей; в `profiles.json` они остаются как есть.
- `watchinj_multi.exe` оставлен как legacy-артефакт; новые запуски его не используют.

## Постмортем первого live-запуска (11:59)

- Симптом: лаунчер падал сразу после map; в EventLog `0xc0000005`, fault offset
  `0x12f41269`/`0x14101269` (низкие 16 бит = entry RVA `0x1269`, модуль «unknown» из-за
  затёртых заголовков); `spoof_2.log` пустой, `Local\RFSpoofState_<pid>` не `ready`.
- Причина: в `manualmap._write_entry_stub` displacement `E8` считался от **image base**, а не от
  адреса stub'а (`VirtualAllocEx` в другом месте). Поток прыгал в `stub_addr + entry_rva`, т.е. в
  освобождённую/чужую память.
- Исправление: `struct.pack_into("<i", stub, call_at + 1, entry - (addr + call_at + 5))`
  (`addr` = адрес stub'а). DLL не менялась, только `manualmap.py`.
- Для проверки нужен рестарт guard/app (старый guard держит старый `manualmap.py` в памяти).

### Контрольный тест после фикса (12:02)

- `tests/map_host.exe` (32-bit, `Sleep(60s)`, без игры/UAC): manual map `rfspoof.dll` с
  `spoof_99.cfg` (`net=0`) — `mapped at 0x736A0000 (SEC_IMAGE)`, imports 90, TLS 2 callback,
  entry OK, `Local\RFSpoofState_9184.ready=1`, `spoof_modules=[]` (в PEB нет), процесс жив.
- `verify` в логе показывает реальное имя (`DESKTOP-SNQG1MV`): это **ожидаемо** для manual map —
  собственный IAT спуфера не в PEB и не патчится; патчатся IAT целевых модулей (62 записи).
  В лаунчере/игре проверять HWID через код приложения/`test_a`, а не по строке `verify`.
- Артефакт теста: `tests/map_host.c/.exe`; временный cfg/state удалены.

## Причина потери аккаунтов (29.10.2026, live)

- Спуф HWID и прокси применяются: `spoof_2.log` (`serial=406C097E`, `proxy=on`),
  `socks5 CONNECT rep=0`, `ConnectEx PROXIED`; guard status `ready`, `hooks=20`; legacy-модулей нет.
- `System\accounts.json` создаётся (`[]`), но аккаунты не переживают рестарт.
- Найден PC-ID маркер: `C:\ProgramData\Microsoft\DeviceSync\vcredist_x86.exe` (redirect в
  `meta\profile_2`). После запуска содержимое профильного маркера меняется:
  `0ec897ff-...` → `286e9687-...`; лаунчер перезаписывает его при каждом старте, поэтому
  серверный `auth_hash`/привязка аккаунта каждый раз другая.
- Исправление по умолчанию: `metadir=C:\ProgramData\Microsoft\DeviceSync` (реальный маркер,
  redirect становится no-op); старый per-profile режим — `RF_PROFILE_META=1`.
  Для проверки нужен новый процесс `app.py` (старый держит `rfprofiles.py` в памяти).

### Stage 1 game acceptance (29.10.2026, live)

- Игра стабильна: `RF_Online_4gb.bin` PID 26640; `Local\RFSpoofState_26640.ready=1`,
  `cfg=spoof_2_game.cfg`; `rfspoof`/`Bagnon` в PEB **отсутствуют**.
- Бот: `Bagnon` замаплен guard'ом (base `0x6F610000`), `Local\RFBotState_bot2` живой,
  первый snapshot после входа в мир (`8 characters`), vtable-слоты
  `0x00A41ED0`/`0x00A4FE74` указывают в регион Bagnon.
- Сеть: `socks5 CONNECT rep=0`, `ConnectEx PROXIED`; proxy через relay.
- Причина падений игры: `GetProcAddress` IAT-хук (`h_GetProcAddress`). Стабильный набор:
  `net=1`, `noiat=0` (IAT connect/WSAConnect/ConnectEx), `noinline=1`, `nocex=1`,
  `nogpa=1`, `proxymain=1`; full HWID.
- Итоговый game cfg генерируется из `game_overrides.cfg`; launcher/CEF — полный `spoof_2.cfg`.
- Осталось: рестарт игры (новый PID снова full+net+bot) и этап 2 (RFOCliMod scan/canary/vtable,
  relog, multi-instance, VM/debugger, бан-тест).

- Рестарт игры: новый PID 11240 получил full spoofer (spoof_live=True, RFSpoofState.ready=1,
  PEB пуст) и Bagnon (base 0x6F610000); guard сработал на новом PID (~1 c). Бот-снапшот
  появится после входа в мир (StartDelayMs=3000).

- После входа в мир: PID 11240 spoof_live=True, Local\RFSpoofState.ready=1, PEB пуст;
  ot_live=True, первый snapshot получен; сеть socks5 CONNECT rep=0 / ConnectEx PROXIED.
  **Этап 1 (игра/лаунчер/бот/manual map/restart) — принят.**

### Stage 2, шаг 1: RFOCliMod scan (rfmon3, inline)

- `rfmon3.dll` (inline `K32EnumProcessModules`/`EnumProcessModules`/`VirtualQuery(Ex)`/
  `ReadProcessMemory`/`NtQueryInformationProcess`/`IsDebuggerPresent`/
  `CreateToolhelp32Snapshot`) внедрён в PID 21468 после старта.
- Из региона RFOCliMod (`0x080C0000..0x08422000`) за время игры **нет** вызовов этих API.
  Единственный наблюдаемый RF-вызов — `GetAsyncKeyState` F1–F10 (игровые бинды).
- 28k `VirtualQuery` в логе — это `Bagnon` (bot), не RFOCliMod.
- Вывод: RFOCliMod либо сканирует только на старте (до монитора), либо использует
  direct syscall/VMP; в геймплее module/memory-scan через эти API не наблюдается.
  Монитор после проверки снять рестартом игры.

### Фикс сети игры (29.10.2026)

- Было: игра подключалась **напрямую** к `168.113.248.36:23445` (IAT-хуков не хватало, inline
  `connect` был выключен), relay `127.0.0.1:65349` простаивал.
- Стабильный game cfg: `net=1`, `noinline=0` (inline connect/WSAConnect), `nocex=1`,
  `nogpa=1` (GetProcAddress off — он ронял игру), `noiat=0`, `proxymain=1`.
- После рестарта PID 20580: единственное соединение `127.0.0.1:58191 -> 127.0.0.1:65349`
  (relay Established), прямого `168.113...` нет; `socks5 CONNECT rep=0`.
  `RFSpoofState.ready=1`, PEB пуст.
- `hook connect ... byte0=E9` — `connect` уже был inline-хукнут (вероятно RFOCliMod);
  наш `InlineHook` не дублировал, проксирование идёт через IAT/ConnectEx.

### Stage 2, шаг 2: canary SEC_IMAGE + vtable-hook

- Видимый canary `canary.dll` (SEC_IMAGE, LoadLibrary) на `0x6F600000`; слот
  `0x00A41ED4` (исходно `0x004038A0`) заменён на canary-thunk, который инкрементит
  счётчик и прыгает в оригинал. За 5–10 с счётчик `0x5FC -> 0xAE4+` (2788+ вызовов),
  игра жива; RFOCliMod слот **не восстановил**.
- Скрытый эквивалент — `Bagnon` (manual map, PEB не содержит): слоты
  `0x00A41ED0` и `0x00A4FE74` указывают в `0x70FD...`, PEB пуст, после рестарта
  снова на месте; RFOCliMod их не репарит.
- Вывод: vtable/manual-map canary в геймплее не детектится и не восстанавливается.
  Осталось: relog/login/map, synthetic input (RF читает GetAsyncKeyState F1–F10),
  multi-instance, VM/debugger, бан-тест.

### Stage 2, шаг 3: synthetic input vs GetAsyncKeyState

- Окно игры в фокусе; `rfmon2` (IAT) логирует опрос RFOCliMod F1–F10.
- `PostMessage(WM_KEYDOWN/UP, VK_F1)` в окно игры: RFOCliMod получает
  `GetAsyncKeyState(0x70)=0x0000` — физическое состояние не меняется.
- `keybd_event(VK_F1, down)` (аналог SendInput): RFOCliMod получает
  `GetAsyncKeyState(0x70)=0x8000` — состояние видно.
- Вывод: RFOCliMod проверяет **физическое** состояние F1–F10. Клавиши бота через
  `PostMessage` для этих VK — потенциальный tell; для synthetic input нужен
  `SendInput`/`keybd_event` (с фокусом) или игровые функции (`CLinkBoard::UseSlot` для belt).
  Бот сейчас belt делает через `UseSlot` — это ок; `BOT_CMD_KEY` через PostMessage — проверить.

### Stage 2, шаг 4: relog/map

- PID 25864 после relog/смены карты: `spoof_live=True`, `RFSpoofState.ready=1`, PEB пуст.
- `bot_live=True`; vtable-слоты `0x00A41ED0`/`0x00A4FE74` по-прежнему указывают в Bagnon
  (`0x70FD...`); сеть `127.0.0.1:<port> -> 127.0.0.1:65349` (relay).
- Relog/map не сбрасывает спуфер/бота/vtable/relay.

### Stage 2, шаг 5: multi-instance / per-profile marker

- Одновременно: profile 2 `C:\SHARE\CERBERUS2` PID 26736 и profile 1 `C:\SHARE\CERBERUS`
  PID 27088; у обоих `spoof_live=True`, `RFSpoofState.ready=1`, PEB пуст.
- Профили изолированы: `spoof_1_game.cfg` / `spoof_2_game.cfg` с разными
  `serial/cname/guid`, `metadir`, relay (`53522`/`62920`); соединения идут на свои
  `127.0.0.1:<relay>`.
- Маркеры профилей уникальны и **не перезаписываются** после запуска:
  profile 1 `bcd5c223-...`, profile 2 `10b102b4-...` (mtime 13:30:09 не менялся).
- Аккаунты раздельные: `CERBERUS\System\accounts.json` (`Vlados90`) и
  `CERBERUS2\System\accounts.json` (`brians`).
- Бот только в profile 2 (`bot_live=True`), в profile 1 `bot_live=False` — не цепляется
  к чужому клиенту.

### Stage 2, шаг 6: debugger / VM

- Debugger: `dbgattach.exe` (реальный `DebugActiveProcess` + `WaitForDebugEvent`/`ContinueDebugEvent`)
  подключён к profile 2 PID 26736 на 5 с, затем `DebugActiveProcessStop`. Клиент жив,
  `BeingDebugged` после detach = 0; краша/реакции RFOCliMod не было.
  (profile 1 run as John; attach tool as Johnny получает err=5 к чужому пользователю.)
- VM: хост физический — `Win32_ComputerSystem: ASRock X670E Steel Legend,
  HypervisorPresent=False`. VM-тест сейчас не применим (нужна отдельная VM).
- BOT_CMD_KEY: `PostMessage` для F1–F10 RF не видит (`GetAsyncKeyState=0`), `keybd_event`
  видит (`0x8000`); belt бота через `UseSlot` — безопасно.

### rfbot.py под текущую архитектуру

- `rfbot.py` больше не авто-мапит Bagnon: `autostart = "--map" in args`; guard — единственный
  маппер. Кнопки Inject/Remap остались, `--map` возвращает старое поведение.
- Создан bot-профиль `profiles/bot1` (копия bot2): `BotCore.ini` SharedName
  `Local\RFBotState_bot1`, `rf_bot_config.json` с тем же именем, свой `Bagnon.dll`.
- В `C:\SHARE\hwid\profiles.json`: profile 1 -> `bot_profile=bot1`, profile 2 -> `bot2`.
  Guard теперь мапит bot1 в `C:\SHARE\CERBERUS`, bot2 в `C:\SHARE\CERBERUS2`.
- GUI «Bind client» показывает PID, путь exe, game profile и bot profile; при несовпадении
  выбранного профиля пишет предупреждение. Запуск: `pythonw rfbot.py --profile bot1`
  / `--profile bot2`.
- Проверено: `bot1`/`bot2` live в своих играх (27088/26736), `.target` = 27088/26736.
