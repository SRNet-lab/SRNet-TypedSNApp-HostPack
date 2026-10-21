#!/usr/bin/env python3
"""srnet-host: set up and run your own SRNet typed-SNApp host (board, store, wiki, rooms,
files, people, directory, mail) with an OFFLINE root key.

Host machine:   init -> (send request.json to root machine) -> install-delegation -> status
Root machine:   root init  /  root sign request.json  /  root directory-entry
One name:       front --host P --host P ... --sesh-import KEY
Upkeep:         link, renew, upgrade, backup, uninstall, mail, sesh, sesh-help, directory-submit

Safe defaults: binds 127.0.0.1 only, no root key ever on the host, delegations <= 90 days,
Session Router / .sesh exposure is prepared but switched on only by you.
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

PACK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PACK_ROOT)
import mbfmt as F  # noqa: E402

VERSION = "0.5.0"
# host type -> (process, collection kind).  "board" runs the message-board host; the rest
# run the typed hub with one collection.
TYPES = {"board": ("board", None), "store": ("hub", "shop"), "wiki": ("hub", "wiki"),
         "rooms": ("hub", "room"), "files": ("hub", "drop"), "people": ("hub", "id"),
         "directory": ("hub", "directory"), "mail": ("mail", None)}
DEFAULT_PORT = {"board": 48900, "store": 48910, "wiki": 48911, "rooms": 48912,
                "files": 48913, "people": 48914, "mail": 48915, "directory": 48916}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
APP_DIRS = tuple(d for d in ("mbfmt", "mbhost", "typed", "vendor") if os.path.isdir(os.path.join(PACK_ROOT, d)))
SERVICE_USER = "srnethost"
MAX_DAYS = F.MAX_DELEGATION_S // 86400
REQ_KIND = "srnet-host-delegation-request/v1"


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(2)


def write_private(path, data: bytes, mode=0o600):
    tmp = path + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def jdump(obj) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()


def load_cfg(prefix):
    p = os.path.join(prefix, "host.json")
    if not os.path.exists(p):
        die(f"no host at {prefix} (run init first)")
    with open(p) as f:
        return json.load(f)


def save_cfg(cfg):
    write_private(os.path.join(cfg["prefix"], "host.json"), jdump(cfg), 0o644)


def host_key(cfg):
    with open(os.path.join(cfg["prefix"], "data", "host.key"), "rb") as f:
        return F.key_from_seed(f.read())


def colls(cfg):
    """Collections this host serves: its name, plus any extra rooms (rooms hosts only)."""
    return cfg.get("collections") or [cfg["name"]]


def link_kind(cfg):
    return "board" if cfg["type"] == "board" else TYPES[cfg["type"]][1]


def unit_name(cfg):
    return f"srnet-host-{cfg['name']}"


def is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def have_systemd():
    return os.path.isdir("/run/systemd/system") and shutil.which("systemctl")


def sh(*cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


# ---- request / delegation ----------------------------------------------------------------
def make_request(cfg):
    return {"kind": REQ_KIND, "v": 1, "type": cfg["type"], "name": cfg["name"],
            "collections": colls(cfg), "host": F.pub_hex(host_key(cfg)),
            "created": int(time.time()), "pack": VERSION}


def write_request(cfg):
    p = os.path.join(cfg["prefix"], "request.json")
    write_private(p, jdump(make_request(cfg)), 0o644)
    return p


def sign_request(root_key, req: dict, days: int, now=None) -> dict:
    if req.get("kind") != REQ_KIND:
        die("not a srnet-host delegation request")
    if not (1 <= days <= MAX_DAYS):
        die(f"--days must be 1..{MAX_DAYS}")
    F.load_pub(req["host"])
    now = int(time.time()) if now is None else now
    out = {"kind": "srnet-host-delegation/v1", "root": F.pub_hex(root_key), "host": req["host"],
           "delegations": {}}
    for coll in req["collections"]:
        if not NAME_RE.match(coll):
            die(f"bad collection name {coll!r}")
        d = {"v": 1, "board": coll, "root": F.pub_hex(root_key), "host": req["host"],
             "issued": now, "expires": now + days * 86400, "policy": ""}
        out["delegations"][coll] = {"delegation": d,
                                    "sig": root_key.sign(F.canonical(F.DELEGATION_DOMAIN, d)).hex()}
    return out


def check_bundle(cfg, bundle: dict, allow_root_change=False) -> str:
    hk = F.pub_hex(host_key(cfg))
    root = bundle.get("root", "")
    if cfg.get("root_pin") and root != cfg["root_pin"] and not allow_root_change:
        die("delegation is signed by a DIFFERENT root than before; refusing "
            "(use --allow-root-change only if you really rotated the root)")
    for coll in colls(cfg):
        env = bundle.get("delegations", {}).get(coll)
        if not env:
            die(f"bundle has no delegation for {coll}")
        if F.verify_delegation(env, root, coll) != hk:
            die("delegation is for a different host key")
    return root


# ---- systemd unit ------------------------------------------------------------------------
def exec_cmd(cfg):
    pre = cfg["prefix"]
    py = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
    if cfg["type"] == "board":
        return [py, "-m", "mbhost.host", "--data", f"{pre}/data", "--board", cfg["name"],
                "--bind", "127.0.0.1", "--port", str(cfg["port"]),
                "--delegation", f"{pre}/delegation/{cfg['name']}.json", "--tick", "30",
                # same soft PoW as the SRNet demo board (16 / 18 for new keys)
                "--pow-bits", "16", "--new-key-pow-bits", "18"]
    if cfg["type"] == "mail":  # sealed store-and-forward; never sees content or senders
        return [py, "-m", "typed.mailhost", "--data", f"{pre}/data", "--bind", "127.0.0.1",
                "--port", str(cfg["port"]), "--delegation", f"{pre}/delegation/{cfg['name']}.json",
                "--max-inboxes", str(cfg.get("max_inboxes", 1000))] + (["--closed"] if cfg.get("closed") else []) \
            + [x for k, f in (("requests_max_msgs", "--requests-max-msgs"), ("requests_per_hour", "--requests-per-hour"))
               if cfg.get(k) for x in (f, str(cfg[k]))]
    kind = TYPES[cfg["type"]][1]
    cmd = [py, "-m", "typed.hub", "--data", f"{pre}/data", "--bind", "127.0.0.1",
           "--port", str(cfg["port"]), "--delegation-dir", f"{pre}/delegation"]
    for c in colls(cfg):
        cmd += ["--coll", f"{kind}:{c}"]
    if kind == "drop":
        cmd += ["--max-file-mb", str(cfg.get("max_file_mb", 25)),
                "--quota-mb", str(cfg.get("quota_mb", 0))]
    for a in cfg.get("admins", []):
        cmd += ["--admin", a]
    for s in cfg.get("sellers", []):
        cmd += ["--seller", s]
    return cmd


def unit_text(cfg):
    pre = cfg["prefix"]
    return f"""# generated by srnet-host {VERSION}; do not edit by hand (re-run srnet-host)
