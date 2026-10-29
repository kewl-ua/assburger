import pefile, re
files=[r"C:\SHARE\hwid\RF_Online_4gb_dump.exe", r"C:\SHARE\hwid\CERBERUS-GAMES_dump.exe"]
hw=re.compile(r'(Volume|ComputerName|Adapters|RegQuery|RegOpen|RegGet|Firmware|NtQuerySystem|DeviceIoControl|DisplayDevices|MemoryStatus|SystemInfo|FileInformation|UserName|HostName|gethostname|Wbem|WMI|SetupDi|DeviceRegistry|Processor|BaseBoard|BIOS|SMBIOS|Serial|Netbios|MAC|Uuid|Disk|Drive)', re.I)
for f in files:
    print("="*80); print(f)
    try:
        pe=pefile.PE(f, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
        dlls=[]
        for entry in getattr(pe,'DIRECTORY_ENTRY_IMPORT',[]):
            dll=entry.dll.decode('latin1','replace')
            names=[(imp.name.decode('latin1','replace') if imp.name else '#%d'%imp.ordinal) for imp in entry.imports]
            dlls.append(dll)
            hits=[n for n in names if hw.search(n)]
            if hits: print("  %-20s %s" % (dll, ", ".join(hits)))
        print("DLLs:", ", ".join(sorted(set(dlls))))
    except Exception as e: print("ERR",e)
