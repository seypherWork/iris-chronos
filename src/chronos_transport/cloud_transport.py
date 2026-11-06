"""Explicit OpenAI E1 transport library, not an enabled application route.

No environment/key loading, automatic initialization, retries, endpoint overrides
or CLI. The current guard/native installer still reject remote provider startup.
"""
from hashlib import sha256
from pathlib import Path
from threading import Event, Lock, Thread
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time

if __package__:
    from . import guard
    from .cloud_budget import CloudAllowance, OUTPUT_TOKEN_LIMIT, canonical
    from .deployment import DeploymentError
else:
    import guard
    from cloud_budget import CloudAllowance, OUTPUT_TOKEN_LIMIT, canonical
    from deployment import DeploymentError

HOST, PORT, ROUTE = 'api.openai.com', 443, '/v1/chat/completions'
_DNS_LOCK = Lock()


class TransportError(ValueError):
    pass


class ApiKey:
    """Memory only; no implicit str/repr/pickle disclosure. Not secure erasure."""
    __slots__ = ('_value',)

    def __init__(self, value):
        if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{16,512}', value):
            raise TransportError('API_KEY_FORMAT_INVALID')
        self._value = value

    def __repr__(self):
        return '<ApiKey redacted>'

    __str__ = __repr__

    def __reduce_ex__(self, protocol):
        raise TypeError('API_KEY_SERIALIZATION_DISABLED')

    def close(self):
        self._value = None  # Python/OS may retain earlier immutable copies.

    def _header(self):
        if self._value is None:
            raise TransportError('API_KEY_CLOSED')
        return 'Bearer ' + self._value

    def _reject_echo(self, value):
        if self._value is None:
            raise TransportError('API_KEY_CLOSED')
        if self._value in canonical(value):
            raise TransportError('CREDENTIAL_ECHO_REJECTED')


def _schema_subset(node):
    if type(node) is list:
        return [_schema_subset(item) for item in node]
    if type(node) is not dict:
        return node
    permitted = {'type', 'properties', 'required', 'additionalProperties', 'enum', 'anyOf', 'items'}
    local_constraints = {'minLength', 'maxLength', 'minItems', 'maxItems', 'uniqueItems'}
    if set(node) - permitted - local_constraints:
        raise TransportError('PROVIDER_SCHEMA_UNSUPPORTED')
    result = {}
    for key, value in node.items():
        if key in local_constraints:
            continue
        result[key] = ({name: _schema_subset(schema) for name, schema in value.items()}
                       if key == 'properties' else _schema_subset(value))
    return result


def _check_e1(value):
    """Retain ALL removed schema constraints. Context semantics remain native A1."""
    if type(value) is not dict or set(value) != guard.EXTRACTION_FIELDS:
        raise TransportError('PROPOSAL_SHAPE')
    if value['schema_version'] != guard.EXTRACTION_CONTRACT:
        raise TransportError('EXTRACTION_CONTRACT_MISMATCH')
    if value['interpreted_preference'] not in ('CHEAPEST_ON_TIME', 'EARLIEST_ALLOWED', 'UNRESOLVED'):
        raise TransportError('EXTRACTION_ENUM_INVALID')
    if value['reason_code'] not in ('PREFERENCE_MATCH', 'CONTEXT_AMBIGUOUS', 'CONFLICTING_EVIDENCE', 'CONTEXT_INCOMPLETE'):
        raise TransportError('EXTRACTION_ENUM_INVALID')
    sources = value['source_ids']
    if (type(sources) is not list or not 1 <= len(sources) <= 16
            or any(type(s) is not str or not 1 <= len(s) <= 256 for s in sources)
            or len(set(sources)) != len(sources)):
        raise TransportError('EXTRACTION_SOURCES_INVALID')
    if type(value['rationale']) is not str or not 1 <= len(value['rationale']) <= 240:
        raise TransportError('EXTRACTION_RATIONALE_INVALID')
    question = value['clarification']
    if question is not None and (type(question) is not str or not 1 <= len(question) <= 160):
        raise TransportError('EXTRACTION_CLARIFICATION_INVALID')


def _remaining(deadline, disconnected):
    remaining = deadline - time.monotonic()
    if remaining <= 0 or disconnected():
        raise TransportError('UPSTREAM_CANCELLED_OR_TIMEOUT')
    return remaining


def _resolve(deadline, disconnected):
    # A timed-out native DNS call may remain alive. At most one resolver worker
    # exists in this process; it never dispatches HTTP or receives a credential.
    if not _DNS_LOCK.acquire(blocking=False):
        raise TransportError('DNS_BUSY_NO_RETRY')
    done, result = Event(), []
    def worker():
        try:
            result.extend(socket.getaddrinfo(HOST, PORT, type=socket.SOCK_STREAM))
        except OSError:
            pass
        finally:
            _DNS_LOCK.release()
            done.set()
    thread = Thread(target=worker, daemon=True)
    try:
        thread.start()
    except Exception:
        _DNS_LOCK.release()
        raise TransportError('DNS_UNAVAILABLE') from None
    while not done.wait(min(.05, _remaining(deadline, disconnected))):
        pass
    _remaining(deadline, disconnected)
    candidates = []
    for family, kind, proto, _, address in result:
        if family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM:
            continue
        try:
            public = ipaddress.ip_address(address[0]).is_global
        except ValueError:
            public = False
        if public and address[1] == PORT:
            candidates.append((family, proto, address))
    if not candidates:
        raise TransportError('DNS_NO_PUBLIC_ADDRESS')
    # Prefer IPv4 for portability; one connection only, no failover retry.
    candidates.sort(key=lambda row: row[0] != socket.AF_INET)
    return candidates[0]