[Unit]
Description=SRNet {cfg['type']} host '{cfg['name']}' (loopback only)
After=network.target

[Service]
User={cfg['user']}
WorkingDirectory={pre}/app
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart={' '.join(exec_cmd(cfg))}
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallArchitectures=native
CapabilityBoundingSet=
AmbientCapabilities=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
IPAddressDeny=any
IPAddressAllow=localhost
ReadWritePaths={pre}/data
ReadOnlyPaths={pre}/delegation {pre}/app

[Install]
WantedBy=multi-user.target
"""


# ---- commands ----------------------------------------------------------------------------
def cmd_init(a):
    if a.type not in TYPES:
        die(f"--type must be one of {', '.join(TYPES)}")
    if not NAME_RE.match(a.name) or not a.name[0].isalpha():
        die("--name: starts with a letter; lowercase letters, digits, dashes; max 32")
    extra = [r for r in (a.room or []) if r != a.name]
    if extra and a.type != "rooms":
        die("--room is for rooms hosts")
    for r in extra:
        if not NAME_RE.match(r) or not r[0].isalpha():
            die(f"--room {r!r}: starts with a letter; lowercase letters, digits, dashes; max 32")
    prefix = os.path.abspath(a.prefix or f"/opt/srnet-host/{a.name}")
    if os.path.exists(os.path.join(prefix, "host.json")):
        die(f"{prefix} already has a host (use status / renew / uninstall)")
    port = a.port or DEFAULT_PORT[a.type]
    if not (1024 <= port <= 65535):
        die("--port must be 1024..65535")
    import socket
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            die(f"127.0.0.1:{port} is already in use; pick another --port")
    for d in ("app", "data", "delegation", "backups"):
        os.makedirs(os.path.join(prefix, d), exist_ok=True)
    for d in APP_DIRS:
        dst = os.path.join(prefix, "app", d)
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(os.path.join(PACK_ROOT, d), dst,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    user = a.user or (SERVICE_USER if is_root() else pwd.getpwuid(os.getuid()).pw_name)
    cfg = {"v": 1, "type": a.type, "name": a.name, "prefix": prefix, "port": port,
           "user": user, "root_pin": "", "admins": a.admin, "sellers": a.seller,
           "installed": int(time.time()), "pack": VERSION, "systemd": False}
    if extra:
        cfg["collections"] = [a.name] + sorted(set(extra))
    if a.type == "mail":
        cfg["closed"], cfg["max_inboxes"] = bool(a.closed), a.max_inboxes
    if a.type == "files":
        cfg["max_file_mb"], cfg["quota_mb"] = check_mb(a.max_file_mb, a.quota_mb)
    os.chmod(os.path.join(prefix, "data"), 0o700)
    from typed.host import load_host_key
    load_host_key(os.path.join(prefix, "data"))
    save_cfg(cfg)
    if is_root() and user == SERVICE_USER:
        try:
            pwd.getpwnam(user)
        except KeyError:
            sh("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", user)
        shutil.chown(os.path.join(prefix, "data"), user, user)
        for root_, dirs, files in os.walk(os.path.join(prefix, "data")):
            for n in dirs + files:
                shutil.chown(os.path.join(root_, n), user, user)
    mode, path = choose_sesh_mode(a)
    sname = sesh_setup(cfg, mode, path)
    save_cfg(cfg)
    req = write_request(cfg)
    print(f"Host '{a.name}' ({a.type}) prepared in {prefix}")
    if len(colls(cfg)) > 1:
        print(f"  rooms    : {', '.join(colls(cfg))}")
    if sname:
        print(f"  .sesh    : {sname} (key stored mode 600; switch it on with sesh/ENABLE.txt)")
    print(f"  host key : {F.pub_hex(host_key(cfg))}")
    print(f"  listens  : 127.0.0.1:{port} (loopback only)")
    print(f"\nNext: copy {req} to your OFFLINE root machine and run:")
    print(f"  srnet-host root sign {os.path.basename(req)} --days 90")
    print("then bring delegation.json back and run:")
    print(f"  srnet-host install-delegation delegation.json --prefix {prefix}")


def cmd_root_init(a):
    os.makedirs(a.dir, exist_ok=True)
    p = os.path.join(a.dir, "root.key")
    if os.path.exists(p):
        die(f"{p} exists; refusing to overwrite a root key")
    seed = os.urandom(32)
    write_private(p, seed)
    pin = F.pub_hex(F.key_from_seed(seed))
    write_private(os.path.join(a.dir, "root.pin"), (pin + "\n").encode(), 0o644)
    print(f"Root key created: {p} (keep this machine offline; back the key up on paper/USB)")
    print(f"Root pin (public, give to users): {pin}")


def cmd_root_sign(a):
    with open(a.root_key, "rb") as f:
        root = F.key_from_seed(f.read())
    with open(a.request) as f:
        req = json.load(f)
    print(f"Request: type={req.get('type')} collections={req.get('collections')}")
    print(f"         host key={req.get('host')}")
    if not a.yes:
        if input(f"Sign for {a.days} days? Check the host key with the host operator. [y/N] ") \
                .strip().lower() != "y":
            die("not signed")
    bundle = sign_request(root, req, a.days)
    write_private(a.out, jdump(bundle), 0o644)
    print(f"Wrote {a.out} (valid {a.days} days). Copy it back to the host.")


def install_unit(cfg):
    up = f"/etc/systemd/system/{unit_name(cfg)}.service"
    write_private(up, unit_text(cfg).encode(), 0o644)
    sh("systemctl", "daemon-reload")
    sh("systemctl", "enable", "--now", unit_name(cfg))
    sh("systemctl", "restart", unit_name(cfg))


def cmd_install_delegation(a):
    cfg = load_cfg(a.prefix)
    with open(a.bundle) as f:
        bundle = json.load(f)
    root = check_bundle(cfg, bundle, a.allow_root_change)
    for coll, env in bundle["delegations"].items():
        write_private(os.path.join(cfg["prefix"], "delegation", f"{coll}.json"), jdump(env), 0o644)
    cfg["root_pin"] = root
    write_private(os.path.join(cfg["prefix"], "unit.service"), unit_text(cfg).encode(), 0o644)
    if a.no_systemd or not (is_root() and have_systemd()):
        cfg["systemd"] = False
        save_cfg(cfg)
        print(f"Delegation installed. systemd not used; start in foreground with:\n"
              f"  srnet-host run --prefix {cfg['prefix']}")
    else:
        cfg["systemd"] = True
        save_cfg(cfg)
        install_unit(cfg)
        print(f"Delegation installed; service {unit_name(cfg)} started.")
    print_connect(cfg)


def links(cfg, host=None):
    """srnet:// invite links (collections) or mail host URL, for the .sesh name if set."""
    sn = (cfg.get("sesh") or {}).get("name")
    host = host or sn or f"127.0.0.1:{cfg['port']}"
    if cfg["type"] == "mail":
        # the srnet:// link is what directories list ("Add mail host" verifies the root-signed
        # delegation in /v1/mail/info); the URL is for `srnet mail hosts URL`
        url = f"http://{host}"
        return ([f"srnet://{host}/mail/{cfg['name']}#root={cfg['root_pin']}", url]
                if cfg.get("root_pin") else [url])
    if not cfg.get("root_pin"):
        return []
    return [f"srnet://{host}/{link_kind(cfg)}/{c}#root={cfg['root_pin']}" for c in colls(cfg)]


