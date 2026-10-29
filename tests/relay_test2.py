import socket, sys, time
sys.path.insert(0, r"C:\SHARE\hwid")
from app import SocksRelay
r = SocksRelay("proxy_user:3P3YiDPElBiXgfHh@66.151.43.88:34728".replace("3P3","3P2"), "test2")
print("port", r.port)
def try_dst(host, port):
    try:
        c = socket.create_connection(("127.0.0.1", r.port), timeout=10); c.settimeout(20)
        c.sendall(b"\x05\x01\x00"); c.recv(2)
        hb=host.encode(); c.sendall(b"\x05\x01\x00\x03"+bytes([len(hb)])+hb+port.to_bytes(2,"big"))
        rep=c.recv(10); print("%s -> rep=%d %s" % (host, rep[1] if len(rep)>1 else -1, rep.hex())); c.close()
    except Exception as e: print("%s ERR %s" % (host,e))
for h in ["auth1.cerberus-games.com","auth.cerberus-games.com","31.128.51.158","186.2.175.174","92.118.86.158"]:
    try_dst(h,443)
time.sleep(.5); r.close()
