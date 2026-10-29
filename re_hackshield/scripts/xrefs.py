import sys, struct, json
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

def find_all(hay, needle):
    out=[]; i=0
    while True:
        j=hay.find(needle, i)
        if j<0: break
        out.append(j); i=j+1
    return out

def main(path, targets):
    pe=pefile.PE(path, fast_load=True)
    data=pe.__data__
    ib=pe.OPTIONAL_HEADER.ImageBase
    secs=[]
    for s in pe.sections:
        nm=s.Name.rstrip(b'\0').decode('latin1')
        secs.append((nm, s.PointerToRawData, s.PointerToRawData+s.SizeOfRawData, s.VirtualAddress, s.Characteristics))
    md=Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail=True
    res={}
    for tname,tva in targets:
        packed=struct.pack('<I', tva & 0xffffffff)
        hits=[]
        for nm,rs,re_,va,ch in secs:
            if re_<=rs: continue
            blob=data[rs:re_]
            for off in find_all(blob, packed):
                hva=ib+va+off
                hits.append((nm,hva,off+rs))
        res[tname]=hits
        print("### %s VA=%08X hits=%d" % (tname,tva,len(hits)))
        for nm,hva,foff in hits:
            print("  %s VA=%08X fileoff=%08X" % (nm,hva,foff))
            # disassemble window before/after in that section
            sm=[s for s in secs if s[0]==nm][0]
            sstart=sm[1]
            start=max(sstart, foff-24); end=min(sm[2], foff+40)
            code=data[start:end]
            for ins in md.disasm(code, ib+sm[3]+(start-sstart)):
                mark='  >>' if ins.address <= hva < ins.address+ins.size else '    '
                print("%s %08X: %-24s %s %s" % (mark, ins.address, ins.bytes.hex(), ins.mnemonic, ins.op_str))
    return res

if __name__=='__main__':
    path=sys.argv[1]
    targets=[]
    for a in sys.argv[2:]:
        n,v=a.split('=')
        targets.append((n,int(v,0)))
    main(path,targets)
