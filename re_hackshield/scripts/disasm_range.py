import sys
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

path=sys.argv[1]; start=int(sys.argv[2],0); end=int(sys.argv[3],0)
pe=pefile.PE(path, fast_load=True); data=pe.__data__; ib=pe.OPTIONAL_HEADER.ImageBase
for s in pe.sections:
    va=ib+s.VirtualAddress
    if va<=start<va+s.SizeOfRawData:
        off=s.PointerToRawData+(start-va)
        blob=data[off:off+(end-start)]
        md=Cs(CS_ARCH_X86, CS_MODE_32)
        for ins in md.disasm(blob, start):
            print("%08X: %-30s %s %s" % (ins.address, ins.bytes.hex(), ins.mnemonic, ins.op_str))
        break
else:
    print("not in section")
