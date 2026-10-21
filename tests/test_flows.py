"""Every host flow the guide describes, end to end in a temp sandbox (no systemd).

init for every type (rooms with extra rooms, mail, directory), .sesh make / import / skip,
root sign, install-delegation, run, status, link, directory-entry + directory-submit,
mail --closed / --open, upgrade.  With SRNET_CLIENT pointing at an SRNet-Desktop checkout
(default ../SRNet-Desktop), the real client also joins, reads the directory, uses mail, lists
and pays for a USDC item in a store, and uploads and opens files on a file drop."""
import json, os, signal, socket, subprocess, sys, time, unittest, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.dirname(HERE)
sys.path[:0] = [PACK, HERE, os.path.join(PACK, "bin")]
from helpers import tmpdir  # noqa: E402
import mbfmt as F  # noqa: E402
from typed import joins as J  # noqa: E402
from typed.record import KIND_TYPES, make_record  # noqa: E402
import srnet_host as S  # noqa: E402
from typed.sync import submit  # noqa: E402

CLI = os.path.join(PACK, "bin", "srnet_host.py")
CLIENT = os.environ.get("SRNET_CLIENT") or os.path.join(os.path.dirname(PACK), "SRNet-Desktop")
HAVE_CLIENT = os.path.isfile(os.path.join(CLIENT, "snapps", "typed", "core.py"))


