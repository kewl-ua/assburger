import sys, struct
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

path=sys.argv[1]
targets=[int(x,0) for x in sys.argv[2:]]
pe=pefile.PE(path,fast_load=True); data=pe.__data__; ib=pe.OPTIONAL_HEADER.ImageBase
secs=[]
for s in pe.sections:
    secs.append((s.Name.rstrip(b'\0').decode('latin1'), s.PointerToRawData, s.PointerToRawData+s.SizeOfRawData, s.VirtualAddress, s.Characteristics))

def sec_of_va(va):
    for nm,rs,re_,sva,ch in secs:
        if ib+sva<=va<ib+sva+(re_-rs): return nm,rs,re_,sva,ch
    return None

md=Cs(CS_ARCH_X86,CS_MODE_32)
for t in targets:
    print("### target %08X" % t)
    # direct call rel32
    found=0
    for nm,rs,re_,sva,ch in secs:
        if not (ch & 0x20000000): continue
        blob=data[rs:re_]
        for i in range(len(blob)-5):
            if blob[i]==0xe8:
                rel=struct.unpack_from('<i',blob,i+1)[0]
                va=ib+sva+i
                if (va+5+rel)&0xffffffff==t:
                    print("  call %s @ %08X" % (nm,va)); found+=1
    # pointer in any section
    packed=struct.pack('<I',t)
    for nm,rs,re_,sva,ch in secs:
        blob=data[rs:re_]
        j=0
        while True:
            j=blob.find(packed,j)
            if j<0: break
            print("  ptr  %s @ %08X" % (nm, ib+sva+j)); found+=1; j+=1
    print("  total",found)