def print_connect(cfg):
    sn = (cfg.get("sesh") or {}).get("name")
    print("\nConnect info:")
    print(f"  type     : {cfg['type']}   collections: {', '.join(colls(cfg))}")
    print(f"  root pin : {cfg['root_pin']}")
    print(f"  local    : http://127.0.0.1:{cfg['port']} (loopback)")
    print(f"  .sesh    : {sn if sn else 'none yet (srnet-host sesh --prefix ... --sesh new)'}")
    for ln in links(cfg):
        label = "mail host URL" if ln.startswith("http") else "invite link"
        print(f"  {label}: {ln}")
    if not sn:
        print("  (links use the loopback address until the host has a .sesh name)")


def cmd_link(a):
    cfg = load_cfg(a.prefix)
    for ln in links(cfg):
        print(ln)


def cmd_mail(a):
    cfg = load_cfg(a.prefix)
    if cfg["type"] != "mail":
        die("not a mail host")
    if a.closed or a.open:
        cfg["closed"] = bool(a.closed)
    if a.max_inboxes is not None:
        if a.max_inboxes < 0:
            die("--max-inboxes must be >= 0")
        cfg["max_inboxes"] = a.max_inboxes
    for k in ("requests_max_msgs", "requests_per_hour"):
        v = getattr(a, k)
        if v is not None:
            if v < 1:
                die(f"--{k.replace('_', '-')} must be at least 1")
            cfg[k] = v
    save_cfg(cfg)
    write_private(os.path.join(cfg["prefix"], "unit.service"), unit_text(cfg).encode(), 0o644)
    if cfg.get("systemd") and is_root() and have_systemd():
        install_unit(cfg)
    print(f"mail host '{cfg['name']}': sign-up {'CLOSED' if cfg.get('closed') else 'open'}, "
          f"cap {cfg.get('max_inboxes', 1000)} inboxes, non-contact mail "
          f"{cfg.get('requests_max_msgs', 32)} waiting / {cfg.get('requests_per_hour', 20)} per hour per inbox"
          + ("" if cfg.get("systemd") else " (restart `srnet-host run` to apply)"))


def check_mb(max_file_mb, quota_mb):
    if not (0 < max_file_mb <= 256):
        die("--max-file-mb must be more than 0 and at most 256")
    if quota_mb < 0:
        die("--quota-mb must be >= 0 (0 = no quota)")
    return max_file_mb, quota_mb


