# HackShield в RF Online / CERBERUS — отчёт о реверсе

Дата: 29.10.2026  
Хост: Windows 11 Pro 10.0.22631 x64, клиент и лаунчер — 32-bit WOW64.  
Артефакты: `C:\SHARE\hwid\re_hackshield\`.  
Рабочий профиль: `C:\SHARE\CERBERUS2` (Instance 2). Тестовая копия: `C:\SHARE\CERBERUS3`.  
Оригинальные файлы не изменялись; в живой процесс игры внедрялись только benign-мониторы (`hsmon*.dll`), без подмены HWID.

---

## 0. Краткий вывод (TL;DR)

1. **Отдельного AhnLab/HackShield в системе нет.** Нет `EHSvc.dll`, `HSUpdate.exe`, сервиса, драйвера, ключа `HKLM\SOFTWARE\AHNLAB` (в т.ч. WOW6432Node). `Hsp.sys` — Microsoft Pluton.
2. **HackShield SDK встроен в `RF_Online_4gb.bin`**, но в этом приватном билде он, по совокупности доказательств, **не инициализируется и является мёртвым/legacy-кодом**. Монитор, внедрённый в процесс игры *до* resume/окна, не увидел ни `HackShield Init Ok`, ни `Svr Init Ok`, ни `EHSvc`, ни `Netbios`/`GetDriveTypeA`/`MachineGuid`, ни callback `0x10101/0x10102`, ни пакетов `0x62`/342/74. Код по адресу callback `0x731550` в live-процессе — `00 00 00`.
3. **Фактический клиентский модуль — `RFOCliMod.vmp.dll`** (`GAMESPROTECT::cerberus`, VMP, memory-only, файла на диске нет). Это CERBERUS-мод/защита, не AhnLab. В нём есть UI/чат/радар/DPS/exitlag/macro-классы; он и есть основной кандидат на «античит/мод» в этой сборке.
4. **Практический вывод для мультиоконного спуфера:** net-only проксирование (уже работающее `rfspoof.net.dll` + relay) безопасно; спуфить именно HackShield-VphwID в этой сборке не требуется. Если сервер/RFOCli требует HWID — хуки HWID-API ставить до окна/резюма, но это уже не HackShield.
5. **Anti-AutoMouse HackShield** в live не наблюдался (`Detect AutoMouse` = 0). Игра сама опрашивает `GetKeyState/GetCursorPos/PostMessage`, имеет собственную macro-подсистему; антимакрос может быть в RFOCliMod/на сервере.

Уверенность: **высокая** в том, что в этой установке HackShield не активен; **средняя** в том, что он не активируется на других картах/серверах (см. Unknowns).

---

## 1. Инвентаризация

### 1.1. Файлы, сервисы, драйверы, реестр

Поиск по `C:\SHARE` и системе (`HSUpdate.exe`, `EHSvc.dll`, `AhnLab*`, `HShield*`, `HackShield*`, `*.hsd`, `*.hsl`):

- отдельных файлов HackShield/EHSvc/HSUpdate **не найдено**;
- сервисов AhnLab/HackShield **нет**;
- драйвер `Hsp` — `C:\Windows\system32\drivers\Hsp.sys`, **Microsoft Pluton Service**, не AhnLab;
- `HKLM\SOFTWARE\AHNLAB`, `HKLM\SOFTWARE\WOW6432Node\AHNLAB`, `HKCU\SOFTWARE\AHNLAB` **отсутствуют**;
- в `Uninstall` и `Services` упоминаний HackShield/AhnLab нет.

Строки `SOFTWARE\AHNLAB\IOU\HackShield` и `HSUpdate.exe` присутствуют только внутри `RF_Online_4gb.bin` (legacy-код), но ключ/файл не создаются.

### 1.2. PE-файлы

| Файл | Размер | Тип | Примечание |
|---|---:|---|---|
| `C:\SHARE\CERBERUS2\RF_Online_4gb.bin` | 19 833 856 | PE32 i386, GUI | ImageBase `0x400000`, SizeOfImage `0x4DAF000`; секции `.text/.rdata/.data/.gpt0/.gpt1/.gpt2/.rsrc`; `.text/.rdata/.data` в файле имеют RawSize=0 — упаковщик **shzip** (строки `shzip.dll`, `clearplain`, `shplain`, PDB `e:\work\work_all\shzip\Release\shzip.pdb`). Не подписан. SHA256 `E0E2B6E7...A23D6CD`. |
| `C:\SHARE\hwid\RF_Online_4gb_dump.exe` | 81 439 744 | PE32 i386 | Реконструированный дамп с распакованными `.text/.rdata/.data`; ImageBase/SizeOfImage те же. Использовался для статики/xrefs. Не подписан. SHA256 `8D3A2CBF...5264B6B8`. |
| `C:\SHARE\hwid\re_hackshield\poc\RFOCliMod.vmp.dump.bin` | 3 547 136 | PE32 i386 | Дамп памяти `RFOCliMod.vmp.dll`; VMP, `.fptable/.gpt0`, без импортов/экспортов; PDB `E:\source\cerberus\cerb-client\Bin\4gb_Release\Win32\RFOCliMod.pdb`. SHA256 `7791285A...BBFD15F`. |

`RF_Online.bin` (19 523 072) — такой же shzip-пакет; в игре используется 4gb-вариант.

### 1.3. Модули живого процесса игры

Снято с рабочего процесса `RF_Online_4gb.bin` (PID 2796, запущен лаунчером 29.10.2026 10:42:51), монитор `hsmon6.dll` внедрён вотчером в момент создания процесса. Полный список — `logs/modules_2796.txt` (94 модуля + заголовок). Ключевое:

- `RF_Online_4gb.bin` — база `0x00400000`;
- `RFOCliMod.vmp.dll` — база `0x07EE0000`, путь `C:\SHARE\CERBERUS2\RFOCliMod.vmp.dll` (файла на диске нет — memory-only);
- `hsmon6.dll` — наш монитор, `0x6F590000`;
- `EHSvc.dll`, `HSUpdate.exe`, `HShield.dll`, `AhnLab*` — **нет**;
- `rfspoof.net.dll` в этом запуске не было (net-only DLL был в предыдущем процессе PID 7756, база `0x72CE0000`).

Ранее, в рабочем процессе PID 7756, было 95 модулей, включая `rfspoof.net.dll`; HackShield/EHSvc также отсутствовали (`logs/modules_7756.txt`).

Полный список модулей PID 2796 — Приложение A.

### 1.4. `RFOCliMod.vmp.dll` — фактический клиентский мод

- Загружен и в рабочем CERBERUS2, и в тестовом CERBERUS3; файл на диске отсутствует (загружается/удаляется лаунчером, memory-only).
- VMP-упакован, без обычных импортов/экспортов; в памяти видны строки:
  - `E:\source\cerberus\cerb-client\Bin\4gb_Release\Win32\RFOCliMod.pdb`;
  - `GAMESPROTECT::cerberus::...`, `GCerbClient`, `CGUI...`, `radar_ex`, `dps_meter`, `buyback`, `macro_filter_board`, `CMacroProcessor`, `CMacroPotionProcessor`, `exitlag.on_hook_listen_address_established`, `SYSTEM\HardwareConfig`, `client_id`, `LastConfig`, `CRF_OnlineCerberusCrypto`;
  - `boost::asio`, `boost::dll`, `abseil`.
- Это **не AhnLab/HackShield**: строк `HackShield`, `VphwID`, `EHSvc` в нём нет. Похоже на CERBERUS-клиентский мод (UI/чат/радар/DPS/exitlag/macro), возможно, с собственной защитой/криптой.
- В отчёте он отмечен как отдельный слой; его внутренности VMP, детальный реверс — в Unknowns.

---

## 2. Инициализация HackShield: где и когда

### 2.1. Статика (по распакованному дампу)

HackShield-обвязка находится в `.text` дампа; строки — в `.rdata/.data`.

| RVA/VA (dump) | Что делает |
|---|---|
| `0x731180` | Строит путь: `GetModuleFileNameA`, `%s%s%s\%s`, `%s%s%s\%s%s`, использует `\EHSvc.dll` и `HackShield`; вызывает `0x731370`. |
| `0x731370` | Выбирает регион-ключ: `0xA6AA1C` (`3C8C7629B3800972`), `0xA6AA30` (`4219411BCD902C8C`), `0xA6AA44` (`4C6ABE9C50DF8607F1EE2BF7`); вызывает `0x753CE2` (инициализация/лог). |
| `0x731E30` | `0x7542A3(2, 0x731550, 0x731370)` — регистрация callback `0x731550`; затем `0x731850`. |
| `0x73B780` / `0x73C3C0` | Две ветки init: `0x731180` → если ok, лог `HackShield Init Ok` / `HackShield Svr Init Ok`, вызов `vtable+8`; vtables `0xA6B638` / `0xA6C420`. |
| `0x731E70` | Таймер/вотчер с интервалом `0xEA60` (60 000 мс) после init. |
| `0x731550` | Callback-диспетчер (`ret 0xc`): коды `0x10101`, `0x10102`, `0x10501`, `0x103xx`, `0x107xx`, `0x109xx`. |
| `0x731850` | Обработчик ошибок: `HackShield Err %x`, jump table, сообщения `HS Err 1..4`. |
| `0x755539`/`0x75558A` | Путь `HSUpdate.exe`, `%s\%s`; `0x755850`. |
| `0x7AFA9E` | Лог `%s\%s_%s_Hack%d.log` (HackShield-лог). |

Строки:

- `0xA6AA60` — `[HACKSHIELD] Already Hooked`
- `0xA6AA7C` — `- szFunctionName : %s`
- `0xA6AA92` — `- szModuleName : %s`
- `0xA6AAA8` — `[HACKSHIELD] Detect AutoMouse - %d`
- `0xA6DA9C` / `0xA6DAB0` — `HackShield Init Ok` / `HackShield Svr Init Ok`
- `0xA6DDD8` / `0xA6DDEC` — вторая пара Init Ok/Svr Init Ok
- `0xA6A9D0` — `\EHSvc.dll`
- `0xB3586C` — `SOFTWARE\AHNLAB\IOU\HackShield`
- `0xB35894` — `HSUpdate.exe`

### 2.2. Что читает (по статике)

- путь/наличие `...\HackShield\EHSvc.dll`;
- регион-ключ;
- реестр `HKLM\SOFTWARE\AHNLAB\IOU\HackShield` (в WOW64 — `WOW6432Node`);
- HWID-API: `RegQueryValueExA`, `RegOpenKeyExA`, `Netbios`, `gethostname`, `GetSystemInfo`, `GetDriveTypeA`;
- при обновлении — `HSUpdate.exe` и `%s\%s`;
- лог `*_Hack*.log`.

### 2.3. Что показала динамика

Монитор `hsmon6.dll` внедрён в **момент создания** процесса PID 2796 (вотчер `watchinj.exe`, задержка ~30 мс, до окна/резюма). Лог `logs/hsmon6_2796.log`:

- `CB hook skipped ... bytes=00 00 00` — по адресу `0x731550` в live-процессе **не код**, а нули; ленивый поиск сигнатуры `55 8B EC 83 EC 1C 8B 45 08 89 45 F4 81 7D` по исполняемым страницам **не нашёл** callback;
- `HS_CB` — **0**;
- `HackShield Init Ok` / `HackShield Svr Init Ok` — **0**;
- `EHSvc` / `HSUpdate` в `LOADLIB` — **0**;
- `Netbios` — **0**; `GetDriveTypeA` — **0**; `MachineGuid` — **0**;
- `ODS` — только `Video error - MaxVideoNumber Zero` (D3D9, не fatal);
- `RegQueryValueExA` — только 4 вызова D3D9: `D3DXDoNotMute`, `DisablePSGP`, `DisableD3DXPSGP`, `DisableMMX`;
- `GetSystemInfo` — 59 (D3D9);
- `GetKeyState` — 123, `GetCursorPos` — 20, `PostMessage` — 28 (игровой ввод);
- `SEND/RECV` — есть, но **нет** `0x62`, **нет** длин 342/74.

Ранее, в PID 7756 (рабочий, уже в мире) и PID 2436 (перезапуск), картина та же: `CB hook skipped`, `HS_CB`=0, `EHSvc`/`Netbios`/`GetDriveTypeA`/`MachineGuid`=0, `HS Init Ok`=0.

**Вывод:** в этой сборке HackShield init либо не вызывается, либо его код/данные лежат в shzip-секциях и не используют ожидаемые адреса/API. Фактически наблюдаемое поведение — SDK не активен. Код по `0x731550` в live — нули, значит статический дамп не соответствует live-раскладке shzip; статические RVA — это адреса *дампа*, а не гарантированно live-кода.

### 2.4. Прямой запуск (не из лаунчера)

`RF_Online_4gb.bin`, запущенный напрямую (PID 15044/10624), поднимает окно `RF Online` и пишет `ODS: Video error - MaxVideoNumber Zero`; к серверу не коннектится. Пользователь подтвердил: **без лаунчера игра не подключается**. Поэтому все выводы по init/сети сделаны на процессе, запущенном лаунчером.

---

## 3. `Already Hooked`: что проверяется и что происходит

### 3.1. Код

Callback `0x731550` (dump):

- код `0x10101` → ветка `0x731661`:
  ```
  push [data+0x80]   ; szModuleName
  push [data+0]      ; szFunctionName
  push 0xA6AA60      ; "[HACKSHIELD] Already Hooked"
  call 0x597690
  ```
  Строки `- szFunctionName : %s` (`0xA6AA7C`) и `- szModuleName : %s` (`0xA6AA92`) — рядом, формат собирается логгером.
- код `0x10102` → ветка `0x731686`:
  ```
  flag = *(BYTE*)data
  push flag
  push 0xA6AAA8      ; "[HACKSHIELD] Detect AutoMouse - %d"
  call 0x597690
  if (flag == 3) {
      push 0x8A0; ... ; лог строки
      push 0x1388; push string; call 0x5966D0
  }
  ```
  То есть при `flag==3` — локализованное сообщение/ошибка (0x1388), вероятно MessageBox/выход; при других значениях — только лог.
- Прочие коды (`0x10501`, `0x103xx`, `0x107xx`, `0x109xx`) — другие события/ошибки HackShield.

### 3.2. Список проверяемых функций/модулей

Статически список **не извлечён**: он находится внутри упакованного HackShield SDK в `.gpt0/.gpt2` (shzip), а не в открытом `.rdata`. В дампе видны только формат и callback. Динамически получить список не удалось, потому что callback `0x731550` в live не найден/не вызывался.

### 3.3. Что происходит при обнаружении

По статике: лог `[HACKSHIELD] Already Hooked ...` + имена функции/модуля; для AutoMouse — лог и при `flag==3` сообщение/ошибка. Данных о кике/бане из игры нет; решение принимает сервер (пакет `0x62`) — но в live `0x62` не наблюдался.

### 3.4. Тест «поставить безопасный хук»

В рабочем процессе PID 7756 были установлены IAT-хуки на `RegQueryValueExA`, `Netbios`, `GetSystemInfo`, `GetDriveTypeA`, `GetCursorPos`, `GetAsyncKeyState`, `WSASend/WSARecv`; в PID 2796 — ещё и inline-хуки на `ws2_32!send/recv/WSASend/WSARecv`. Реакции `Already Hooked`/`HS_CB` **не было** (HackShield не активен). Это не доказывает безопасность хука при *активном* HackShield, но доказывает, что в этой сборке он не проверяет.

---

## 4. HWID / VphwID

### 4.1. Что такое VphwID (по статике)

- Строка ` VphwID` находится только в упакованной `.gpt0` дампа по адресу `0x2FADC25`; абсолютных xref в открытом `.text` нет (поиск `60 AA A6 00`, `60 AA 66 00`, `68 60 AA A6 00` — 0).
- В live-памяти рабочего процесса строка `VphwID` **не найдена** (0 совпадений), как и `EHSvc`.
- По смыслу HackShield `VphwID` — «Virtual Physical Hardware ID»: агрегат из физических/виртуальных идентификаторов. Вероятные источники (по импортам и соседним строкам):
  - `RegQueryValueExA` / `RegOpenKeyExA` (MachineGuid и др.);
  - `Netbios` (NCB, имена/адаптеры);
  - `gethostname` (WS2_32);
  - `GetSystemInfo` (CPU/архитектура/страницы);
  - `GetDriveTypeA` (типы дисков);
  - вероятно SMBIOS/WMI, диск, MAC, том, UUID — но в открытом коде это не подтверждено.
- **Это не HWID лаунчера.** Лаунчер отдельно собирает `{hwid, hashes, protover}` (`hwid` — UUID v5 от seed-каталога, `hashes` — из `System\accounts.json`) и шлёт на `wss://auth.cerberus-games.com`; с VphwID игры не смешивать.

