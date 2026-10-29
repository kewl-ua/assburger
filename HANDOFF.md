# Бриф: RF Online / CERBERUS мульти-инстанс HWID-спуфер — что осталось

Ты получаешь проект `C:\SHARE\hwid` (Windows, Python 3, 32-битная DLL на MinGW gcc).
Задача — вернуть проект в полностью рабочее состояние. Ниже контекст по фактам; не переспрашивай очевидное, проверяй по коду и Git.

## Что это за проект

Мульти-инстанс лончер для CEF-лаунчера `CERBERUS-GAMES.exe` (RF Online).
Запускает N изолированных копий, каждая видит поддельное «железо» (имя ПК, серийник тома, MAC, MachineGuid, SMBIOS/BIOS/board/CPU/disk/monitor, RAM, build) и свой SOCKS5-прокси.
Ядро — `rfspoof.dll`, собранная из `spoof.c`: IAT-хуки Win32-API + SOCKS5 в `connect`.

## КРИТИЧНО: в Git лежит РАБОЧАЯ версия, на диске — сломанная переделка

Репозиторий один коммит: `6c966b9` («Initial commit…»). Состояние:

- **Изменены относительно рабочего коммита (сломаны):** `spoof.c`, `build.ps1`, `config.py`, `gui.py`, `start.cmd`, `rfspoof.dll`.
- **НЕ изменены (рабочие):** `launcher.py`, `inject.py`, `hwgen.py`, `realhw.py`, `profiles.example.json`.
- **Вне Git (наши новые, на них всё и сломалось):** `app.py` (one-file переделка ~1500 строк), `profiles_model.py`, `test_config.py`, `test_gui_logic.py`.

**Рабочий `spoof.c` в Git = 1624 строки.** На диске сейчас ~550 строк — урезанная переделка, которая теряет почти всё покрытие. Рабочий `spoof.c` уже реализует: SMBIOS (`GetSystemFirmwareTable`/`NtQuerySystemInformation`), disk serial, мониторы, host, RAM, хуки реестра (`RegQueryValueExW/A` — полностью отвечает сам, БЕЗ записи в HKLM), `GetAdaptersAddresses`, `GetAdaptersInfo`, `connect`, `WSAConnect`, **`ConnectEx` (inline)**, IPv4+IPv6, SOCKS5 c retry и direct-fallback, UDP-детект (`SOCKTYPE==SOCK_DGRAM` → без прокси), построчное чтение cfg через `fopen/fgets` (НЕ `GetPrivateProfile`).

## Как воспроизвести поломку / где искать

1. `git show HEAD:spoof.c` — эталон рабочего ядра. Сравни с текущим `spoof.c`.
2. Проблемы, которые уже подтверждены эмпирически (Procmon/netstat/лог DLL):
   - Реальное имя `DESKTOP-…` и реальный IP утекают: `GetComputerNameExW`, `GetAdaptersAddresses`, `connect` (через `uv_tcp_connect`/ordinal) не покрыты.
   - `connect`/`WSAConnect` импортируются **по ординалу** (ordinal 4 в `ws2_32`), а `patch_iat` урезанной версии пропускал ординальные импорты.
   - Текущая `socks_handshake` шлёт неверный SOCKS5-greeting (`{5,2,2}` — заявлено 2 метода, передан 1 байт) → прокси молчит. Правильно `{5,2,0,2}` или `{5,1,2}`.
   - Неблокирующие сокеты CEF: `recv` возвращает `WSAEWOULDBLOCK`, handshake рвётся (нужен `select`+таймаут; в оригинале это `r_all`/`s_all`).
   - `GetPrivateProfileStringA/IntA` **не читают** cfg без секции `[cfg]` → `net`/`proxy`/все поля возвращались дефолтом. Оригинал читал построчно, поэтому секция не нужна.
   - `MachineGuid` писался в HKLM через `RegSetValueEx` — под не-админским профилем `Access denied (5)`. Оригинал вместо этого хукает `RegQueryValueExW/A` и отдаёт значение сам.
   - Инжект в лаунчер: рабочий поток — start suspended → resume ВСЕХ → ждать окно + settle → инжект; инжект слишком рано роняет CEF.