def cmd_files(a):
    cfg = load_cfg(a.prefix)
    if cfg["type"] != "files":
        die("not a files host")
    cfg["max_file_mb"], cfg["quota_mb"] = check_mb(
        cfg.get("max_file_mb", 25) if a.max_file_mb is None else a.max_file_mb,
        cfg.get("quota_mb", 0) if a.quota_mb is None else a.quota_mb)
    save_cfg(cfg)
    write_private(os.path.join(cfg["prefix"], "unit.service"), unit_text(cfg).encode(), 0o644)
    if cfg.get("systemd") and is_root() and have_systemd():
        install_unit(cfg)
    print(f"files host '{cfg['name']}': max file {cfg['max_file_mb']} MiB, quota "
          f"{cfg['quota_mb'] or 'none'}{' MiB per uploader' if cfg['quota_mb'] else ''}"
          + ("" if cfg.get("systemd") else " (restart `srnet-host run` to apply)"))


def _coll_host(cfg, coll):
    """The Host object for one of this host's collections (signs with the host key)."""
    from typed.host import Host
    if cfg["type"] in ("mail",):
        die("mail hosts hold only sealed mail; there is nothing to moderate")
    names = [cfg["name"]] if cfg["type"] == "board" else colls(cfg)
    coll = coll or cfg["name"]
    if coll not in names:
        die(f"--coll must be one of {', '.join(names)}")
    d = os.path.join(cfg["prefix"], "data") if cfg["type"] == "board" \
        else os.path.join(cfg["prefix"], "data", coll)
    if not os.path.exists(os.path.join(d, "log.sqlite3")):
        die(f"no data for {coll} yet (start the host first)")
    h = Host(d, coll, host_key(cfg), {})
    if os.path.isdir(os.path.join(d, "blobs")):
        from typed.hub import BlobStore
        h.blobs = BlobStore(os.path.join(d, "blobs"), coll=coll)
    return h, d


def _fix_owner(cfg, d):
    """Run as root: give files we created back to the service user."""
    if is_root() and cfg.get("user") and cfg["user"] != "root":
        for root, dirs, files in os.walk(d):
            for n in dirs + files:
                try:
                    shutil.chown(os.path.join(root, n), cfg["user"], cfg["user"])
                except (LookupError, OSError):
                    pass


def cmd_moderate(a):
    cfg = load_cfg(a.prefix)
    if a.action in ("remove", "pin", "unpin") and a.target_type != "post":
        die(f"{a.action} takes a post id")
    if a.action == "remove" and not a.yes:
        print(f"This deletes post {a.target} (and its file, if any) from this host now, and from "
              "mirrors and clients when they sync. It can't be undone.")
        try:
            ok = input("Type REMOVE to continue: ").strip() == "REMOVE"
        except EOFError:
            ok = False
        if not ok:
            die("cancelled (use --yes to skip the prompt)")
    h, d = _coll_host(cfg, a.coll)
    import mbfmt as F2
    try:
        env = h.moderate(a.action, a.target_type, a.target, a.reason or "")
    except F2.FormatError as e:
        die(str(e))
    _fix_owner(cfg, d)
    print(json.dumps(env))


def cmd_header(a):
    cfg = load_cfg(a.prefix)
    if cfg["type"] not in ("rooms", "board"):
        die("headers are for rooms and board hosts")
    if a.description is None and a.rules is None:
        die("give --description and/or --rules")
    h, d = _coll_host(cfg, a.coll)
    import mbfmt as F2
    try:
        out = h.set_header(a.description, a.rules)
    except F2.FormatError as e:
        die(str(e))
    _fix_owner(cfg, d)
    print(json.dumps(out))


def cmd_run(a):
    cfg = load_cfg(a.prefix)
    if not cfg.get("root_pin"):
        die("no delegation installed yet")
    os.chdir(os.path.join(cfg["prefix"], "app"))
    os.execv(exec_cmd(cfg)[0], exec_cmd(cfg))


def delegation_left(cfg):
    left = []
    for c in colls(cfg):
        p = os.path.join(cfg["prefix"], "delegation", f"{c}.json")
        if not os.path.exists(p):
            return None
        with open(p) as f:
            left.append(json.load(f)["delegation"]["expires"] - time.time())
    return min(left)


def cmd_status(a):
    cfg = load_cfg(a.prefix)
    out = {"name": cfg["name"], "type": cfg["type"], "collections": colls(cfg),
           "prefix": cfg["prefix"], "pack": cfg.get("pack"),
           "listen": f"127.0.0.1:{cfg['port']}", "root_pin": cfg["root_pin"] or None}
    if cfg["type"] == "mail":
        out["mail_signup"] = "closed" if cfg.get("closed") else "open"
        out["max_inboxes"] = cfg.get("max_inboxes", 1000)
    left = delegation_left(cfg)
    out["sesh"] = (cfg.get("sesh") or {}).get("name")
    out["links"] = links(cfg)
    out["delegation_days_left"] = None if left is None else round(left / 86400, 1)
    if cfg.get("systemd") and have_systemd():
        out["service"] = sh("systemctl", "is-active", unit_name(cfg), check=False).stdout.strip()
    path = {"board": "/v1/info", "mail": "/v1/mail/info"}.get(cfg["type"], f"/c/{cfg['name']}/v1/info")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{cfg['port']}{path}", timeout=3) as r:
            out["http"] = "ok" if r.status == 200 else r.status
    except Exception as e:  # noqa: BLE001
        out["http"] = f"down ({e.__class__.__name__})"
    warn = []
    if left is not None and left < 14 * 86400:
        warn.append("delegation expires within 14 days: run `srnet-host renew`")
    if os.path.exists(os.path.join(cfg["prefix"], "data", "root.key")):
        warn.append("a root.key is on this host; move it offline")
    out["warnings"] = warn
    print(json.dumps(out, indent=2))
    return 0 if out["http"] == "ok" else 1


def cmd_renew(a):
    cfg = load_cfg(a.prefix)
    req = write_request(cfg)
    print(f"Renewal request written: {req}\nSign it on the root machine "
          f"(srnet-host root sign request.json --days 90), then run install-delegation.")


