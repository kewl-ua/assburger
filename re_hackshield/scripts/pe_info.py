import sys, math, hashlib, struct, os
import pefile

def entropy(data):
    if not data: return 0.0
    c=[0]*256
    for b in data: c[b]+=1
    e=0.0
    for n in c:
        if n:
            p=n/len(data); e-=p*math.log2(p)
    return e

for path in sys.argv[1:]:
    print("="*100)
    print(path, os.path.getsize(path), "bytes")
    try:
        pe=pefile.PE(path, fast_load=True)
    except Exception as ex:
        print("PE parse error:", ex); continue
    pe.parse_data_directories(directories=[
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT'],
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE'],
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_LOAD_CONFIG'],
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_SECURITY'],
    ])
    m=pe.FILE_HEADER.Machine
    print("machine=%#x (%s) chars=%#x  TimeDateStamp=%#x  SizeOfImage=%#x  ImageBase=%#x" % (
        m, {0x14c:'i386',0x8664:'amd64',0x1c0:'arm'}.get(m,'?'),
        pe.FILE_HEADER.Characteristics, pe.FILE_HEADER.TimeDateStamp,
        pe.OPTIONAL_HEADER.SizeOfImage, pe.OPTIONAL_HEADER.ImageBase))
    print("Subsystem=%d DllCharacteristics=%#x CheckSum=%#x" % (pe.OPTIONAL_HEADER.Subsystem, pe.OPTIONAL_HEADER.DllCharacteristics, pe.OPTIONAL_HEADER.CheckSum))
    print("Sections:")
    print("  %-10s %-10s %-10s %-10s %-8s %-8s" % ("name","VA","VSize","RawSize","Entropy","Flags"))
    for s in pe.sections:
        nm=s.Name.rstrip(b'\0').decode('latin1')
        print("  %-10s %#-10x %#-10x %#-10x %-8.3f %#x" % (nm, s.VirtualAddress, s.Misc_VirtualSize, s.SizeOfRawData, entropy(s.get_data()), s.Characteristics))
    print("Overlay:", len(pe.get_overlay_data_start_offset() and pe.__data__[pe.get_overlay_data_start_offset():] or b''))
    print("Imports:")
    if hasattr(pe,'DIRECTORY_ENTRY_IMPORT'):
        for d in pe.DIRECTORY_ENTRY_IMPORT:
            names=[]
            for imp in d.imports:
                names.append((imp.name.decode() if imp.name else "ord#%d"%imp.ordinal))
            print("  %s: %s" % (d.dll.decode(), ", ".join(names)))
    else:
        print("  none")
    print("Exports:")
    if hasattr(pe,'DIRECTORY_ENTRY_EXPORT'):
        exps=pe.DIRECTORY_ENTRY_EXPORT.symbols
        print("  count=%d" % len(exps))
        for e in exps[:200]:
            print("    %#x %s ord=%s" % (e.address, e.name.decode() if e.name else '', e.ordinal))
    else:
        print("  none")
    print("Security dir: %#x size=%#x" % (pe.OPTIONAL_HEADER.DATA_DIRECTORY[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_SECURITY']].VirtualAddress,
        pe.OPTIONAL_HEADER.DATA_DIRECTORY[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_SECURITY']].Size))
    print("SHA256:", hashlib.sha256(open(path,'rb').read()).hexdigest())