### 4.2. Где формируется и куда отправляется (статика)

`CNetMsgProcessor_HackShield`:

- конструктор/база: `0x55CE00`, `0x55CE20`, `0x55CE40` (отправка), `0x55CE70` (анализ серверного пакета), `0x55CF10` (sub 2), `0x55CFB0` (sub 4), `0x55D030` (sub 6), `0x55D050` (ошибки).
- Серверный пакет: `[pkt+2] == 0x62`; подтип `[pkt+3]` = 2/4/6:
  - sub 2 → буфер `0x156` (342) → ответ sub 3;
  - sub 4 → буфер `0x4a` (74) → ответ sub 5;
  - sub 6 → `0x55D030` → `0x535630` (действие/закрытие).
- Исходящие: `0x62` + подтип 3 или 5; длины 342/74. Это и есть контейнер для HWID/ответа HackShield.
- Кодирование/шифрование — внутри `0x75420E` / `0x754179`; в live не проверено.

### 4.3. Живая проверка

В PID 2796 (старт, монитор до окна) и PID 7756:

- `Netbios` — 0 вызовов, `GetDriveTypeA` — 0, `RegQueryValueExA(MachineGuid)` — 0;
- `VphwID` в памяти — 0;
- пакетов `0x62` — 0, длин 342/74 — 0;
- исходящие пакеты игры — короткие (5–95 байт) и выглядят зашифрованными; входящие — с 2-байтовым length и опкодом (0x01/0x02/0x03/0x04/0x08/0x09/0x0a/0x0c/0x65/0x66…), без `0x62`.