def cmd_backup(a):
    cfg = load_cfg(a.prefix)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = a.out or os.path.join(cfg["prefix"], "backups", f"{cfg['name']}-{ts}.tar.gz")
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fo, tarfile.open(fileobj=fo, mode="w:gz") as t:
        for n in ("host.json", "data", "delegation", "sesh"):
            if os.path.exists(os.path.join(cfg["prefix"], n)):
                t.add(os.path.join(cfg["prefix"], n), arcname=n)
    print(f"Backup: {out} (contains the HOST key and any .sesh key; store it privately). No root key is included.")


def cmd_uninstall(a):
    cfg = load_cfg(a.prefix)
    if cfg.get("systemd") and have_systemd():
        sh("systemctl", "disable", "--now", unit_name(cfg), check=False)
        try:
            os.remove(f"/etc/systemd/system/{unit_name(cfg)}.service")
        except FileNotFoundError:
            pass
        sh("systemctl", "daemon-reload", check=False)
    if a.purge:
        if not a.yes:
            die("--purge deletes keys and data; add --yes to confirm (back up first)")
        shutil.rmtree(cfg["prefix"])
        print(f"Removed service and {cfg['prefix']}")
    else:
        cfg["systemd"] = False
        save_cfg(cfg)
        print(f"Service removed; data kept in {cfg['prefix']} (use --purge --yes to delete)")


# ---- dedicated .sesh identity (stored + configured, never enabled) -----------------------
def sesh_name(pub: bytes) -> str:
    return F.zb32(pub) + ".sesh"


def parse_sesh_key(raw: bytes):
    """Accept a 32-byte seed or 64-byte seed||pub as hex text or raw bytes, or a bencoded
    `d1:s64:<seed||pub>e` identity.  Returns the Ed25519 key; raises ValueError otherwise."""
    from cryptography.hazmat.primitives import serialization as ser
    seed = pub = None
    txt = raw.strip()
    if txt.startswith(b"d1:s64:") and txt.endswith(b"e") and len(txt) == 72:
        seed, pub = txt[7:39], txt[39:71]
    elif re.fullmatch(rb"[0-9a-fA-F]{64}|[0-9a-fA-F]{128}", txt):
        b = bytes.fromhex(txt.decode())
        seed, pub = b[:32], (b[32:] or None)
    elif len(raw) in (32, 64):
        seed, pub = raw[:32], (raw[32:] or None)
    else:
        raise ValueError("unrecognised .sesh key file (want 32/64-byte hex, raw, or d1:s64:...e)")
    key = F.key_from_seed(seed)
    real = key.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
    if pub is not None and pub != real:
        raise ValueError("key file is inconsistent: stored public half does not match seed")
    return key, real


def sesh_setup(cfg, mode: str, import_path: str | None = None):
    """mode: new | import | skip.  Writes <prefix>/sesh/{identity.key,router.ini,ENABLE.txt}."""
    if mode == "skip":
        cfg["sesh"] = None
        return None
    d = os.path.join(cfg["prefix"], "sesh")
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    kp = os.path.join(d, "identity.key")
    if os.path.exists(kp):
        die(f"{kp} already exists; refusing to overwrite a .sesh key")
    if mode == "import":
        with open(import_path, "rb") as f:
            raw = f.read()
        try:
            _, pub = parse_sesh_key(raw)
        except ValueError as e:
            die(str(e))
        write_private(kp, raw)  # copied byte-for-byte, mode 600
    else:
        seed = os.urandom(32)
        _, pub = parse_sesh_key(seed)
        write_private(kp, (seed + pub).hex().encode() + b"\n")
    name = sesh_name(pub)
    ini = f"""; Dedicated Session Router instance for SRNet host '{cfg['name']}' (start it yourself when ready).
; Template generated by srnet-host {VERSION}; adjust to your Session Router version.
[router]
data-dir={d}/router-data
[network]
keyfile={kp}
[bind]
; keep the instance's own private TUN range; do not reuse another instance's
[service]
; map the .sesh name to the loopback-only host
80=127.0.0.1:{cfg['port']}
"""
    write_private(os.path.join(d, "router.ini"), ini.encode(), 0o600)
    enable = f"""To expose '{cfg['name']}' as {name} (manual, deliberate step):
  1. Install Session Router if it is not installed.
  2. Start a SEPARATE instance with this config (do not edit an existing instance):
       session-router {d}/router.ini
     or create a systemd unit 'srnet-sesh-{cfg['name']}' running that command.
  3. Check the instance reports the name {name}.
  4. Share the links from `srnet-host link --prefix {cfg['prefix']}` (http://{name} serves the host).
To undo: stop that instance. The host itself never listens beyond 127.0.0.1.
"""
    write_private(os.path.join(d, "ENABLE.txt"), enable.encode(), 0o644)
    cfg["sesh"] = {"name": name, "keyfile": kp, "config": os.path.join(d, "router.ini"),
                   "source": mode, "enabled": False}
    return name


def choose_sesh_mode(a):
    if a.sesh_import:
        return "import", a.sesh_import
    if a.sesh:
        return a.sesh, None
    if sys.stdin.isatty():
        while True:
            ans = input(".sesh name for this host: [n]ew key, [i]mport key file, [s]kip (default s): ") \
                .strip().lower() or "s"
            if ans in ("n", "new"):
                return "new", None
            if ans in ("s", "skip"):
                return "skip", None
            if ans in ("i", "import"):
                return "import", input("Path to .sesh key file: ").strip()
    return "skip", None


def cmd_sesh(a):
    cfg = load_cfg(a.prefix)
    mode, path = choose_sesh_mode(a)
    name = sesh_setup(cfg, mode, path)
    save_cfg(cfg)
    if name:
        print(f".sesh name: {name}  (stored; switch it on with {cfg['prefix']}/sesh/ENABLE.txt)")