def _tls_context():
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise TransportError('TLS_VERIFICATION_REQUIRED')
    return context


def _post(payload, key, deadline, disconnected, before_send):
    """Single direct HTTPS POST; no proxy env, redirects, retry or custom CA input."""
    raw = canonical(payload).encode('utf-8')
    if len(raw) > guard.REQUEST_LIMIT:
        raise TransportError('OUTBOUND_REQUEST_SIZE')
    context = _tls_context()
    family, proto, address = _resolve(deadline, disconnected)
    connection = http.client.HTTPSConnection(HOST, PORT, timeout=_remaining(deadline, disconnected), context=context)
    connection.auto_open = 0  # Closing the socket must never trigger a reconnect.
    connection.debuglevel = 0
    control = plain = tls = None
    finished, cancelled = Event(), Event()
    watcher = None
    def watch():
        while not finished.wait(.025):
            try:
                _remaining(deadline, disconnected)
            except Exception:
                cancelled.set()
                try:
                    control.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                return
    try:
        plain = socket.socket(family, socket.SOCK_STREAM, proto)
        control = plain.dup()  # Duplicate BEFORE TLS: SSLSocket.dup is unsupported.
        plain.settimeout(_remaining(deadline, disconnected))
        watcher = Thread(target=watch, daemon=True)
        watcher.start()
        plain.connect(address)
        _remaining(deadline, disconnected)
        tls = context.wrap_socket(plain, server_hostname=HOST, do_handshake_on_connect=False)
        tls.settimeout(_remaining(deadline, disconnected))
        tls.do_handshake()
        connection.sock = tls
        before_send()  # Recheck consent/clock after claim, DNS, connect and TLS.
        _remaining(deadline, disconnected)
        connection.request('POST', ROUTE, body=raw, headers={
            'Authorization': key._header(), 'Content-Type': 'application/json',
            'Accept': 'application/json', 'Accept-Encoding': 'identity', 'Connection': 'close'})
        response = connection.getresponse()
        if response.status != 200:
            raise TransportError('UPSTREAM_HTTP_ERROR')
        for name in ('Content-Length', 'Content-Type', 'Content-Encoding', 'Transfer-Encoding'):
            if len([1 for k, _ in response.getheaders() if k.lower() == name.lower()]) > 1:
                raise TransportError('UPSTREAM_DUPLICATE_HEADER')
        if response.getheader('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            raise TransportError('UPSTREAM_CONTENT_TYPE')
        if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
            raise TransportError('UPSTREAM_ENCODING')
        length, transfer = response.getheader('Content-Length'), response.getheader('Transfer-Encoding')
        if transfer and (transfer.lower() != 'chunked' or length is not None):
            raise TransportError('UPSTREAM_FRAMING')
        if length is not None and (not length.isascii() or not length.isdecimal() or len(length) > 8 or int(length) > guard.RESPONSE_LIMIT):
            raise TransportError('UPSTREAM_SIZE')
        chunks, size = [], 0
        while True:
            _remaining(deadline, disconnected)
            chunk = response.read1(min(4096, guard.RESPONSE_LIMIT + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > guard.RESPONSE_LIMIT:
                raise TransportError('UPSTREAM_SIZE')
        _remaining(deadline, disconnected)
        if cancelled.is_set():
            raise TransportError('UPSTREAM_CANCELLED_OR_TIMEOUT')
        if length is not None and size != int(length):
            raise TransportError('UPSTREAM_INCOMPLETE_BODY')
        return b''.join(chunks)
    except (OSError, http.client.HTTPException):
        raise TransportError('UPSTREAM_CANCELLED_OR_TIMEOUT' if cancelled.is_set() else 'UPSTREAM_UNAVAILABLE') from None
    finally:
        finished.set()
        if watcher is not None and watcher.is_alive():
            watcher.join(timeout=.2)
        connection.close()
        for stream in (tls, plain, control):
            if stream is not None:
                stream.close()


class OpenAITransport:
    """Requires a privately supplied key and an already explicitly funded ledger.

    All future launchers must enforce owner consent, model capability/rate review
    and path ownership. Programmatic construction is not evidence of approval.
    """
    def __init__(self, allowance, key, *, authorized_policy_sha256):
        if not isinstance(allowance, CloudAllowance) or not isinstance(key, ApiKey):
            raise TransportError('CLOUD_LEDGER_AND_PRIVATE_KEY_REQUIRED')
        if authorized_policy_sha256 != allowance.policy.digest:
            raise TransportError('CLOUD_EXPLICIT_BUDGET_AUTHORIZATION_REQUIRED')
        allowance.policy.validate_profile(allowance.profile)
        # This protocol preserves native temperature=0. Models that do not support
        # non-reasoning+temperature must not be selected or silently downgraded.
        if allowance.profile.reasoning_effort != 'none':
            raise TransportError('CLOUD_NON_REASONING_PROFILE_REQUIRED')
        self.allowance, self.key = allowance, key
        self.authorization = authorized_policy_sha256
        self.profile, self.policy = allowance.profile, allowance.policy
        self.schema = guard.strict_json(Path(__file__).with_name('extraction-schema.json').read_bytes())
        if sha256(canonical(self.schema).encode()).hexdigest() != self.profile.schema_sha256:
            raise TransportError('PROFILE_SCHEMA_MISMATCH')
        self._lock = Lock()

    def __repr__(self):
        return '<OpenAITransport private credentials redacted>'

    def _prepare(self, raw):
        if type(raw) is not bytes or not 0 < len(raw) <= guard.REQUEST_LIMIT:
            raise TransportError('REQUEST_SIZE')
        value, request_id = guard.request_body(raw, self.schema, self.profile.model,
                                             self.profile.digest, self.profile.reasoning_effort)
        self.key._reject_echo(value)
        body = {key: value[key] for key in ('model', 'messages', 'temperature', 'reasoning_effort')}
        body.update(max_completion_tokens=OUTPUT_TOKEN_LIMIT, n=1, stream=False, store=False,
                    service_tier='default', response_format={'type': 'json_schema', 'json_schema': {
                        'name': 'chronos_e1', 'strict': True, 'schema': _schema_subset(self.schema)}})
        if len(canonical(body).encode('utf-8')) > guard.REQUEST_LIMIT:
            raise TransportError('OUTBOUND_REQUEST_SIZE')
        return value, request_id, body

    def send(self, raw, *, disconnected=lambda: False):
        if not self._lock.acquire(blocking=False):
            raise TransportError('BUSY_NO_RETRY')
        claimed = None
        try:
            started = time.monotonic()
            value, request_id, body = self._prepare(raw)
            deadline_us = value['chronos_deadline_us']
            deadline = started + min(28, (deadline_us - time.time_ns() // 1000) / 1_000_000)
            def revalidate():
                _remaining(deadline, disconnected)
                self.policy.validate_authorization(self.authorization, time.time_ns() // 1000, deadline_us)
            revalidate()
            self.key._header()  # Refuse a closed key before spending a slot.
            self.allowance.claim(request_id, sha256(raw).hexdigest(), deadline_us,
                                 authorized_policy_sha256=self.authorization)
            claimed = request_id
            revalidate()
            def before_send():
                revalidate()
                self.allowance.check_dispatch(request_id, sha256(raw).hexdigest(), deadline_us,
                                              authorized_policy_sha256=self.authorization)
                revalidate()  # A DB read can also cross the deadline.
            wire = _post(body, self.key, deadline, disconnected, before_send)
            revalidate()
            parsed = guard.strict_json(wire)
            self.key._reject_echo(parsed)
            if type(parsed) is dict:
                if parsed.get('service_tier') not in (None, 'default'):
                    self.allowance.halt('UNEXPECTED_PROVIDER_TIER')
                    raise TransportError('UNEXPECTED_PROVIDER_TIER')
                usage = parsed.get('usage')
                counts = [usage.get(k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')] if type(usage) is dict else []
                if (len(counts) != 3 or any(type(n) is not int or n < 0 for n in counts)
                        or counts[0] + counts[1] != counts[2]
                        or counts[0] > self.policy.model_context_tokens or counts[1] > OUTPUT_TOKEN_LIMIT):
                    self.allowance.halt('PROVIDER_USAGE_OUTSIDE_AUTHORIZED_LIMIT')
                    raise TransportError('PROVIDER_USAGE_OUTSIDE_AUTHORIZED_LIMIT')
            result = guard.checked_response(wire, request_id, self.profile.model,
                                            self.profile.digest, guard.EXTRACTION_CONTRACT)
            content = guard.strict_json(result['choices'][0]['message']['content'])
            self.key._reject_echo(content)
            _check_e1(content)
            revalidate()
            result['choices'][0]['message']['content'] = canonical(content)
            self.allowance.finish(request_id, 'VERIFIED_STOP')
            revalidate()  # Persistence may outlive the caller; never return late success.
            return result
        except (TransportError, DeploymentError, guard.Rejected) as exc:
            if claimed is not None:
                try:
                    self.allowance.finish(claimed, 'UNCERTAIN')
                except Exception:
                    pass  # Durable IN_FLIGHT remains spent even if status fails.
            raise TransportError(exc.code if isinstance(exc, guard.Rejected) else str(exc)) from None
        except Exception:
            if claimed is not None:
                try:
                    self.allowance.finish(claimed, 'UNCERTAIN')
                except Exception:
                    pass
            raise TransportError('CLOUD_TRANSPORT_UNAVAILABLE') from None
        finally:
            self._lock.release()