**Вывод:** в этой сборке VphwID не формируется/не отправляется (по крайней мере, на старте/в мире). Если сервер когда-то пришлёт `0x62`, обработчик в коде есть, но live-подтверждения нет.

---

## 5. Сеть и `CNetMsgProcessor_HackShield`

### 5.1. Наблюдаемое соединение

- PID 2796: `10.8.1.1:62589 → 168.113.248.36:23445` (`Established`), локальный интерфейс `10.8.1.1` — VPN/TAP; игра шла не через `127.0.0.1` relay.
- PID 7756 (ранее): `127.0.0.1:64856 Established` — relay CEF/профиля.
- `148.113.215.219:443` в живых соединениях не наблюдался; мёртвый хост — не источник текущего трафика.

### 5.2. Протокол (live, `logs/startup_net_2796.txt`)

- Входящие (S→C): 2-байтовый little-endian length, затем опкод/подтип; примеры:
  - `05 00 65 01 00` (len 5, op 0x65),
  - `57 00 01 09 ...` (len 0x57, op 0x01),
  - `14 00 66 02 ...` (len 0x14, op 0x66),
  - `0c 00 04 0a ...` (op 0x04/sub 0x0a),
  - `15 00 04 04 ...` (op 0x04/sub 0x04),
  - `0e 00 04 14 ...`, `0d 00 08 05 ...`, `45 04 0c 09 ...` и т.д.
