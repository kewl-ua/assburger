import socket, sys, time
sys.path.insert(0, r"C:\SHARE\hwid")
from app import SocksRelay

ips = ["155.212.234.11","186.2.175.174","92.118.86.158","89.104.116.214","31.128.51.158"]
print("=== DIRECT (no proxy) ===")
for ip in ips:
    s=socket.socket(); s.settimeout(6)
    t=time.time()
    try:
        s.connect((ip,443)); print("%-16s OK  %.2fs" % (ip, time.time()-t))
    except Exception as e:
        print("%-16s FAIL %s" % (ip, e))
    s.close()

print("=== VIA PROXY x10 to auth1 ===")
r=SocksRelay("proxy_user:3P2YiDPElBiXgfHh@66.151.43.88:34728","reptest")
def conn(host, port=443):
    c=socket.create_connection(("127.0.0.1",r.port),timeout=10); c.settimeout(20)
    c.sendall(b"\x05\x01\x00"); c.recv(2)
    hb=host.encode(); c.sendall(b"\x05\x01\x00\x03"+bytes([len(hb)])+hb+port.to_bytes(2,"big"))
    rep=c.recv(10); c.close(); return rep[1] if len(rep)>1 else -1
for i in range(10):
    try: print("attempt %d: rep=%d" % (i, conn("auth1.cerberus-games.com")))
    except Exception as e: print("attempt %d: ERR %s" % (i,e))
    time.sleep(0.4)
r.close()
