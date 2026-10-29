import sys, re, struct, json, os
import pefile

KEYWORDS = [
    b'HackShield', b'HACKSHIELD', b'Hack Shield', b'AutoMouse', b'Already Hooked',
    b'VphwID', b'VPHWID', b'EHSvc', b'HSUpdate', b'AhnLab', b'AHNLAB',
    b'IOU', b'HShield', b'hslog', b'HSLog', b'CHackShield', b'CKorHackShield',
    b'HackShieldAction', b'CNetMsgProcessor_HackShield', b'Detect AutoMouse',
    b'szFunctionName', b'szModuleName', b'HSAddress', b'HShield', b'XignCode',
]

def iter_strings(data, minlen=4, utf16=False):
    if not utf16:
        pat = re.compile(rb'[\x20-\x7e]{%d,}' % minlen)
        for m in pat.finditer(data):
            yield m.start(), m.group().decode('latin1'), len(m.group())
    else:
        pat = re.compile((rb'(?:[\x20-\x7e]\x00){%d,}' % minlen))
        for m in pat.finditer(data):
            raw = m.group()
            yield m.start(), raw.decode('utf-16le', 'replace'), len(raw)//2

def va_for(pe, off):
    for s in pe.sections:
        if s.PointerToRawData <= off < s.PointerToRawData + s.SizeOfRawData:
            return pe.OPTIONAL_HEADER.ImageBase + s.VirtualAddress + (off - s.PointerToRawData), s.Name.rstrip(b'\0').decode('latin1')
    return None, None

def main(path, outpath):
    pe = pefile.PE(path, fast_load=True)
    data = pe.__data__
    hits = []
    for utf16 in (False, True):
        for off, s, l in iter_strings(data, 4, utf16):
            if any(k.decode('latin1').lower() in s.lower() for k in [b'HackShield', b'AutoMouse', b'Already Hooked', b'VphwID', b'EHSvc', b'HSUpdate', b'AhnLab', b'IOU', b'CHackShield', b'CNetMsgProcessor', b'HSAddress', b'HShield', b'szFunctionName', b'XignCode']):
                va, sec = va_for(pe, off)
                hits.append(dict(off=off, va=va, sec=sec, utf16=utf16, s=s))
    hits.sort(key=lambda x: (x['va'] if x['va'] else 0))
    with open(outpath, 'w', encoding='utf-8') as f:
        for h in hits:
            f.write("%08X off=%08X %-7s %s %s\n" % (h['va'] or 0, h['off'], h['sec'] or '-', 'U16' if h['utf16'] else 'A', h['s']))
    print("hits", len(hits), "->", outpath)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