- Исходящие (C→S): зашифрованы, длины 5–95 (17/25/31/20/29/10/9/5/48/95 …), без явного `0x62`.
- Пакетов `0x62` и длин 342/74 за стартовый обмен **не было**. `CNetMsgProcessor_HackShield` в live не активировался.
- `WSASend/WSARecv/send/recv` ловятся inline-хуками; IAT-хуки не ловили реальные вызовы (сеть идёт через другой модуль/указатель). Это важно: для мониторинга сети нужны inline-хуки, не IAT.

### 5.3. Поведение при недоступности HackShield-сервера

Статически:

- sub 6 (`0x55D030`) вызывает `0x535630` (действие/закрытие);
- `0x55D050` — обработчик кодов ошибок `HackShield Err %x`, сообщения `HS Err 1..4`;
- `0x55D544` — fallback-строка/сообщение.

Живой тест недоступности HS-сервера не делался (в этой сборке HS-пакетов нет). Если сервер пришлёт `0x62`, а HS-сервер недоступен — вероятно сообщение/закрытие, но это не подтверждено.

---

## 6. Матрица «действие → обнаружение → последствия → уверенность»

| Действие | Обнаружение HackShield | Последствия | Доказательство | Уверенность |
|---|---|---|---|---|
| `LoadLibrary` / инъекция `rfspoof.net.dll` | Не обнаружено | Игра работает, кика нет | PID 7756: 95 модулей, `rfspoof.net.dll`; игра в мире; `net_2.log` | Высокая (для этой сборки) |
| Инъекция `hsmon6.dll` + inline-хуки `ws2_32` | Не обнаружено | Игра логинится, сеть идёт, кика нет | PID 2796: `IH install`, `SEND/RECV`, `Established` | Высокая |
| IAT-hook `connect`/`WSAConnect`/`ConnectEx` (`rfspoof`) | Не обнаружено | Прокси работает, `rep=0` | `spoof_2.log`, `net_2.log` | Высокая |
| IAT-hook `RegQueryValueExA` | Не обнаружено | Нет `HS_CB`/`Already Hooked` | `hsmon5_7756`, `hsmon6_2796` | Средняя/высокая (HS не активен) |
| IAT-hook `Netbios`/`gethostname`/`GetSystemInfo`/`GetDriveTypeA` | Не обнаружено | Нет реакции | те же логи | Средняя/высокая |
| Inline-hook `send/recv/WSASend/WSARecv` | Не обнаружено | Сеть работает, кика нет | PID 2796, `startup_net_2796.txt` | Высокая (HS не активен) |
| Спуф HWID (`rfspoof.dll`) | Не обнаружено HackShield | Игра работает (исторически) | `spoof_2.log`, профиль 2 | Высокая |
| Подмена `VphwID` | Не проверено | — | VphwID в live не найден | Низкая |
| Запуск под отладчиком | Не проверено | — | x32dbg не установлен; пользователь разрешил поставить | Низкая |
| Kernel-драйвер / Proxifier / WinDivert | Не проверено | — | не ставились | Низкая |
| Смена заголовка окна | Не проверено | — | нет данных | Низкая |
| Несколько инстансов | Не проверено (HackShield) | — | CERBERUS2 + CERBERUS3 лаунчеры одновременно; игры в 3 не было | Низкая |
| Виртуалка | Не проверено | — | — | Низкая |
| Synthetic mouse/macro | `Detect AutoMouse` = 0 | Нет реакции HS; игра закрылась позже (graceful) | `hsmon6_2796`: `GetKeyState`/`GetCursorPos`/`PostMessage`, `Detect AutoMouse`=0 | Средняя (для HS), низкая для RFOCli/сервера |