def run(*a, ok=True):
    r = subprocess.run([sys.executable, CLI, *a], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=120)
    if ok and r.returncode:
        raise AssertionError(" ".join(a) + "\n" + r.stderr + r.stdout)
    return r


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_up(port, path, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    raise AssertionError(f"port {port}{path} never came up")


class Flows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tmpdir()
        run("root", "init", "--dir", f"{cls.t}/root")
        cls.pin = open(f"{cls.t}/root/root.pin").read().strip()
        cls.procs, cls.hosts = [], {}
        from cryptography.hazmat.primitives import serialization as ser
        k = F.new_key()  # a vanity-style key file to import: 64-byte seed||pub hex
        seed = k.private_bytes(ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption())
        pub = k.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
        open(f"{cls.t}/vanity.key", "w").write((seed + pub).hex())
        cls.vanity = F.zb32(pub) + ".sesh"
        plan = [("board", "news", ["--sesh", "new"]),
                ("store", "shop", ["--sesh-import", f"{cls.t}/vanity.key"]),
                ("wiki", "wiki", ["--sesh", "skip"]),
                ("rooms", "lobby", ["--room", "hikers", "--room", "maps"]),
                ("files", "files", []), ("people", "people", []),
                ("directory", "directory", []), ("mail", "post", [])]
        for typ, name, extra in plan:
            cls.hosts[typ] = cls.setup_host(typ, name, extra)

    @classmethod
    def setup_host(cls, typ, name, extra):
        pre, port = f"{cls.t}/{name}", free_port()
        run("init", "--type", typ, "--name", name, "--prefix", pre, "--port", str(port), *extra)
        run("root", "sign", f"{pre}/request.json", "--root-key", f"{cls.t}/root/root.key",
            "--days", "90", "--yes", "--out", f"{pre}.delegation.json")
        r = run("install-delegation", f"{pre}.delegation.json", "--prefix", pre, "--no-systemd")
        h = {"pre": pre, "port": port, "name": name, "typ": typ, "install_out": r.stdout}
        cls.start(h)
        return h

    @classmethod
    def start(cls, h):
        p = subprocess.Popen([sys.executable, CLI, "run", "--prefix", h["pre"]],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        h["proc"] = p
        cls.procs.append(p)
        wait_up(h["port"], {"board": "/v1/info", "mail": "/v1/mail/info"}.get(h["typ"], f"/c/{h['name']}/v1/info"))

    @classmethod
    def stop(cls, h):
        os.killpg(h["proc"].pid, signal.SIGTERM)
        h["proc"].wait(10)

    @classmethod
    def tearDownClass(cls):
        for p in cls.procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
                p.wait(10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass

    def status(self, typ):
        r = run("status", "--prefix", self.hosts[typ]["pre"], ok=False)
        return r.returncode, json.loads(r.stdout)

    def test_01_status_every_role(self):
        for typ in self.hosts:
            code, st = self.status(typ)
            self.assertEqual((code, st["http"]), (0, "ok"), (typ, st))
            self.assertEqual(st["root_pin"], self.pin)
            self.assertGreater(st["delegation_days_left"], 89)
            self.assertEqual(st["pack"], S.VERSION)
        self.assertEqual(self.status("rooms")[1]["collections"], ["lobby", "hikers", "maps"])
        self.assertEqual(self.status("mail")[1]["mail_signup"], "open")

    def test_02_sesh_make_import_skip(self):
        st = self.status("board")[1]
        self.assertTrue(st["sesh"].endswith(".sesh"))
        self.assertEqual(st["links"], [f"srnet://{st['sesh']}/board/news#root={self.pin}"])
        self.assertEqual(self.status("store")[1]["sesh"], self.vanity)
        self.assertIsNone(self.status("wiki")[1]["sesh"])
        self.assertFalse(os.path.exists(f"{self.hosts['board']['pre']}/sesh/router.ini"))
        self.assertFalse(os.path.exists(f"{self.hosts['board']['pre']}/sesh/ENABLE.txt"))
        self.assertIn("invite link: srnet://", self.hosts["board"]["install_out"])
        for ln in st["links"] + self.status("store")[1]["links"]:
            J.parse(ln)  # the client accepts these links

    def test_03_every_link_probes_and_verifies(self):
        for typ, h in self.hosts.items():
            if typ == "mail":
                continue
            local = f"127.0.0.1:{h['port']}"
            out = run("link", "--prefix", h["pre"]).stdout.split()
            self.assertTrue(out)
            for ln in out:
                l = J.parse(ln)
                self.assertEqual(l["root"], self.pin)
                pr = J.probe(local, l["kind"], l["name"])  # what the client's join sheet does
                self.assertEqual(pr["root"], self.pin, (typ, ln))
        names = sorted(c["name"] for c in J.offered(f"127.0.0.1:{self.hosts['rooms']['port']}"))
        self.assertEqual(names, ["hikers", "lobby", "maps"])

    def test_04_directory_entry_and_submit(self):
        d = self.hosts["directory"]
        hikers = J.make(f"127.0.0.1:{self.hosts['rooms']['port']}", "room", "hikers", self.pin)
        out = f"{self.t}/entry.json"
        run("root", "directory-entry", "--link", hikers, "--title", "Hikers", "--desc", "Weekend walks",
            "--root-key", f"{self.t}/root/root.key", "--out", out)
        r = run("directory-submit", out, "--to", f"http://127.0.0.1:{d['port']}/c/directory")
        self.assertIn("Listed", r.stdout)
        other = J.make(f"127.0.0.1:{self.hosts['rooms']['port']}", "room", "hikers", "cd" * 32)
        r = run("root", "directory-entry", "--link", other, "--title", "x", "--root-key",
                f"{self.t}/root/root.key", "--out", f"{self.t}/bad.json", ok=False)
        self.assertNotEqual(r.returncode, 0)

    def test_05_mail_closed_open(self):
        h = self.hosts["mail"]
        lk, url = run("link", "--prefix", h["pre"]).stdout.split()
        self.assertEqual(url, f"http://127.0.0.1:{h['port']}")
        self.assertEqual(lk, f"srnet://127.0.0.1:{h['port']}/mail/post#root={self.pin}")
        pr = J.probe(f"127.0.0.1:{h['port']}", "mail", "post")  # the client's "Add mail host" check
        self.assertEqual((pr["root"], pr["url"]), (self.pin, url))
        e = f"{self.t}/mail-entry.json"  # mail hosts can be listed in a directory
        run("root", "directory-entry", "--link", lk, "--title", "Free mail", "--root-key",
            f"{self.t}/root/root.key", "--out", e)
        d = self.hosts["directory"]
        self.assertIn("Listed", run("directory-submit", e, "--to", f"http://127.0.0.1:{d['port']}/c/directory").stdout)
        info = lambda: json.dumps(json.load(urllib.request.urlopen(f"http://127.0.0.1:{h['port']}/v1/mail/info")))
        self.assertIn('"open_registration": true', info())
        run("mail", "--prefix", h["pre"], "--closed")
        self.stop(h); self.start(h)
        self.assertIn('"open_registration": false', info())
        self.assertEqual(self.status("mail")[1]["mail_signup"], "closed")
        run("mail", "--prefix", h["pre"], "--open")
        self.stop(h); self.start(h)
        self.assertIn('"open_registration": true', info())
        self.assertEqual(self.status("mail")[1]["mail_signup"], "open")

    def test_06_upgrade_keeps_keys_and_data(self):
        h = self.hosts["wiki"]
        base = f"http://127.0.0.1:{h['port']}/c/wiki"
        env = make_record(F.new_key(), KIND_TYPES["wiki"], "wiki", "wiki.page",
                          {"slug": "hello", "title": "Hello"}, [], pow_bits=16)
        self.assertTrue(submit([base], env).get("ok"))
        hk = open(f"{h['pre']}/data/host.key", "rb").read()
        cfgp = f"{h['pre']}/host.json"
        cfg = json.load(open(cfgp)); cfg["pack"] = "0.2.0"; open(cfgp, "w").write(json.dumps(cfg))
        r = run("upgrade", "--prefix", h["pre"])
        self.assertIn(f"0.2.0 -> {S.VERSION}", r.stdout)
        self.assertTrue(os.path.isdir(f"{h['pre']}/app.prev"))
        self.stop(h); self.start(h)
        self.assertEqual(open(f"{h['pre']}/data/host.key", "rb").read(), hk)
        code, st = self.status("wiki")
        self.assertEqual((code, st["pack"], st["root_pin"]), (0, S.VERSION, self.pin))
        self.assertIn(env["sig"], urllib.request.urlopen(base + "/v1/log?since=0").read().decode())
        cfg = json.load(open(cfgp)); cfg["pack"] = "9.0.0"; open(cfgp, "w").write(json.dumps(cfg))
        self.assertNotEqual(run("upgrade", "--prefix", h["pre"], ok=False).returncode, 0)
        cfg["pack"] = "0.3.0"; open(cfgp, "w").write(json.dumps(cfg))

    @unittest.skipUnless(HAVE_CLIENT, "SRNet-Desktop checkout not found")
    def test_07_real_client_join_directory_mail(self):
        self.test_04_directory_entry_and_submit()
        code = r'''
import json, sys, os
sys.path[:0] = [os.path.join(sys.argv[1], "snapps")]
from typed.core import Core
a = json.loads(sys.argv[2])
c = Core(a["dir"], {"mail": {"hosts": [a["mail"]]}}, autoconfirm=True)
out = {}
pv = c.join_preview(a["rooms"]); out["preview"] = [pv["name"], pv["root"], pv["first_seen"]]
out["join"] = c.join(a["rooms"])["id"]
c.join(a["dirlink"])
out["entries"] = [e["title"] for e in c.view("directory")["view"]["entries"]]
out["sidebar"] = sorted(i["id"] for g in c.sidebar()["groups"] for i in g["items"])
out["share_root"] = c.share(out["join"])["link"].split("#root=")[1]
c.mail.register()
out["mail_link"] = c.mail.link().startswith("srnet://mail/")
b = Core(a["dir"] + "-b", {"mail": {"hosts": [a["mail"]]}}, autoconfirm=True); b.mail.register()
b.mail.send(c.mail.link(), "hi", "hello from b")
out["fetched"] = c.mail.fetch()["new"]
out["requests"] = len(c.mail.folder("requests"))
print(json.dumps(out))
'''
        rooms = f"127.0.0.1:{self.hosts['rooms']['port']}"
        args = {"dir": f"{self.t}/client", "mail": f"http://127.0.0.1:{self.hosts['mail']['port']}",
                "rooms": J.make(rooms, "room", "hikers", self.pin),
                "dirlink": J.make(f"127.0.0.1:{self.hosts['directory']['port']}", "directory", "directory", self.pin)}
        r = subprocess.run([sys.executable, "-c", code, CLIENT, json.dumps(args)], capture_output=True,
                           text=True, timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["preview"], ["hikers", self.pin, True])
        self.assertIn("Hikers", out["entries"])
        self.assertIn("hikers", out["sidebar"])
        self.assertEqual(out["share_root"], self.pin)
        self.assertTrue(out["mail_link"])
        self.assertEqual((out["fetched"], out["requests"]), (1, 1))

    def test_08_front_one_name_for_all_roles(self):
        from cryptography.hazmat.primitives import serialization as ser
        k = F.new_key()
        seed = k.private_bytes(ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption())
        pub = k.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
        kf = f"{self.t}/front-src.key"
        open(kf, "w").write((seed + pub).hex() + "\n")
        name = F.zb32(pub) + ".sesh"
        roles = [self.hosts[t]["pre"] for t in ("rooms", "directory", "files", "mail")]
        hargs = [x for p in roles for x in ("--host", p)]
        r = run("front", "--prefix", f"{self.t}/front", "--sesh-import", kf, "--no-systemd", *hargs)
        self.assertIn(f".sesh name: {name}", r.stdout)
        self.assertEqual(open(kf).read(), open(f"{self.t}/front/identity.key").read())  # copied
        self.assertTrue(os.path.exists(kf))  # never moved
        ini = open(f"{self.t}/front/router.ini").read()
        self.assertIn(f"keyfile={self.t}/front/identity.key", ini)
        routes = json.load(open(f"{self.t}/front/routes.json"))["routes"]
        self.assertEqual(sorted(routes), ["/c/directory", "/c/files", "/c/hikers", "/c/lobby", "/c/maps", "/v1/mail"])
        self.assertIn(f"srnet://{name}/room/lobby#root={self.pin}", r.stdout)
        self.assertIn(f"srnet://{name}/mail/post#root={self.pin}", r.stdout)
        other = f"{self.t}/other.key"  # a different key never overwrites the stored one
        k2 = F.new_key()
        open(other, "w").write((k2.private_bytes(ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption())
                                + k2.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)).hex())
        self.assertNotEqual(run("front", "--prefix", f"{self.t}/front", "--sesh-import", other,
                                "--no-systemd", *hargs, ok=False).returncode, 0)
        r = run("front", "--prefix", f"{self.t}/front2", "--sesh-import", kf, "--no-systemd",
                "--host", self.hosts["board"]["pre"], *hargs, ok=False)   # a board can't share a name
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("only --host", r.stderr)
        port = free_port()
        p = subprocess.Popen([sys.executable, f"{self.t}/front/srnet_front.py", "--routes",
                              f"{self.t}/front/routes.json", "--bind", "127.0.0.1", "--port", str(port)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        wait_up(port, "/v1/collections")
        host = f"127.0.0.1:{port}"
        self.assertEqual(sorted(c["name"] for c in J.offered(host)), ["directory", "files", "hikers", "lobby", "maps"])
        for kind, coll in (("room", "lobby"), ("room", "maps"), ("directory", "directory"), ("drop", "files")):
            self.assertEqual(J.probe(host, kind, coll)["root"], self.pin, coll)
        self.assertEqual(J.probe(host, "mail", "post")["url"], f"http://{host}")
        self.assertEqual(urllib.request.urlopen(f"http://{host}/v1/mail/info").status, 200)
        with self.assertRaises(Exception):
            urllib.request.urlopen(f"http://{host}/c/nope/v1/info")

    def test_08b_front_for_a_board_alone(self):
        h = self.hosts["board"]
        kf = f"{h['pre']}/sesh/identity.key"   # the key init made
        name = S.load_cfg(h["pre"])["sesh"]["name"]
        fp = f"{self.t}/front-board"
        r = run("front", "--prefix", fp, "--sesh-import", kf, "--host", h["pre"], "--no-systemd")
        self.assertIn(f".sesh name: {name}", r.stdout)
        self.assertEqual(json.load(open(f"{fp}/routes.json"))["routes"], {"/": h["port"]})
        self.assertNotEqual(run("front", "--prefix", fp, "--host", h["pre"], "--route", "/relayer=8645",
                                "--no-systemd", ok=False).returncode, 0)
        port = free_port()
        p = subprocess.Popen([sys.executable, f"{fp}/srnet_front.py", "--routes", f"{fp}/routes.json",
                              "--bind", "127.0.0.1", "--port", str(port)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        wait_up(port, "/v1/info")
        direct = urllib.request.urlopen(f"http://127.0.0.1:{h['port']}/v1/info").read()
        self.assertEqual(urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/info").read(), direct)
        self.assertEqual(self.status("board")[1]["sesh"], name)

    def test_09_front_extra_route_and_forwarded_for(self):
        import http.server
        import threading
        seen = []

        class Echo(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(n)
                seen.append((self.path, self.headers.get("X-Forwarded-For")))
                b = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def log_message(self, *a):
                pass
        echo = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Echo)
        threading.Thread(target=echo.serve_forever, daemon=True).start()
        self.addCleanup(echo.shutdown)
        kf = f"{self.t}/front-src.key"
        roles = [self.hosts[t]["pre"] for t in ("rooms", "mail")]
        hargs = [x for p in roles for x in ("--host", p)]
        for bad in ("/c/x=1", "/v1/mail=1", "relayer=1", "/relayer=0", "/relayer"):
            self.assertNotEqual(run("front", "--prefix", f"{self.t}/front3", "--sesh-import", kf, "--no-systemd",
                                    *hargs, "--route", bad, ok=False).returncode, 0, bad)
        run("front", "--prefix", f"{self.t}/front3", "--sesh-import", kf, "--no-systemd", *hargs,
            "--route", f"/relayer={echo.server_address[1]}")
        routes = json.load(open(f"{self.t}/front3/routes.json"))["routes"]
        self.assertEqual(routes["/relayer"], echo.server_address[1])
        port = free_port()
        p = subprocess.Popen([sys.executable, f"{self.t}/front3/srnet_front.py", "--routes",
                              f"{self.t}/front3/routes.json", "--bind", "127.0.0.1", "--port", str(port)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        wait_up(port, "/v1/collections")
        q = urllib.request.Request(f"http://127.0.0.1:{port}/relayer/fund", data=b"{}",
                                   headers={"X-Forwarded-For": "6.6.6.6", "Content-Type": "application/json"})
        self.assertEqual(urllib.request.urlopen(q).status, 200)
        self.assertEqual(seen, [("/relayer/fund", "127.0.0.1")])  # the caller's address, never the spoofed one

    def test_10_store_takes_direct_usdc_listings(self):
        seller = F.new_key()
        h = self.setup_host("store", "market", ["--seller", F.pub_hex(seller), "--sesh", "skip"])
        base = f"http://127.0.0.1:{h['port']}/c/market"
        pay_to = "0x" + "12" * 20

        def listing(body):
            return submit([base], make_record(seller, KIND_TYPES["shop"], "market", "shop.listing",
                                              dict({"title": "Sticker pack", "price": "1.50"}, **body),
                                              [], pow_bits=16))
        r = listing({"currency": "USDC", "chain_id": 42161, "pay_to": pay_to})
        self.assertTrue(r.get("ok"), r)  # real USDC on Arbitrum One
        self.assertTrue(listing({"currency": "USDC", "chain_id": 8453, "pay_to": pay_to}).get("ok"))
        r = listing({"currency": "USDC", "chain_id": 1, "pay_to": pay_to})
        self.assertFalse(r.get("ok"))
        self.assertIn("Arbitrum One", r.get("error", ""))
        r = listing({"currency": "SRNET", "vendor_id": "0x" + "ab" * 32})
        self.assertEqual(r.get("error"), "seller needs to update")
        r = listing({"currency": "ETH", "chain_id": 42161, "pay_to": pay_to})
        self.assertEqual(r.get("error"), "ETH payments are testnet-only")

    @unittest.skipUnless(HAVE_CLIENT, "SRNet-Desktop checkout not found")
    def test_11_real_client_store_and_file_drop(self):
        seed = os.urandom(32)
        seller = F.key_from_seed(seed)
        h = self.setup_host("store", "bazaar", ["--seller", F.pub_hex(seller), "--sesh", "skip"])
        os.makedirs(f"{self.t}/seller-client", exist_ok=True)
        with open(f"{self.t}/seller-client/author.key", "wb") as f:
            f.write(seed)
        code = r'''
import json, sys, os
sys.path[:0] = [os.path.join(sys.argv[1], "snapps")]
from typed.core import Core
a = json.loads(sys.argv[2])
s = Core(a["seller"], {}, autoconfirm=True)
b = Core(a["buyer"], {}, autoconfirm=True)
out = {}
def done(c, r):
    return (r.get("result") or c.confirm(r["token"])).get("ok")
for c in (s, b):
    c.join(a["store"]); c.join(a["files"])
d = s.draft("bazaar", "shop.listing", {"title": "Sticker pack", "price": "1.50", "currency": "USDC",
                                       "chain_id": 42161, "pay_to": a["pay_to"]}, [])
out["listed"] = done(s, d)
b.sync("bazaar")
ls = b.view("bazaar")["view"]["listings"]
out["payable"] = [(l["title"], l["payable"], l["currency"], l["chain_id"]) for l in ls]
sheet = b.pay_draft("bazaar", ls[0]["id"])
out["sheet"] = [sheet["sheet"]["network"], sheet["sheet"]["to"], sheet["sheet"]["token_address"],
                sheet["sheet"]["amount"].startswith("1.50")]
o = b.pay_order(sheet["token"], "0x" + "cd" * 32)
out["ordered"] = done(b, o)
s.sync("bazaar")
orders = s.view("bazaar")["view"]["listings"][0].get("orders", [])
out["orders"] = [(x["chain_id"], x["tx"][:6], x["amount"] == sheet["sheet"]["amount"]) for x in orders]
data = b"meeting notes\n" * 50
for mode in ("gated", "link", "plain"):
    u = s.upload("files", data, mode + ".txt", "text/plain", note=mode, mode=mode)
    assert done(s, u), u
s.sync("files"); b.sync("files")
items = {i["note"]: i for i in b.view("files")["view"]["items"]}
out["drop"] = sorted((n, i["encrypted"], i["can_open"]) for n, i in items.items())
out["open_link"] = b.open_link(s.share_link("files", items["link"]["id"])["link"])[0] == data
out["open_plain"] = b.open_file("files", items["plain"]["id"])[0] == data
out["owner_opens_gated"] = s.open_file("files", items["gated"]["id"])[0] == data
print(json.dumps(out))
'''
        pay_to = "0x" + "12" * 20
        args = {"seller": f"{self.t}/seller-client", "buyer": f"{self.t}/buyer-client", "pay_to": pay_to,
                "store": J.make(f"127.0.0.1:{h['port']}", "shop", "bazaar", self.pin),
                "files": J.make(f"127.0.0.1:{self.hosts['files']['port']}", "drop", "files", self.pin)}
        r = subprocess.run([sys.executable, "-c", code, CLIENT, json.dumps(args)], capture_output=True,
                           text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(out["listed"])
        self.assertEqual(out["payable"], [["Sticker pack", True, "USDC", 42161]])
        self.assertEqual(out["sheet"], ["Arbitrum One", pay_to, "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", True])
        self.assertTrue(out["ordered"])
        self.assertEqual(out["orders"], [[42161, "0xcdcd", True]])
        self.assertEqual(out["drop"], [["gated", True, False], ["link", True, False], ["plain", False, True]])
        self.assertTrue(out["open_link"] and out["open_plain"] and out["owner_opens_gated"])


class FrontRefusals(unittest.TestCase):
    """A refused request closes the connection, so its unread body is never taken as a new request."""

    def setUp(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import srnet_front as FR
        hits = self.hits = []

        class Back(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            do_POST = do_GET

            def log_message(self, *a):
                pass
        self.back = ThreadingHTTPServer(("127.0.0.1", 0), Back)
        self.front = ThreadingHTTPServer(("127.0.0.1", 0), FR.make_handler(
            [("/c/x", self.back.server_address[1])], ["x"]))
        for srv in (self.back, self.front):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
        self.assertEqual(FR.make_handler([], []).timeout, 60)

    def raw(self, data):
        s = socket.create_connection(self.front.server_address, timeout=5)
        s.sendall(data)
        out = b""
        try:
            while True:
                b = s.recv(65536)
                if not b:
                    break
                out += b
        except socket.timeout:
            pass
        s.close()
        return out

    def test_refused_requests_close(self):
        inner = b"GET /c/x/smuggled HTTP/1.1\r\nHost: a\r\n\r\n"
        cases = [
            b"POST /c/x/a HTTP/1.1\r\nHost: a\r\nContent-Length: 999999999\r\n\r\n" + inner,
            b"POST /c/x/a HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n" + inner,
            b"POST /c/x/a HTTP/1.1\r\nHost: a\r\nContent-Length: -5\r\n\r\n" + inner,
            b"POST /nope HTTP/1.1\r\nHost: a\r\nContent-Length: 0\r\n\r\n" + inner,
        ]
        for c in cases:
            r = self.raw(c)
            self.assertEqual(r.count(b"HTTP/1.1 "), 1, r)
            self.assertIn(b"Connection: close", r)
        self.assertEqual(self.hits, [])
        r = self.raw(b"GET /c/x/a HTTP/1.1\r\nHost: a\r\nConnection: close\r\n\r\n")
        self.assertTrue(r.startswith(b"HTTP/1.1 200"), r)
        self.assertEqual(self.hits, ["/c/x/a"])


if __name__ == "__main__":
    unittest.main()
