import pefile, re, sys
files=[r"C:\SHARE\CERBERUS\RF_Online.bin", r"C:\SHARE\CERBERUS\RF_Online_4gb.bin", r"C:\SHARE\CERBERUS\CERBERUS-GAMES.exe"]
hw=re.compile(r'(Volume|ComputerName|Adapters|RegQuery|RegOpen|RegGet|Firmware|NtQuerySystem|DeviceIoControl|DisplayDevices|MemoryStatus|SystemInfo|FileInformation|UserName|HostName|gethostname|Wbem|WMI|SetupDi|DeviceRegistry|Processor|BaseBoard|BIOS|SMBIOS|Serial)', re.I)
for f in files:
    print("="*80); print(f)
    try:
        pe=pefile.PE(f, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
        dlls={}
        for entry in getattr(pe,'DIRECTORY_ENTRY_IMPORT',[]):
            dll=entry.dll.decode('latin1','replace')
            names=[]
            for imp in entry.imports:
                nm=imp.name.decode('latin1','replace') if imp.name else '#%d'%imp.ordinal
                names.append(nm)
            dlls[dll]=names
        print("DLLs:", ", ".join(sorted(dlls.keys())))
        for dll,names in sorted(dlls.items()):
            hits=[n for n in names if hw.search(n)]
            if hits: print("  %s: %s" % (dll, ", ".join(hits)))
    except Exception as e:
        print("ERR", e)