Примечание: «Не обнаружено» для HS означает, что HS в этой сборке не подал признаков жизни; это не гарантия для другой сборки/сервера.

---

## 7. Рекомендация для мультиоконного спуфера

### 7.1. Можно ли (а) проксировать игру

**Да.** Текущая схема `rfspoof.net.dll` + relay уже работала: все TCP игры шли через `127.0.0.1:<relay>`, `rep=0`; в новом запуске игра шла через `10.8.1.1 → 168.113.248.36:23445` (VPN/прямое), но HackShield-реакции не было. Для net-only достаточно:
- внедрять `rfspoof.net.dll` в **процесс игры** (и, при необходимости, в дочерние);
- hooks: `connect`, `WSAConnect`, `ConnectEx`, DNS; IAT + inline;
- relay/upstream SOCKS5.

### 7.2. Можно ли (б) спуфить HWID игры

Для **HackShield** в этой сборке — **не требуется**: VphwID не наблюдался, HWID-API HackShield не вызывались. Если сервер/RFOCli всё же требует HWID:
- хуки `RegQueryValueExA` (MachineGuid), `Netbios`, `gethostname`, `GetSystemInfo`, `GetDriveTypeA` — **до окна/резюма**;
- для game HWID использовать отдельный профиль/seed, не смешивать с лаунчерным UUID v5;
- тестировать на CERBERUS3/отдельном профиле, не на рабочем CERBERUS2.

