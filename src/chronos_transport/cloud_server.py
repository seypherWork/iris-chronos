"""Private loopback HTTP adapter for an explicitly authorized cloud transport.

Only for the owned IRIS network namespace. No host publication, reverse proxy,
external bind or per-user authentication. All processes in that namespace are
inside the spending trust boundary. Never use on a shared/untrusted host.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import select
import socket
from threading import BoundedSemaphore, Event, Timer
import time
if __package__:
    from .cloud_transport import OpenAITransport
    from .cloud_models import validate_selection
    from . import guard
else:
    from cloud_transport import OpenAITransport
    from cloud_models import validate_selection
    import guard


def make_server(client, port=11512):
    if not isinstance(client, OpenAITransport):
        raise ValueError("CLOUD_TRANSPORT_REQUIRED")
    validate_selection(client.profile, client.policy)
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("INVALID_LISTEN_PORT")
    slots = BoundedSemaphore(4)

    class Server(ThreadingHTTPServer):
        daemon_threads = False
        request_queue_size = 4
        allow_reuse_address = False
        def process_request(self, request, address):
            if not slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, address)
            except BaseException:
                slots.release()
                raise
        def process_request_thread(self, request, address):
            try:
                super().process_request_thread(request, address)
            finally:
                slots.release()
        def handle_error(self, request, address):
            # No traceback containing client/provider data or credentials.
            pass

    class Handler(BaseHTTPRequestHandler):
        server_version = "Chronos"
        sys_version = ""
        def setup(self):
            super().setup()
            self.connection.settimeout(2)
            self.expired = Event()
            self.deadline = time.monotonic() + 2
            self.timer = Timer(2, self.expire)
            self.timer.daemon = True
            self.timer.start()
        def expire(self):
            self.expired.set()
            try: self.connection.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        def finish(self):
            self.timer.cancel()
            super().finish()
        def log_message(self, *_): pass
        def reply(self, status, value):
            self.close_connection = True
            if self.expired.is_set() or time.monotonic() >= self.deadline:
                return
            data = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
        def send_error(self, code, message=None, explain=None):
            # BaseHTTPRequestHandler otherwise echoes malformed request lines.
            try: self.reply(code, {"error": {"code": "CLOUD_HTTP_REJECTED"}})
            except OSError: pass
        def do_GET(self): self.send_error(404)
        def do_POST(self):
            try:
                lengths = self.headers.get_all("Content-Length", [])
                types = self.headers.get_all("Content-Type", [])
                if (self.path != "/v1/chat/completions"
                        or self.headers.get_all("Transfer-Encoding")
                        or self.headers.get_all("Content-Encoding")
                        or len(self.headers) > 24
                        or sum(len(k)+len(v) for k,v in self.headers.items()) > 8192
                        or len(types) != 1 or types[0].split(";",1)[0].strip().lower() != "application/json"
                        or len(lengths) != 1 or not lengths[0].isascii()
                        or not lengths[0].isdecimal() or len(lengths[0]) > 6
                        or not 0 < int(lengths[0]) <= guard.REQUEST_LIMIT):
                    raise ValueError("INVALID_HTTP_ENVELOPE")
                size = int(lengths[0]); parts = []; count = 0
                while count < size:
                    remaining = self.deadline - time.monotonic()
                    if self.expired.is_set() or remaining <= 0:
                        raise ValueError("REQUEST_TIMEOUT")
                    self.connection.settimeout(remaining)
                    piece = self.rfile.read1(min(4096, size-count))
                    if not piece: raise ValueError("INCOMPLETE_BODY")
                    parts.append(piece); count += len(piece)
                raw = b"".join(parts)
                value, _ = guard.request_body(raw, client.schema, client.profile.model,
                                             client.profile.digest, client.profile.reasoning_effort)
                if self.expired.is_set(): raise ValueError("REQUEST_TIMEOUT")
                self.timer.cancel()
                remaining = min(30, (value["chronos_deadline_us"]-time.time_ns()//1000)/1_000_000)
                self.deadline = time.monotonic() + max(0, remaining)
                self.timer = Timer(max(0, remaining), self.expire)
                self.timer.daemon = True; self.timer.start()
                def disconnected():
                    if self.expired.is_set() or time.monotonic() >= self.deadline: return True
                    try:
                        readable, _, _ = select.select([self.connection], [], [], 0)
                        return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
                    except OSError: return True
                result = client.send(raw, disconnected=disconnected)
                self.reply(200, result)
            except Exception:
                # Durable claims/uncertainty are owned solely by OpenAITransport.
                try: self.reply(422, {"error": {"code": "CLOUD_REQUEST_REJECTED_NO_AUTOMATIC_RETRY"}})
                except OSError: pass
    return Server(("127.0.0.1", port), Handler)
