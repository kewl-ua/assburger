import socket, sys, time
sys.path.insert(0, r"C:\SHARE\hwid")
from app import SocksRelay
r=SocksRelay("USER:PASS@HOST:PORT","diag2")
def test(host,port):
    try:
        c=socket.create_connection(("127.0.0.1",r.port),timeout=10); c.settimeout(20)
        c.sendall(b"\x05\x01\x00"); c.recv(2)
        hb=host.encode(); c.sendall(b"\x05\x01\x00\x03"+bytes([len(hb)])+hb+port.to_bytes(2,"big"))
        rep=c.recv(10); c.close(); print("%-28s rep=%d" % (host+":"+str(port), rep[1] if len(rep)>1 else -1))
    except Exception as e: print(host,port,"ERR",e)
for h,p in [("185.149.147.195",15666),("95.213.143.206",11031),("104.26.0.92",443),("cerberus-games.com",443),("auth1.cerberus-games.com",443),("example.com",80)]:
    test(h,p); time.sleep(0.3)
r.close()
