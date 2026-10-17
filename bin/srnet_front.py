#!/usr/bin/env python3
"""One .sesh name for several srnet-host roles: a small path router.

Binds the Session Router instance's tun address (port 80) and forwards by path prefix to the
loopback-only hosts:  /c/<collection>/...  -> the hub serving that collection
                      /v1/mail/...         -> the mail host
                      /v1/collections      -> merged list from every hub
                      extra routes         -> other loopback services (e.g. /relayer)
X-Forwarded-For is set to the caller's tun address (any incoming value is dropped), so
loopback services can rate-limit per caller.
Routes come from routes.json, written by `srnet-host front`. Stdlib only.
"""
from __future__ import annotations

import argparse
import http.client
import json
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 64 << 20
HOP = {"connection", "keep-alive", "proxy-connection", "transfer-encoding", "te", "trailer", "upgrade"}


def load(path):
    with open(path) as f:
        r = json.load(f)
    routes = sorted(((p.rstrip("/"), int(port)) for p, port in r["routes"].items()),
                    key=lambda x: -len(x[0]))
    return routes, r.get("collections", [])


def make_handler(routes, colls):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _route(self):
            path = self.path.split("?", 1)[0]
            for pre, port in routes:
                if path == pre or path.startswith(pre + "/"):
                    return port
            return None

        def _proxy(self):
            if self.path.split("?", 1)[0] == "/v1/collections" and self.command == "GET":
                return self._send(200, json.dumps({"collections": colls}).encode())
            port = self._route()
            if port is None:
                return self._send(404, b'{"error":"no such collection on this host"}')
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._send(413, b'{"error":"too large"}')
            body = self.rfile.read(n) if n else None
            hdrs = {k: v for k, v in self.headers.items()
                    if k.lower() not in HOP and k.lower() not in ("host", "x-forwarded-for")}
            hdrs["X-Forwarded-For"] = self.client_address[0]
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
                c.request(self.command, self.path, body=body, headers=hdrs)
                r = c.getresponse()
                data = r.read()
            except OSError:
                return self._send(502, b'{"error":"host down"}')
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() not in HOP and k.lower() != "content-length":
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_HEAD = _proxy

    return H


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--bind", required=True, help="tun address of the Session Router instance")
    ap.add_argument("--port", type=int, default=80)
    a = ap.parse_args(argv)
    routes, colls = load(a.routes)

    class S(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if ":" in a.bind else socket.AF_INET
        daemon_threads = True

    srv = S((a.bind, a.port), make_handler(routes, colls))
    print(f"srnet-front on [{a.bind}]:{a.port}: {', '.join(p for p, _ in routes)}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