### 7.3. Можно ли (в) и то и другое

**Да**, но тайминг:
1. `CREATE_SUSPENDED` для процесса игры (или вотчер, инжектящий в первые ~30 мс).
2. Внедрить net-DLL + HWID-хуки.
3. Resume.
4. Если HS активен — не ставить новые inline-хуки после его init; лучше до.

**Вывод:** HWID+net в игре возможны, но для этой сборки HS не активен; основной риск — RFOCliMod и серверное поведение, а не HS-тайминг.

---

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
  api-ms-win-crt-*, USER32, WS2_32; `TimeDateStamp=0`.
- `python -m py_compile app.py rfguard.py manualmap.py rfprofiles.py` — OK.
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


---

## Приложение B (восстановленные ключевые выводы HS-логов)

- `hsmon6_2796`: `HS_CB=0`, `HackShield Init Ok=0`, `Svr Init Ok=0`, `EHSvc=0`, `HSUpdate=0`,
  `Netbios=0`, `GetDriveTypeA=0`, `MachineGuid=0`, `Already Hooked=0`, `Detect AutoMouse=0`,
  `SEND len=342=0`, `SEND len=74=0`.
- `ODS`: `Video error - MaxVideoNumber Zero`.
- `CB hook skipped ... bytes=00 00 00`; lazy signature не сработала.
- Сеть: `10.8.1.1:62589 → 168.113.248.36:23445`; пакеты length-prefixed, `0x62` нет;
  HS-сервер не участвует.
- Вывод: HS в этой сборке мёртв; реальный клиентский модуль — `RFOCliMod.vmp.dll`
  (VMP, PDB `RFOCliMod.pdb`, `GAMESPROTECT::cerberus`); `EHSvc/HSUpdate/AhnLab` нет.

> Примечание: при добавлении раздела «Этап 1» часть прежнего длинного приложения B была
> перезаписана; выше — сохранённые ключевые строки из `logs/hsmon6_2796_summary.txt` и
> `logs/startup_net_2796.txt`.

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
