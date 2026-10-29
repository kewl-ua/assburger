import socket, sys, time
sys.path.insert(0, r"C:\SHARE\hwid")
from app import SocksRelay, _split_proxy

proxy = "proxy_user:3P2YiDPElBiXgfHh@66.151.43.88:34728"
r = SocksRelay(proxy, "test")
print("relay port", r.port)

def try_dst(host, port):
    try:
        c = socket.create_connection(("127.0.0.1", r.port), timeout=10)
        c.settimeout(15)
        c.sendall(b"\x05\x01\x00")
        print(" method:", c.recv(2).hex())
        hb = host.encode()
        req = b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + port.to_bytes(2, "big")
        c.sendall(req)
        rep = c.recv(10)
        print(" %s:%d -> reply %s (rep=%d)" % (host, port, rep.hex(), rep[1] if len(rep)>1 else -1))
        c.close()
    except Exception as e:
        print(" %s:%d -> ERR %s" % (host, port, e))

for h,p in [("cerberus-games.com",443), ("92.118.86.158",443), ("89.104.116.214",443), ("example.com",80)]:
    try_dst(h,p)
time.sleep(0.5)
r.close()
