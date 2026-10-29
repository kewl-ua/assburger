import socket, ssl, sys, time
sys.path.insert(0, r"C:\SHARE\hwid")
from app import SocksRelay

PROXY = "USER:PASS@HOST:PORT"
r = SocksRelay(PROXY, "newproxy")
print("relay port", r.port)

def socks_connect(host, port=443, timeout=20):
    c = socket.create_connection(("127.0.0.1", r.port), timeout=timeout)
    c.settimeout(timeout)
    c.sendall(b"\x05\x01\x00")
    m = c.recv(2)
    if m != b"\x05\x00":
        raise OSError("method reply %r" % m)
    hb = host.encode()
    c.sendall(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + port.to_bytes(2, "big"))
    rep = c.recv(10)
    if len(rep) < 2:
        raise OSError("short reply %r" % rep)
    return c, rep[1], rep

def test(host, port=443, tls=False, tries=1):
    for i in range(tries):
        t = time.time()
        try:
            c, rep, raw = socks_connect(host, port)
            if rep != 0:
                print("%-30s rep=%d (%.2fs) %s" % (host, rep, time.time()-t, raw.hex()))
                c.close(); time.sleep(0.3); continue
            extra = ""
            if tls:
                ctx = ssl.create_default_context()
                s = ctx.wrap_socket(c, server_hostname=host)
                extra = " TLS=%s" % (s.version(),)
                s.close()
            else:
                c.close()
            print("%-30s rep=0 OK (%.2fs)%s" % (host, time.time()-t, extra))
            return True
        except Exception as e:
            print("%-30s ERR %s (%.2fs)" % (host, e, time.time()-t))
            time.sleep(0.3)
    return False

for h in ["cerberus-games.com","auth.cerberus-games.com","auth1.cerberus-games.com","example.com"]:
    test(h, 443, tls=True, tries=1)
print("=== auth1 x10 ===")
ok=0
for i in range(10):
    if test("auth1.cerberus-games.com", 443, tls=False, tries=1): ok+=1
    time.sleep(0.3)
print("auth1 success", ok, "/10")
time.sleep(0.5); r.close()