## Что нужно сделать (по приоритету)

### P0 — восстановить ядро
Проще всего: взять `spoof.c` из HEAD за базу и портировать на него наши полезные добавки (если они нужны — W-хуки, неблокирующая обработка), а не чинить урезанную версию. Убедиться, что собирается `build.ps1` без warning'ов.

### P0 — инъекция и порядок старта
Держать контракт `launcher.py`: `CREATE_SUSPENDED` → resume всех → `wait_windows` → settle → инжект; `--user-data-dir` на инстанс; `SPOOF_CFG` в env (юникод-блок, работает и для `CreateProcessWithLogonW`).

### P0 — решить, что основное: `launcher.py+gui.py` или `app.py`
Сейчас есть два расходящихся варианта. Предпочтительно вернуть модульный (в Git, рабочая база) и удалить/заморозить `app.py`, либо довести `app.py`, но не держать оба. Если `app.py` нужен как «один файл» — он обязан вызывать то же самое поведение.

### P1 — покрыть утечки в лаунчере
`GetComputerNameExW`, `GetAdaptersAddresses` (MAC), `connect`/`WSAConnect` **по ординалам**, `ConnectEx`. Все — с `GetProcAddress` реальных экспортов в `DllMain` и защитой от саморекурсии.

### P1 — cfg
Либо читать построчно как в оригинале (тогда `[cfg]` не нужен, формат совместим со старым `launcher._cfg_text`), либо оставить INI-API и гарантированно писать `[cfg]`. Один формат, без дублей.

### P1 — прокси-надёжность
Правильный greeting, неблокирующий I/O + таймауты, UDP не проксировать, retry, direct-fallback при полном отказе, не проксировать сам адрес прокси и `127.*`.

### P2 — регресс-тесты без игры
32-битный хост-загрузчик (`gcc`, `LoadLibraryA` + вызовы `GetComputerNameExW`/`GetAdaptersAddresses`/`RegQueryValueExW(MachineGuid)`/`connect`) печатает подменённые значения. Сейчас такие тесты жили в `_readtest*.c` — оформить как `tests/`.

## Грабли окружения (проверено)

- `Kill()`/`taskkill` из не-админской сессии НЕ убивают elevated-процессы → остатки держат CEF-профиль и ломают следующий старт. Убивать `taskkill /F` из-под админа и чистить `cef/`.
- Тест-процесс без elevation не пишет в HKLM (для проверки guid это ок — он должен работать через хук, не запись).
- `C:\` из тестового процесса не всегда доступен на запись — DLL-лог писать в папку проекта.
- `IP_ADAPTER_ADDRESSES` поле MAC — `PhysicalAddress`/`PhysicalAddressLength` (не `Address`).
- mingw: `struct timeval`; `#include <winsock2.h>` до `windows.h`; сборка: `-shared -s -O2 -Wno-cpp -Wno-unknown-pragmas -Wno-cast-function-type`.

## Проверка «готово»

1. `pwsh -File build.ps1` — OK, 0 warning.
2. Инстанс стартует, окно живо >15 c, DLL в модулях процесса.
3. Procmon: `GetComputerNameExW`/MAC/`MachineGuid` отдают фейк; в соединениях есть `66.151.43.88` (прокси), реальные IP только через туннель.
4. `RegQueryValueEx(MachineGuid)` = guid из cfg при НЕ-админском профиле.
5. 2+ инстанса параллельно с разными HWID и разными `cef/profile_<id>`, друг другу не мешают.

## Деликатное
- Рабочий прокси в `profiles.json`/cfg: `proxy_user:…@66.151.43.88:34728` (SOCKS5). Прокси иногда отвечает отказом — нужен retry.
- Не трогать реальную систему вне процесса (всё user-mode, IAT, без драйверов).
- `profiles.json` содержит реальные логины/прокси — не логировать в git.