SESH_HELP = """Opening a host over Session Router (.sesh): a deliberate step you take yourself.

Your host only listens on 127.0.0.1. To let others reach it:
 1. Run a SEPARATE Session Router instance with its own key, so this host gets its own
    .sesh name (do not reuse a name that already serves other things).
 2. Point that instance's port 80 at 127.0.0.1:<port> of this host (the generated
    <prefix>/sesh/router.ini does this). The host itself never listens beyond loopback.
 3. Share the links from `srnet-host link --prefix ...`: each carries the .sesh name, the
    collection and your root pin.
Anyone who knows the name can then reach the host, so review your rules and rate limits first.
"""


def _ver(v):
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except ValueError:
        return (0,)


def cmd_upgrade(a):
    """Swap in the app code from THIS (newer) pack. Keys, data, delegations and .sesh stay."""
    cfg = load_cfg(a.prefix)
    old = cfg.get("pack", "0")
    if _ver(VERSION) < _ver(old) and not a.force:
        die(f"this pack is {VERSION}, the host runs {old}: refusing to downgrade (--force)")
    app = os.path.join(cfg["prefix"], "app")
    new = app + ".new"
    shutil.rmtree(new, ignore_errors=True)
    os.makedirs(new)
    for d in APP_DIRS:
        shutil.copytree(os.path.join(PACK_ROOT, d), os.path.join(new, d),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    prev = app + ".prev"
    shutil.rmtree(prev, ignore_errors=True)
    os.replace(app, prev)
    os.replace(new, app)
    cfg["pack"] = VERSION
    save_cfg(cfg)
    write_private(os.path.join(cfg["prefix"], "unit.service"), unit_text(cfg).encode(), 0o644)
    if cfg.get("systemd") and is_root() and have_systemd():
        install_unit(cfg)
        print(f"Upgraded {cfg['name']} {old} -> {VERSION}; service restarted.")
    else:
        print(f"Upgraded {cfg['name']} {old} -> {VERSION}. Restart `srnet-host run --prefix "
              f"{cfg['prefix']}` to use it.")
    print(f"Previous code kept in {prev}. Keys, data and delegations are unchanged.")


def cmd_root_directory_entry(a):
    """Offline: sign a directory listing for one of YOUR collections with its root key."""
    from typed import joins
    from typed.record import KIND_TYPES, make_record
    with open(a.root_key, "rb") as f:
        key = F.key_from_seed(f.read()[:32])
    try:
        ln = joins.parse(a.link)
    except joins.LinkError as e:
        die(f"--link: {e}")
    if not ln["kind"] or ln["root"] != F.pub_hex(key):
        die("the link must name a collection and carry #root= of THIS root key")
    if not NAME_RE.match(a.directory_name):
        die("--directory-name: the directory collection's name")
    env = make_record(key, KIND_TYPES["directory"], a.directory_name, "directory.entry",
                      {"link": a.link, "title": a.title[:80], "desc": a.desc}, [],
                      pow_bits=a.pow_bits)
    write_private(a.out, jdump(env), 0o644)
    print(f"Wrote {a.out}: '{a.title}' for directory '{a.directory_name}'. Carry it to any "
          "online machine and run `srnet-host directory-submit`.")


def cmd_directory_submit(a):
    from typed.sync import submit
    with open(a.entry) as f:
        env = json.load(f)
    r = submit([a.to.rstrip("/")], env)
    if not r.get("ok"):
        die(f"directory refused the entry: {r.get('error')}")
    print(f"Listed: {r}")



# ---- one .sesh name for several roles (path router) --------------------------------------
FRONT_NET6 = "fd2e:7365:7368:50"


def parse_extra_route(s):
    """--route /relayer=8645: another loopback service on the front's name."""
    pre, sep, port = (s or "").partition("=")
    pre = pre.rstrip("/")
    if not sep or not pre.startswith("/") or pre.startswith(("/c/", "/v1/")) or pre in ("/c", "/v1") \
            or not all(ch.isalnum() or ch in "-_/" for ch in pre):
        die(f"--route {s!r}: use /name=PORT (not under /c/ or /v1/)")
    try:
        port = int(port)
    except ValueError:
        port = 0
    if not 0 < port < 65536:
        die(f"--route {s!r}: bad port")
    return pre, port


def front_routes(host_prefixes, extra=()):
    routes, offered, cfgs = {}, [], []
    for hp in host_prefixes:
        cfg = load_cfg(os.path.abspath(hp))
        if cfg["type"] == "board":
            die("a board host serves at / and can't share a name; give it its own .sesh")
        if cfg["type"] == "mail":
            if "/v1/mail" in routes:
                die("only one mail host per name")
            routes["/v1/mail"] = cfg["port"]
        else:
            for c in colls(cfg):
                if f"/c/{c}" in routes:
                    die(f"two hosts serve a collection named {c!r}")
                routes[f"/c/{c}"] = cfg["port"]
                offered.append({"name": c, "kind": link_kind(cfg)})
        cfgs.append(cfg)
    for s in extra:
        pre, port = parse_extra_route(s)
        if pre in routes:
            die(f"--route {pre}: already routed")
        routes[pre] = port
    return routes, offered, cfgs


def front_units(pre, sr_bin, bind):
    router = f"""# generated by srnet-host {VERSION}
[Unit]
Description=SRNet one-name front: Session Router instance
After=network-online.target
Wants=network-online.target

[Service]
ExecStart={sr_bin} {pre}/router.ini
Restart=always
RestartSec=10
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
"""
    front = f"""# generated by srnet-host {VERSION}
[Unit]
Description=SRNet one-name front: path router on the .sesh name
After=srnet-front-router.service
BindsTo=srnet-front-router.service

[Service]
User={SERVICE_USER}
ExecStartPre=/bin/sh -c 'for n in $$(seq 120); do ip -6 addr show dev sr-front 2>/dev/null | grep -q "{bind}" && exit 0; sleep 1; done; exit 1'
ExecStart=/usr/bin/python3 {pre}/srnet_front.py --routes {pre}/routes.json --bind {bind} --port 80
Restart=always
RestartSec=5
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK

[Install]
WantedBy=multi-user.target
"""
    return router, front


def cmd_front(a):
    """Serve several hosts (rooms, directory, files, mail...) under ONE .sesh name."""
    pre = os.path.abspath(a.prefix)
    os.makedirs(pre, exist_ok=True)
    os.chmod(pre, 0o711)
    kp = os.path.join(pre, "identity.key")
    if a.sesh_import:
        with open(a.sesh_import, "rb") as f:
            raw = f.read()
        if os.path.exists(kp):
            with open(kp, "rb") as f:
                if f.read() != raw:
                    die(f"{kp} holds a different key; refusing to overwrite a .sesh key")
        else:
            write_private(kp, raw)  # byte-for-byte copy, mode 600
    if not os.path.exists(kp):
        die("--sesh-import KEY is required the first time")
    with open(kp, "rb") as f:
        try:
            _, pub = parse_sesh_key(f.read())
        except ValueError as e:
            die(str(e))
    name = sesh_name(pub)
    routes, offered, cfgs = front_routes(a.host, a.route or ())
    write_private(os.path.join(pre, "routes.json"), jdump({"name": name, "routes": routes,
                                                           "collections": offered}), 0o644)
    shutil.copy(os.path.join(PACK_ROOT, "bin", "srnet_front.py"), os.path.join(pre, "srnet_front.py"))
    bind = f"{a.net6}::1"
    boot = ""
    if a.bootstrap:  # copied next to the config: the unit can't read /root or /home
        bp = os.path.join(pre, "bootstrap.signed")
        if os.path.abspath(a.bootstrap) != bp:
            shutil.copy(a.bootstrap, bp)
            os.chmod(bp, 0o644)
        boot = f"[bootstrap]\nadd-node={bp}\n"
    elif os.path.exists(os.path.join(pre, "bootstrap.signed")):
        boot = f"[bootstrap]\nadd-node={os.path.join(pre, 'bootstrap.signed')}\n"
    ini = f"""; One-name front for SRNet hosts, generated by srnet-host {VERSION}
[router]
data-dir={pre}/router-data
[logging]
level=warning
[network]
keyfile={kp}
ifname=sr-front
ifaddr=10.50.0.1/16
ifaddr={a.net6}::1/64
auto-routing=false
blackhole-routes=false
[bind]
listen=:{a.listen_port}
[dns]
listen=
[api]
enabled=false
{boot}"""
    write_private(os.path.join(pre, "router.ini"), ini.encode(), 0o600)
    for cfg in cfgs:
        cfg["sesh"] = {"name": name, "front": pre, "keyfile": kp, "source": "front", "enabled": True}
        save_cfg(cfg)
    router, front = front_units(pre, os.path.abspath(a.sr_binary) if a.sr_binary else "/usr/local/bin/session-router", bind)
    write_private(os.path.join(pre, "srnet-front-router.service"), router.encode(), 0o644)
    write_private(os.path.join(pre, "srnet-front.service"), front.encode(), 0o644)
    if not a.no_systemd and is_root() and have_systemd():
        if not a.sr_binary and not os.path.exists("/usr/local/bin/session-router"):
            die("--sr-binary PATH: no session-router at /usr/local/bin/session-router")
        for n, txt in (("srnet-front-router", router), ("srnet-front", front)):
            write_private(f"/etc/systemd/system/{n}.service", txt.encode(), 0o644)
        sh("systemctl", "daemon-reload")
        sh("systemctl", "enable", "--now", "srnet-front-router", "srnet-front")
        sh("systemctl", "restart", "srnet-front-router", "srnet-front")
        print("started srnet-front-router + srnet-front")
    else:
        print(f"units written to {pre}; start them yourself (root + systemd needed)")
    print(f".sesh name: {name}")
    for p, port in sorted(routes.items()):
        print(f"  http://{name}{p}  ->  127.0.0.1:{port}")
    for cfg in cfgs:
        for ln in links(cfg):
            print(f"  {cfg['name']}: {ln}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="srnet-host", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=VERSION)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def pre(p):
        p.add_argument("--prefix", required=True, help="install dir, e.g. /opt/srnet-host/<name>")

    def sesh_args(p):
        g = p.add_mutually_exclusive_group()
        g.add_argument("--sesh", choices=["new", "skip"], help="make a new .sesh key, or skip")
        g.add_argument("--sesh-import", metavar="FILE", help="import an existing .sesh key file")

    p = sp.add_parser("init", help="prepare a host and write a delegation request")
    p.add_argument("--type", required=True, choices=list(TYPES))
    p.add_argument("--name", required=True)
    p.add_argument("--prefix")
    p.add_argument("--port", type=int)
    p.add_argument("--user", help=f"service user (default {SERVICE_USER} when root)")
    p.add_argument("--admin", action="append", default=[], help="admin public key (hub types)")
    p.add_argument("--seller", action="append", default=[], help="seller public key (store)")
    p.add_argument("--closed", action="store_true", help="mail: no new inboxes (default: open)")
    p.add_argument("--max-inboxes", type=int, default=1000, help="mail: inbox cap (default 1000)")
    p.add_argument("--room", action="append", default=[], help="rooms: another room on this host (repeatable)")
    p.add_argument("--max-file-mb", type=float, default=25, help="files: largest file in MiB (default 25)")
    p.add_argument("--quota-mb", type=float, default=0, help="files: MiB each uploader may store (0 = no quota)")
    sesh_args(p)
    p.set_defaults(fn=cmd_init)
    p = sp.add_parser("mail", help="mail host: sign-up, inbox cap and limits for mail from non-contacts")
    pre(p)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--closed", action="store_true", help="stop new inboxes (existing ones keep working)")
    g.add_argument("--open", action="store_true", help="allow new inboxes again")
    p.add_argument("--max-inboxes", type=int)
    p.add_argument("--requests-max-msgs", type=int, help="non-contact mail waiting per inbox (default 32)")
    p.add_argument("--requests-per-hour", type=int, help="new non-contact mail per inbox per hour (default 20)")
    p.set_defaults(fn=cmd_mail)
    p = sp.add_parser("files", help="files host: change the file size limit or uploader quota")
    pre(p)
    p.add_argument("--max-file-mb", type=float)
    p.add_argument("--quota-mb", type=float)
    p.set_defaults(fn=cmd_files)
    p = sp.add_parser("moderate", help="hide, unhide, remove, pin or unpin (signed, public)")
    pre(p)
    p.add_argument("action", choices=["hide", "unhide", "remove", "pin", "unpin"])
    p.add_argument("target_type", choices=["post", "author"])
    p.add_argument("target", help="post id or author key")
    p.add_argument("--reason", default="")
    p.add_argument("--coll", help="collection (default: the host's name; e.g. another room)")
    p.add_argument("--yes", action="store_true", help="remove: skip the confirmation")
    p.set_defaults(fn=cmd_moderate)
    p = sp.add_parser("header", help="set the room description and rules shown at the top")
    pre(p)
    p.add_argument("--description")
    p.add_argument("--rules")
    p.add_argument("--coll")
    p.set_defaults(fn=cmd_header)
    p = sp.add_parser("sesh", help="make or import a dedicated .sesh key later")
    pre(p)
    sesh_args(p)
    p.set_defaults(fn=cmd_sesh)

    r = sp.add_parser("root", help="offline root machine commands").add_subparsers(dest="rc",
                                                                                   required=True)
    p = r.add_parser("init", help="create an offline root key")
    p.add_argument("--dir", default="./srnet-root")
    p.set_defaults(fn=cmd_root_init)
    p = r.add_parser("sign", help="sign a host's request.json")
    p.add_argument("request")
    p.add_argument("--root-key", default="./srnet-root/root.key")
    p.add_argument("--days", type=int, default=MAX_DAYS)
    p.add_argument("--out", default="delegation.json")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_root_sign)
    p = r.add_parser("directory-entry", help="sign a directory listing for your collection")
    p.add_argument("--link", required=True, help="srnet:// link of YOUR collection (from `srnet-host link`)")
    p.add_argument("--title", required=True)
    p.add_argument("--desc")
    p.add_argument("--directory-name", default="directory", help="name of the directory collection")
    p.add_argument("--root-key", default="./srnet-root/root.key")
    p.add_argument("--pow-bits", type=int, default=14, help="proof-of-work bits (directory default 14)")
    p.add_argument("--out", default="directory-entry.json")
    p.set_defaults(fn=cmd_root_directory_entry)
    p = sp.add_parser("directory-submit", help="post a signed directory entry to a directory")
    p.add_argument("entry")
    p.add_argument("--to", required=True, help="directory URL, e.g. http://<name>.sesh/c/directory")
    p.set_defaults(fn=cmd_directory_submit)
    p = sp.add_parser("upgrade", help="move a host to this pack's code (keeps keys and data)")
    pre(p)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_upgrade)
    p = sp.add_parser("link", help="print invite links (or the mail host URL)")
    pre(p)
    p.set_defaults(fn=cmd_link)

    p = sp.add_parser("install-delegation", help="install a signed delegation and start")
    p.add_argument("bundle")
    pre(p)
    p.add_argument("--no-systemd", action="store_true")
    p.add_argument("--allow-root-change", action="store_true")
    p.set_defaults(fn=cmd_install_delegation)
    for n, fn, h in (("status", cmd_status, "show health"), ("renew", cmd_renew, "new request"),
                     ("run", cmd_run, "run in foreground (no systemd)")):
        p = sp.add_parser(n, help=h)
        pre(p)
        p.set_defaults(fn=fn)
    p = sp.add_parser("backup", help="tar.gz of data + delegation")
    pre(p)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_backup)
    p = sp.add_parser("uninstall", help="remove service (keeps data unless --purge)")
    pre(p)
    p.add_argument("--purge", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_uninstall)
    p = sp.add_parser("front", help="serve several hosts under ONE .sesh name (path router)")
    p.add_argument("--prefix", default="/opt/srnet-host/front")
    p.add_argument("--host", action="append", required=True, metavar="HOST_PREFIX",
                   help="an installed host's --prefix (repeatable): rooms, directory, files, mail, ...")
    p.add_argument("--sesh-import", metavar="FILE", help="the .sesh key file (copied, never moved)")
    p.add_argument("--route", action="append", metavar="/NAME=PORT",
                   help="also route /NAME to a loopback service on PORT (repeatable), e.g. /relayer=8645")
    p.add_argument("--sr-binary", help="session-router binary (default /usr/local/bin/session-router)")
    p.add_argument("--bootstrap", help="Session Router bootstrap file (e.g. mainnet.signed)")
    p.add_argument("--net6", default=FRONT_NET6, help="private tun /64 prefix (default %(default)s)")
    p.add_argument("--listen-port", type=int, default=1250, help="Session Router UDP port")
    p.add_argument("--no-systemd", action="store_true")
    p.set_defaults(fn=cmd_front)
    p = sp.add_parser("sesh-help", help="how to expose over Session Router (manual)")
    p.set_defaults(fn=lambda a: print(SESH_HELP))
    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
