"""Bounded local Ollama transport for AI Hub154, not an agent or dispatcher.

Rejects incomplete responses before the SDK drops finish_reason. Only synthetic
Chronos requests, a pinned local model/profile, and no provider credentials.
"""
from dataclasses import dataclass
from copy import deepcopy
from contextlib import closing
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread, Timer
import http.client
import io
import json
import math
import re
import select
import signal
import socket
import sqlite3
import sys
import time

MODEL = "qwen38:cyber-32k"
REQUEST_LIMIT, RESPONSE_LIMIT, CONTENT_LIMIT = 98304, 65536, 4096
OPERATION_LIMIT_SECONDS = 30
CONVERSATION_CONTRACT = "chronos.case-conversation.v1"
PLAN_CONTRACT = "chronos.case-explanation-plan.v1"
PLAN_V2_CONTRACT = "chronos.case-explanation-plan.v2"
PLAN_CONTRACTS = (PLAN_CONTRACT, PLAN_V2_CONTRACT)
CONVERSATION_CONTRACTS = (CONVERSATION_CONTRACT, *PLAN_CONTRACTS)
PLAN_FIELDS = set("schema conversation_id turn_id context_digest catalog_digest topic detail preference".split())
PLAN_TOPICS = {'DECISION','COMPARISON','OPERATION_STATUS','PHYSICAL_DELIVERY',
               'PREFERENCE_CHANGE','APPROVAL_REQUIREMENTS','CLARIFY'}
PLAN_V2_FIELDS = (PLAN_FIELDS - {'topic'}) | {'renderer_version','topics'}
PLAN_V2_TOPICS = PLAN_TOPICS | {'CHAT_EFFECT','CURRENT_REVIEW','DECISION_CHANGE','DESTINATION_SIMULATION'}
PLAN_V2_RENDERER = 'chronos.explanation-renderer.v2'
PLAN_RESPONSE_BYTE_LIMIT = 8192
# Match the C1 schema/host limits; A1/E1 limits are unchanged.
CONVERSATION_ANSWER_CHAR_LIMIT = 2048
CONVERSATION_ANSWER_BYTE_LIMIT = 8192
CONVERSATION_RESPONSE_BYTE_LIMIT = 32768
CONVERSATION_FIELDS = set("schema conversation_id turn_id context_digest intent answer source_ids preference".split())
EXTRACTION_CONTRACT = "chronos.preference-extraction.v1"
# Keep the local E1 decision and case chat on one verified Ollama context policy.
NATIVE_CONTEXT_CONTRACTS = (EXTRACTION_CONTRACT, *CONVERSATION_CONTRACTS)
EXTRACTION_FIELDS = set("schema_version interpreted_preference reason_code source_ids rationale clarification".split())


def response_contract(schema):
    if type(schema) is not dict or type(schema.get("properties")) is not dict:
        raise Rejected("UNSUPPORTED_CONTRACT")
    properties=schema["properties"]
    if "schema" in properties:
        marker=properties["schema"]
        if (type(marker) is dict and marker.get("enum")==[CONVERSATION_CONTRACT]
                and set(properties)==CONVERSATION_FIELDS):
            return CONVERSATION_CONTRACT
        if (type(marker) is dict and marker.get("enum")==[PLAN_CONTRACT]
                and set(properties)==PLAN_FIELDS):
            return PLAN_CONTRACT
        if (type(marker) is dict and marker.get("enum")==[PLAN_V2_CONTRACT]
                and set(properties)==PLAN_V2_FIELDS):
            return PLAN_V2_CONTRACT
        raise Rejected("UNSUPPORTED_CONTRACT")
    marker=properties.get("schema_version",{})
    versions=marker.get("enum") if type(marker) is dict else None
    if versions not in (["chronos.agent-proposal.v1"],["chronos.agent-proposal.v2"],[EXTRACTION_CONTRACT]):
        raise Rejected("UNSUPPORTED_CONTRACT")
    return versions[0]
FIELDS = set("schema_version context_id context_digest order_id shipment_version state_revision action option_id interpreted_preference source_ids reason_code rationale clarification".split())


class Rejected(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)



# Fixed diagnostics only. Never include prompts, content, settings or exception text.
DIAGNOSTIC_CODES = frozenset({
    'ALLOWANCE_UNAVAILABLE',
    'BUSY_NO_RETRY',
    'CLAIM_UNAVAILABLE',
    'DEADLINE_EXPIRED_OR_INVALID',
    'DUPLICATE_JSON_KEY',
    'EXTRACTION_CONTRACT_MISMATCH',
    'EXTRACTION_PROFILE_REQUIRED',
    'CONVERSATION_PROFILE_REQUIRED',
    'CONVERSATION_RESPONSE_INVALID',
    'GUARD_ERROR',
    'INCOMPLETE_RESPONSE',
    'INVALID_BODY_DIGEST',
    'INVALID_DEADLINE',
    'INVALID_JSON',
    'INVALID_REQUEST_ID',
    'NONFINITE_JSON',
    'PROFILE_MISMATCH',
    'PROPOSAL_SHAPE',
    'REQUEST_ALREADY_USED',
    'REQUEST_BODY_INCOMPLETE',
    'REQUEST_DEADLINE',
    'REQUEST_FIELDS',
    'REQUEST_ID',
    'REQUEST_LIMIT_REACHED',
    'REQUEST_MESSAGES',
    'REQUEST_POLICY',
    'REQUEST_SCHEMA',
    'REQUEST_SIZE',
    'REQUEST_TIMEOUT',
    'RESPONSE_CHOICES',
    'RESPONSE_CONTENT',
    'RESPONSE_MESSAGE',
    'RESPONSE_MODEL',
    'RESPONSE_USAGE',
    'ROUTE_OR_ENCODING',
    'UNEXPECTED_TOOL_OR_REFUSAL',
    'UNSUPPORTED_CONTRACT',
    'UPSTREAM_CONTENT_TYPE',
    'UPSTREAM_ENCODING',
    'UPSTREAM_HTTP_ERROR',
    'UPSTREAM_INCOMPLETE_BODY',
    'UPSTREAM_SIZE',
    'UPSTREAM_TIMEOUT',
    'UPSTREAM_UNAVAILABLE',
    'CONTEXT_POLICY_UNSUPPORTED',
    'NATIVE_RESPONSE_INVALID',
    'CONVERSATION_CONTENT_EMPTY',
    'CONVERSATION_THINKING_ONLY',
    'CONVERSATION_CONTENT_TYPE',
    'CONVERSATION_CONTENT_LIMIT',
    'CONVERSATION_SCHEMA_INVALID',
    'CONVERSATION_BINDING_INVALID',
    'CONVERSATION_INTENT_INVALID',
    'CONVERSATION_ANSWER_INVALID',
    'CONVERSATION_SOURCES_INVALID',
    'CONVERSATION_PREFERENCE_INVALID',
    'EXPLANATION_PLAN_INVALID',
    'EXPLANATION_PLAN_BINDING_INVALID',
    'EXPLANATION_REQUEST_BINDING_INVALID',
    'EXPLANATION_PLAN_TOPIC_INVALID',
    'EXPLANATION_PLAN_TOPICS_TYPE',
    'EXPLANATION_PLAN_TOPICS_COUNT',
    'EXPLANATION_PLAN_TOPIC_NAME',
    'EXPLANATION_PLAN_TOPICS_DUPLICATED',
    'EXPLANATION_PLAN_CLARIFY_MIXED',
    'EXPLANATION_PLAN_PREFERENCE_MISSING',
    'EXPLANATION_PLAN_PREFERENCE_VALUE',
    'EXPLANATION_PLAN_PREFERENCE_UNEXPECTED',
    'EXPLANATION_PLAN_DETAIL_INVALID',
    'EXPLANATION_PLAN_PREFERENCE_INVALID',

})

class DiagnosticWriter:
    """Best-effort fixed-size events; a blocked sink cannot hold a request."""
    LIMIT = 32

    def __init__(self, stream=None):
        self.stream = sys.stderr if stream is None else stream
        self.queue = Queue(maxsize=self.LIMIT)
        self.stopped = Event()
        self.worker = Thread(target=self._run, daemon=True, name="chronos-diagnostics")
        self.worker.start()

    def emit(self, row):
        if self.stopped.is_set():
            return
        try:
            self.queue.put_nowait(row)
        except Full:
            pass

    def close(self):
        # Never join a possibly blocked sink. The worker is daemon and memory bounded.
        self.stopped.set()

    def _run(self):
        while not self.stopped.is_set():
            try:
                row = self.queue.get(timeout=0.2)
            except Empty:
                continue
            try:
                print(json.dumps(row, separators=(",", ":")), file=self.stream, flush=True)
            except Exception:
                pass
            finally:
                self.queue.task_done()


def record_rejection(request_id, code, began, diagnostics):
    try:
        safe_id = request_id if type(request_id) is str and re.fullmatch(
            r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", request_id) else None
        safe_code = code if type(code) is str and code in DIAGNOSTIC_CODES else "UNCLASSIFIED_REJECTION"
        elapsed = time.monotonic() - began
        if not math.isfinite(elapsed): elapsed = 0
        row = {"event": "chronos.transport.rejected", "request_id": safe_id,
               "code": safe_code, "elapsed_ms": int(max(0, min(3600, elapsed)) * 1000)}
        diagnostics.emit(row)
    except Exception:
        # Diagnostics cannot change the response, spend status or recovery authority.
        pass


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Rejected("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    def constant(_):
        raise Rejected("NONFINITE_JSON")
    def floating(value):
        result = float(value)
        if not math.isfinite(result): raise Rejected("NONFINITE_JSON")
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=floating)
    except (ValueError, UnicodeError, RecursionError):
        raise Rejected("INVALID_JSON") from None


def request_body(raw, expected_schema, model=MODEL, profile_sha256=None, reasoning_effort='none'):
    value = strict_json(raw)
    keys = {"model", "messages", "temperature", "max_tokens", "response_format", "reasoning_effort", "user"}
    contract=response_contract(expected_schema)
    native_v2=contract in ('chronos.agent-proposal.v2',EXTRACTION_CONTRACT,*CONVERSATION_CONTRACTS)
    if contract==EXTRACTION_CONTRACT and profile_sha256 is None:raise Rejected('EXTRACTION_PROFILE_REQUIRED')
    if contract in CONVERSATION_CONTRACTS and profile_sha256 is None:raise Rejected('CONVERSATION_PROFILE_REQUIRED')
    if native_v2:keys.add('chronos_deadline_us')
    if profile_sha256 is not None:keys.add('chronos_profile_sha256')
    if type(value) is not dict or set(value) != keys:
        raise Rejected("REQUEST_FIELDS")
    request_id = value["user"]
    if type(request_id) is not str or not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", request_id):
        raise Rejected("REQUEST_ID")
    if profile_sha256 is not None and value.get('chronos_profile_sha256')!=profile_sha256:
        raise Rejected('PROFILE_MISMATCH')
    if (reasoning_effort not in ("none","low","medium") or (reasoning_effort!="none" and profile_sha256 is None)
            or value["model"] != model or value["reasoning_effort"] != reasoning_effort
            or type(value["temperature"]) not in (int, float) or value["temperature"] != 0
            or type(value["max_tokens"]) is not int or value["max_tokens"] != 2048):
        raise Rejected("REQUEST_POLICY")
    expected = {"type": "json_schema", "json_schema": {"name": {EXTRACTION_CONTRACT:"chronos_e1",CONVERSATION_CONTRACT:"chronos_c1",PLAN_CONTRACT:"chronos_c2",PLAN_V2_CONTRACT:"chronos_c2_v2"}.get(contract,"chronos_a1"), "strict": True, "schema": expected_schema}}
    if json.dumps(value["response_format"], sort_keys=True, separators=(",", ":")) != json.dumps(expected, sort_keys=True, separators=(",", ":")):
        raise Rejected("REQUEST_SCHEMA")
    messages = value["messages"]
    if type(messages) is not list or len(messages) != 2:
        raise Rejected("REQUEST_MESSAGES")
    for message, role in zip(messages, ("system", "user")):
        if (type(message) is not dict or set(message) != {"role", "content"}
                or message["role"] != role or type(message["content"]) is not str
                or not message["content"] or len(message["content"].encode("utf-8")) > 65536):
            raise Rejected("REQUEST_MESSAGES")
    if native_v2:
        deadline=value['chronos_deadline_us'];now=time.time_ns()//1000
        if type(deadline) is not int or not now<deadline<=now+30_000_000:
            raise Rejected('REQUEST_DEADLINE')
    if contract==PLAN_V2_CONTRACT:plan_v2_binding(value)
    return value, request_id


def checked_response(raw, request_id, model=MODEL, profile_sha256=None, contract="chronos.agent-proposal.v2"):
    if contract not in ("chronos.agent-proposal.v1","chronos.agent-proposal.v2",EXTRACTION_CONTRACT,*CONVERSATION_CONTRACTS):raise Rejected("UNSUPPORTED_CONTRACT")
    if contract==EXTRACTION_CONTRACT and profile_sha256 is None:raise Rejected("EXTRACTION_PROFILE_REQUIRED")
    if contract in CONVERSATION_CONTRACTS and profile_sha256 is None:raise Rejected("CONVERSATION_PROFILE_REQUIRED")
    value = strict_json(raw)
    if type(value) is not dict or value.get("model") != model:
        raise Rejected("RESPONSE_MODEL")
    choices = value.get("choices")
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        raise Rejected("RESPONSE_CHOICES")
    choice = choices[0]
    if choice.get("finish_reason") != "stop":
        raise Rejected("INCOMPLETE_RESPONSE")
    message = choice.get("message")
    if type(message) is not dict or message.get("role") != "assistant":
        raise Rejected("RESPONSE_MESSAGE")
    if message.get("tool_calls") or message.get("function_call") or message.get("refusal"):
        raise Rejected("UNEXPECTED_TOOL_OR_REFUSAL")
    content = message.get("content")
    if contract in CONVERSATION_CONTRACTS:
        if type(content) is not str:raise Rejected("CONVERSATION_CONTENT_TYPE")
        if not content:raise Rejected("CONVERSATION_CONTENT_EMPTY")
        if len(content.encode("utf-8"))>(PLAN_RESPONSE_BYTE_LIMIT if contract in PLAN_CONTRACTS else CONVERSATION_RESPONSE_BYTE_LIMIT):raise Rejected("CONVERSATION_CONTENT_LIMIT")
    elif type(content) is not str or not content or len(content.encode("utf-8")) > (2048 if contract==EXTRACTION_CONTRACT else CONTENT_LIMIT):
        raise Rejected("RESPONSE_CONTENT")
    proposal = strict_json(content)
    # Bound-case semantic/freshness validation remains in the native caller.
    # A transport receipt proves completion and shape, never truth or authority.
    fields={EXTRACTION_CONTRACT:EXTRACTION_FIELDS,CONVERSATION_CONTRACT:CONVERSATION_FIELDS,PLAN_CONTRACT:PLAN_FIELDS,PLAN_V2_CONTRACT:PLAN_V2_FIELDS}.get(contract,FIELDS)
    if type(proposal) is not dict or set(proposal) != fields:
        raise Rejected("PROPOSAL_SHAPE")
    if contract==EXTRACTION_CONTRACT and proposal.get("schema_version")!=contract:raise Rejected("EXTRACTION_CONTRACT_MISMATCH")
    if contract==CONVERSATION_CONTRACT:check_conversation_shape(proposal)
    if contract in PLAN_CONTRACTS:check_plan_shape(proposal,contract)
    usage = value.get("usage")
    if type(usage) is not dict:
        raise Rejected("RESPONSE_USAGE")
    numbers = [usage.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")]
    if any(type(n) is not int or not 0 <= n <= 1000000 for n in numbers):
        raise Rejected("RESPONSE_USAGE")
    if numbers[0] + numbers[1] != numbers[2] or numbers[1] > 2048:
        raise Rejected("RESPONSE_USAGE")
    # Rebuild the response: never forward reasoning, upstream extra fields or
    # a spoofed transport receipt. Token counts are provider-declared, not billing.
    receipt = {"version": 1, "request_id": request_id, "finish_reason": "stop", "model": model}
    if profile_sha256 is not None:receipt['profile_sha256']=profile_sha256
    if contract in (EXTRACTION_CONTRACT,*CONVERSATION_CONTRACTS):receipt['response_contract']=contract
    return {"id": "chronos-" + request_id, "object": "chat.completion", "created": int(time.time()),
            "model": model, "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": dict(zip(("prompt_tokens", "completion_tokens", "total_tokens"), numbers)),
            "chronos_transport": receipt}


def check_plan_shape(value,contract=PLAN_CONTRACT):
    """C2 wire constraints only; scope, catalog and truth stay with the host."""
    fields=PLAN_FIELDS if contract==PLAN_CONTRACT else PLAN_V2_FIELDS
    if contract not in PLAN_CONTRACTS or type(value) is not dict or set(value)!=fields or value.get('schema')!=contract:
        raise Rejected('EXPLANATION_PLAN_INVALID')
    for key in ('conversation_id','turn_id'):
        if type(value[key]) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',value[key]):
            raise Rejected('EXPLANATION_PLAN_BINDING_INVALID')
    for key in ('context_digest','catalog_digest'):
        if type(value[key]) is not str or not re.fullmatch(r'[a-f0-9]{64}',value[key]):
            raise Rejected('EXPLANATION_PLAN_BINDING_INVALID')
    detail=value['detail'];preference=value['preference']
    if contract==PLAN_CONTRACT:
        topics=[value['topic']]
        if type(topics[0]) is not str or topics[0] not in PLAN_TOPICS:raise Rejected('EXPLANATION_PLAN_TOPIC_INVALID')
    else:
        if type(value['renderer_version']) is not str or value['renderer_version']!=PLAN_V2_RENDERER:
            raise Rejected('EXPLANATION_PLAN_BINDING_INVALID')
        topics=value['topics']
        if type(topics) is not list:raise Rejected('EXPLANATION_PLAN_TOPICS_TYPE')
        if not 1<=len(topics)<=4:raise Rejected('EXPLANATION_PLAN_TOPICS_COUNT')
        if any(type(t) is not str or t not in PLAN_V2_TOPICS for t in topics):
            raise Rejected('EXPLANATION_PLAN_TOPIC_NAME')
        if len(set(topics))!=len(topics):raise Rejected('EXPLANATION_PLAN_TOPICS_DUPLICATED')
        if 'CLARIFY' in topics and len(topics)!=1:raise Rejected('EXPLANATION_PLAN_CLARIFY_MIXED')
    if type(detail) is not str or detail not in ('concise','detailed'):raise Rejected('EXPLANATION_PLAN_DETAIL_INVALID')
    if 'PREFERENCE_CHANGE' in topics:
        if type(preference) is not str or preference not in ('CHEAPEST_ON_TIME','EARLIEST_ALLOWED'):
            code=('EXPLANATION_PLAN_PREFERENCE_MISSING' if preference is None else 'EXPLANATION_PLAN_PREFERENCE_VALUE') if contract==PLAN_V2_CONTRACT else 'EXPLANATION_PLAN_PREFERENCE_INVALID'
            raise Rejected(code)
    elif preference is not None:
        raise Rejected('EXPLANATION_PLAN_PREFERENCE_UNEXPECTED' if contract==PLAN_V2_CONTRACT else 'EXPLANATION_PLAN_PREFERENCE_INVALID')


def check_conversation_shape(value):
    """Wire constraints only. The native finish() binds evidence, turn and scope."""
    def bad(code="CONVERSATION_RESPONSE_INVALID"): raise Rejected(code)
    def identifier(v): return type(v) is str and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}",v)
    if type(value) is not dict or set(value)!=CONVERSATION_FIELDS:bad()
    if value['schema']!=CONVERSATION_CONTRACT:bad('CONVERSATION_SCHEMA_INVALID')
    if not identifier(value['conversation_id']) or not identifier(value['turn_id']):bad('CONVERSATION_BINDING_INVALID')
    digest=value['context_digest']
    if type(digest) is not str or not re.fullmatch(r"[a-f0-9]{64}",digest):bad("CONVERSATION_BINDING_INVALID")
    intent=value['intent']
    if type(intent) is not str or intent not in {'ANSWER','RESULT_QUERY','APPROVAL_REDIRECT','PREFERENCE_PROPOSAL'}:bad('CONVERSATION_INTENT_INVALID')
    answer=value['answer']
    try:
        if (type(answer) is not str or not 1<=len(answer)<=CONVERSATION_ANSWER_CHAR_LIMIT
                or len(answer.encode('utf-8'))>CONVERSATION_ANSWER_BYTE_LIMIT):bad('CONVERSATION_ANSWER_INVALID')
    except UnicodeError:bad('CONVERSATION_ANSWER_INVALID')
    sources=value['source_ids']
    if (type(sources) is not list or len(sources)>16 or any(not identifier(x) for x in sources)
            or len(set(sources))!=len(sources) or (not sources and intent!='APPROVAL_REDIRECT')):bad('CONVERSATION_SOURCES_INVALID')
    preference=value['preference']
    if intent=='PREFERENCE_PROPOSAL':
        if type(preference) is not str or preference not in {'CHEAPEST_ON_TIME','EARLIEST_ALLOWED'}:bad('CONVERSATION_PREFERENCE_INVALID')
    elif preference is not None:bad('CONVERSATION_PREFERENCE_INVALID')


class Claims:
    """Durably spend a request ID before IO; replay cannot trigger another call."""
    def __init__(self, path):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS transport_claims (id TEXT PRIMARY KEY, digest TEXT NOT NULL, created REAL NOT NULL, result TEXT NOT NULL)")

    def claim(self, request_id, digest, deadline_us=None):
        try:
            with closing(sqlite3.connect(self.path, timeout=1)) as db, db:
                db.execute("INSERT INTO transport_claims VALUES (?,?,?,?)", (request_id, digest, time.time(), "IN_FLIGHT"))
        except sqlite3.IntegrityError:
            raise Rejected("REQUEST_ALREADY_USED") from None
        except sqlite3.Error:
            raise Rejected("CLAIM_UNAVAILABLE") from None

    def finish(self, request_id, result):
        try:
            with closing(sqlite3.connect(self.path, timeout=1)) as db, db:
                db.execute("UPDATE transport_claims SET result=? WHERE id=?", (result, request_id))
        except sqlite3.Error:
            # A retained IN_FLIGHT claim remains spent and blocks repeat inference.
            pass


@dataclass(frozen=True)
class Settings:
    schema: dict
    claims: Claims
    upstream_port: int = 11513
    budget_seconds: float = 28
    model: str = MODEL
    profile_sha256: str | None = None
    reasoning_effort: str = "none"


class BudgetedClaims:
    """Adapter for a separately initialized, immutable installation allowance."""
    def __init__(self,allowance):self.allowance=allowance

    def claim(self,request_id,digest,deadline_us=None):
        from deployment import DeploymentError
        try:return self.allowance.claim(request_id,digest,deadline_us)
        except (DeploymentError,sqlite3.Error) as exc:
            code=str(exc) if isinstance(exc,DeploymentError) else 'ALLOWANCE_UNAVAILABLE'
            raise Rejected(code) from None

    def finish(self,request_id,result):
        from deployment import DeploymentError
        outcome='VERIFIED_STOP' if result=='VERIFIED_STOP' else 'UNCERTAIN'
        try:self.allowance.finish(request_id,outcome)
        except (DeploymentError,sqlite3.Error):pass # The committed slot stays spent.


def validate_profile_schema(schema,profile):
    if profile.provider!='ollama':raise ValueError('REMOTE_PROVIDER_NOT_ENABLED')
    digest=sha256(json.dumps(schema,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
    if profile.schema_sha256!=digest:raise ValueError('PROFILE_SCHEMA_MISMATCH')
    if response_contract(schema)!=profile.response_contract:
        raise ValueError('PROFILE_RESPONSE_CONTRACT_MISMATCH')


def configured_settings(schema,allowance,budget_seconds=28):
    profile=allowance.profile
    validate_profile_schema(schema,profile)
    return Settings(schema,BudgetedClaims(allowance),profile.local_port,budget_seconds,profile.model,profile.digest,profile.reasoning_effort)


class _CancellableReader(io.RawIOBase):
    """Keep the HTTP parser, but never trap its reader in a long socket wait."""
    def __init__(self, sock, cancelled, deadline):
        super().__init__()
        self.sock, self.cancelled, self.deadline = sock, cancelled, deadline
        # A real makefile reference retains the socket through HTTP/1.0 close.
        # Never read this lease: SocketIO cannot resume after its own timeout.
        self.lease = None
        self.lease = sock.makefile("rb", buffering=0)

    def readable(self):
        return True

    def readinto(self, buffer):
        if self.closed:
            raise ValueError("read of closed transport")
        if not len(buffer):
            return 0
        while True:
            remaining = self.deadline - time.monotonic()
            if self.cancelled.is_set() or remaining <= 0:
                raise OSError("transport cancelled")
            readable, _, _ = select.select([self.sock], [], [], min(.05, remaining))
            if self.cancelled.is_set() or time.monotonic() >= self.deadline:
                raise OSError("transport cancelled")
            if not readable:
                continue
            try:
                return self.sock.recv_into(buffer)
            except (BlockingIOError, socket.timeout):
                # No HTTP bytes were consumed: continue this read, not a request.
                continue

    def close(self):
        try:
            if not self.closed and self.lease is not None:
                self.lease.close()
        finally:
            super().close()


class _ResponseSocket:
    def __init__(self, sock, cancelled, deadline):
        self.sock, self.cancelled, self.deadline = sock, cancelled, deadline

    def makefile(self, mode):
        if mode != "rb":
            raise ValueError("unsupported HTTP reader mode")
        return io.BufferedReader(_CancellableReader(self.sock, self.cancelled, self.deadline))


def upstream_exchange(settings, body, disconnected=lambda: False, absolute_deadline=None,
                      *, method="POST", path="/v1/chat/completions"):
    """Bounded loopback I/O shared by version admission and model dispatch."""
    began = time.monotonic()
    budget=settings.budget_seconds
    if body is not None and 'chronos_deadline_us' in body:
        budget=min(budget,(body['chronos_deadline_us']-time.time_ns()//1000)/1_000_000)
    if absolute_deadline is not None:
        budget=min(budget,absolute_deadline-began)
    if budget<=0:raise Rejected('UPSTREAM_TIMEOUT')
    deadline = began + budget
    conn = http.client.HTTPConnection("127.0.0.1", settings.upstream_port, timeout=budget)
    conn.auto_open = 0
    cancelled, finished = Event(), Event()
    sock = None
    response = None
    def cancel():
        cancelled.set()
        if sock is not None:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        # HTTPConnection/HTTPResponse belong to the calling thread. Closing
        # them here races response construction and buffered parser state.
    def watch():
        while not finished.wait(0.05):
            if disconnected():
                cancel()
                return
    timer = Timer(budget, cancel)
    timer.daemon = True
    observer = Thread(target=watch, daemon=True)
    try:
        timer.start()
        conn.connect()
        # Retain the actual socket; the response reader owns its makefile lease.
        # Cooperative reads also work where cross-thread shutdown does not wake
        # an already blocked recv promptly.
        sock = conn.sock
        if cancelled.is_set() or time.monotonic() >= deadline:
            raise Rejected("UPSTREAM_TIMEOUT")
        observer.start()
        upstream_body=({k:v for k,v in body.items() if k not in ('chronos_deadline_us','chronos_profile_sha256')}
                       if body is not None else None)
        payload=json.dumps(upstream_body).encode("utf-8") if upstream_body is not None else None
        conn.request(method, path, body=payload,
                     headers={"Content-Type": "application/json", "Accept": "application/json", "Connection": "close"})
        sock.settimeout(.05)
        def response_factory(response_sock, *args, **kwargs):
            return http.client.HTTPResponse(_ResponseSocket(response_sock, cancelled, deadline), *args, **kwargs)
        conn.response_class = response_factory
        response = conn.getresponse()
        if response.status != 200:
            raise Rejected("UPSTREAM_HTTP_ERROR")
        if response.getheader("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            raise Rejected("UPSTREAM_CONTENT_TYPE")
        if response.getheader("Content-Encoding", "identity") != "identity":
            raise Rejected("UPSTREAM_ENCODING")
        length = response.getheader("Content-Length")
        if length is not None and (not length.isascii() or not length.isdecimal() or len(length) > 8 or int(length) > RESPONSE_LIMIT):
            raise Rejected("UPSTREAM_SIZE")
        chunks, size = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if cancelled.is_set() or remaining <= 0:
                raise Rejected("UPSTREAM_TIMEOUT")
            chunk = response.read1(min(4096, RESPONSE_LIMIT + 1 - size))
            if not chunk: break
            chunks.append(chunk)
            size += len(chunk)
            if size > RESPONSE_LIMIT: raise Rejected("UPSTREAM_SIZE")
        if cancelled.is_set() or time.monotonic() >= deadline:
            raise Rejected("UPSTREAM_TIMEOUT")
        if length is not None and size != int(length):
            raise Rejected("UPSTREAM_INCOMPLETE_BODY")
        return b"".join(chunks)
    except (OSError, http.client.HTTPException):
        raise Rejected("UPSTREAM_TIMEOUT" if cancelled.is_set() or time.monotonic() >= deadline else "UPSTREAM_UNAVAILABLE") from None
    finally:
        finished.set()
        timer.cancel()
        if response is not None: response.close()
        conn.close()
        if sock is not None: sock.close()
        if observer.is_alive(): observer.join(timeout=0.2)



# Only this provider version has been source-reviewed for both controls.
# A version string is compatibility admission, not authentication of a hostile
# provider. The installation must retain its pinned, trusted local image.
NATIVE_CONTEXT_VERSION = "0.40.13"


def verify_context_policy(settings, disconnected=lambda: False, absolute_deadline=None):
    raw=upstream_exchange(settings,None,disconnected,absolute_deadline,
                          method="GET",path="/api/version")
    value=strict_json(raw)
    if type(value) is not dict or value != {"version":NATIVE_CONTEXT_VERSION}:
        raise Rejected("CONTEXT_POLICY_UNSUPPORTED")


def plan_v2_binding(body):
    """Validate structured binding only. This never authenticates a case/user."""
    try:
        wire=strict_json(body["messages"][1]["content"])
        fields={'schema','renderer_version','conversation_id','turn_id',
                'context_digest','catalog_digest','message','history',
                'available_topics','case_explanations'}
        if type(wire) is not dict or set(wire)!=fields:
            raise Rejected('EXPLANATION_REQUEST_BINDING_INVALID')
        binding={k:wire[k] for k in ('schema','renderer_version','conversation_id',
                                    'turn_id','context_digest','catalog_digest')}
        # Reuse the wire type/format checks without model-selected subjects.
        check_plan_shape(binding|dict(topics=['DECISION'],detail='concise',preference=None),PLAN_V2_CONTRACT)
        return binding
    except (Rejected,KeyError,IndexError,TypeError):
        raise Rejected('EXPLANATION_REQUEST_BINDING_INVALID') from None


def native_conversation_schema(body):
    schema=deepcopy(body["response_format"]["json_schema"]["schema"])
    if response_contract(schema)==PLAN_V2_CONTRACT:
        binding=plan_v2_binding(body)
        for key,value in binding.items():schema['properties'][key]['enum']=[value]
        # Generation order only; host validation and canonical profile are unchanged.
        order=(*binding,'topics','detail','preference')
        schema['properties']={key:schema['properties'][key] for key in order}
    return schema


def native_conversation_request(body):
    # Shared local E1/chat bridge; E1 keeps its original extraction schema.
    # Called only after the public request has passed request_body(). Never
    # trim history, rewrite messages, alter context size, or enable tools.
    return {"model":body["model"],"messages":body["messages"],
            "format":native_conversation_schema(body),
            "stream":False,"truncate":False,"shift":False,
            "think":False if body["reasoning_effort"]=="none" else body["reasoning_effort"],
            "options":{"temperature":body["temperature"],"num_predict":body["max_tokens"]}}


def native_conversation_response(raw,settings,request_id):
    value=strict_json(raw)
    if type(value) is not dict or "error" in value:
        raise Rejected("NATIVE_RESPONSE_INVALID")
    if value.get("model")!=settings.model:raise Rejected("RESPONSE_MODEL")
    if value.get("done") is not True or value.get("done_reason")!="stop":
        raise Rejected("INCOMPLETE_RESPONSE")
    message=value.get("message")
    if type(message) is not dict:raise Rejected("RESPONSE_MESSAGE")
    if any(message.get(k) for k in ("tool_calls","function_call","refusal")):
        raise Rejected("UNEXPECTED_TOOL_OR_REFUSAL")
    # Record presence only; never retain or expose provider thinking.
    if message.get("content")=="" and type(message.get("thinking")) is str and message["thinking"]:
        raise Rejected("CONVERSATION_THINKING_ONLY")
    prompt,completion=value.get("prompt_eval_count"),value.get("eval_count")
    if any(type(n) is not int or not 0<=n<=1000000 for n in (prompt,completion)):
        raise Rejected("RESPONSE_USAGE")
    # Discard thinking, timings, context tokens and any forged receipt.
    envelope={"model":value["model"],"choices":[{"finish_reason":"stop",
              "message":{"role":message.get("role"),"content":message.get("content")}}],
              "usage":{"prompt_tokens":prompt,"completion_tokens":completion,"total_tokens":prompt+completion}}
    return checked_response(json.dumps(envelope),request_id,settings.model,
                            settings.profile_sha256,response_contract(settings.schema))


def forward(settings, body, request_id, disconnected=lambda: False, absolute_deadline=None):
    if 'chronos_deadline_us' in body:
        wire_deadline=time.monotonic()+(body['chronos_deadline_us']-time.time_ns()//1000)/1_000_000
        absolute_deadline=min(absolute_deadline,wire_deadline) if absolute_deadline is not None else wire_deadline
    contract=response_contract(settings.schema)
    if contract in NATIVE_CONTEXT_CONTRACTS:
        raw=upstream_exchange(settings,native_conversation_request(body),disconnected,
                              absolute_deadline,path="/api/chat")
        return native_conversation_response(raw,settings,request_id)
    raw=upstream_exchange(settings,body,disconnected,absolute_deadline)
    return checked_response(raw,request_id,settings.model,settings.profile_sha256,contract)


def make_server(settings, port=11512):
    if response_contract(settings.schema) in CONVERSATION_CONTRACTS and settings.profile_sha256 is None:raise ValueError("CONVERSATION_PROFILE_REQUIRED")
    if response_contract(settings.schema)==EXTRACTION_CONTRACT and settings.profile_sha256 is None:raise ValueError("EXTRACTION_PROFILE_REQUIRED")
    if settings.reasoning_effort not in ("none","low","medium") or (settings.reasoning_effort!="none" and settings.profile_sha256 is None):
        raise ValueError("REASONING_PROFILE_REQUIRED")
    if not 0 < settings.budget_seconds <= 28 or not 1024 <= settings.upstream_port <= 65535:
        raise ValueError("Invalid fixed deployment settings")
    if not isinstance(settings.model,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',settings.model):
        raise ValueError('INVALID_MODEL')
    if settings.profile_sha256 is None:
        if settings.model!=MODEL:raise ValueError('PROFILE_REQUIRED')
    elif not re.fullmatch(r'[a-f0-9]{64}',settings.profile_sha256):raise ValueError('INVALID_PROFILE_DIGEST')
    lock = Lock()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(2)
            self.operation_expired = Event()
            self.operation_deadline = float("inf")
            def expire_headers():
                try: self.connection.shutdown(socket.SHUT_RDWR)
                except OSError: pass
            self.header_timer = Timer(2, expire_headers)
            self.header_timer.daemon = True
            self.header_timer.start()
        def finish(self):
            self.header_timer.cancel()
            super().finish()
        def log_message(self, *_): pass
        def expired(self):
            return self.operation_expired.is_set() or time.monotonic() >= self.operation_deadline
        def reply(self, status, value):
            if self.expired():
                self.close_connection = True
                return
            raw = json.dumps(value, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self): self.reply(404, {"error": {"code": "ROUTE_NOT_ALLOWED"}})
        def do_POST(self):
            self.header_timer.cancel()
            claimed, held, operation_timer = None, False, None
            began = time.monotonic()
            try:
                self.connection.settimeout(2)
                if self.path != "/v1/chat/completions" or self.headers.get("Transfer-Encoding"):
                    raise Rejected("ROUTE_OR_ENCODING")
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal() or not 0 < int(lengths[0]) <= REQUEST_LIMIT:
                    raise Rejected("REQUEST_SIZE")
                incoming_deadline = time.monotonic() + 2
                chunks, incoming_size = [], 0
                while incoming_size < int(lengths[0]):
                    remaining = incoming_deadline - time.monotonic()
                    if remaining <= 0: raise Rejected("REQUEST_TIMEOUT")
                    self.connection.settimeout(remaining)
                    chunk = self.rfile.read1(min(4096, int(lengths[0]) - incoming_size))
                    if not chunk: break
                    chunks.append(chunk); incoming_size += len(chunk)
                raw = b"".join(chunks)
                if len(raw) != int(lengths[0]): raise Rejected("REQUEST_BODY_INCOMPLETE")
                value, request_id = request_body(raw, settings.schema,settings.model,settings.profile_sha256,settings.reasoning_effort)
                # Bound the whole validated operation, including slow durable I/O.
                # Closing the client never cancels persistence or refunds a claim.
                remaining = OPERATION_LIMIT_SECONDS
                if 'chronos_deadline_us' in value:
                    remaining = min(remaining, (value['chronos_deadline_us']-time.time_ns()//1000)/1_000_000)
                self.operation_deadline = time.monotonic() + max(0, remaining)
                client_socket = self.connection
                def expire_operation():
                    self.operation_expired.set()
                    try: client_socket.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                operation_timer = Timer(max(0, remaining), expire_operation)
                operation_timer.daemon = True
                operation_timer.start()
                held = lock.acquire(blocking=False)
                if not held: raise Rejected("BUSY_NO_RETRY")
                if self.expired(): raise Rejected("REQUEST_TIMEOUT")
                def disconnected():
                    if self.expired(): return True
                    try:
                        readable, _, _ = select.select([self.connection], [], [], 0)
                        return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
                    except OSError: return True
                # GET and POST share the network budget. Capability rejection
                # precedes the durable inference claim and performs no inference.
                transport_deadline=self.operation_deadline
                if response_contract(settings.schema) in NATIVE_CONTEXT_CONTRACTS:
                    transport_deadline=min(transport_deadline,time.monotonic()+settings.budget_seconds)
                    verify_context_policy(settings,disconnected,transport_deadline)
                if self.expired() or time.monotonic()>=transport_deadline:
                    raise Rejected("REQUEST_TIMEOUT")
                settings.claims.claim(request_id, sha256(raw).hexdigest(),value.get('chronos_deadline_us',time.time_ns()//1000+int(settings.budget_seconds*1_000_000)))
                claimed = request_id
                if self.expired(): raise Rejected("REQUEST_TIMEOUT")
                result = forward(settings, value, request_id, disconnected, transport_deadline)
                settings.claims.finish(request_id, "VERIFIED_STOP")
                self.reply(200, result)
            except Rejected as exc:
                if claimed: settings.claims.finish(claimed, exc.code)
                record_rejection(claimed, exc.code, began, self.server.diagnostics)
                try: self.reply(422, {"error": {"code": exc.code}})
                except OSError: pass
            except (OSError, ValueError, sqlite3.Error):
                if claimed: settings.claims.finish(claimed, "GUARD_ERROR")
                record_rejection(claimed, "GUARD_ERROR", began, self.server.diagnostics)
                try: self.reply(422, {"error": {"code": "GUARD_ERROR"}})
                except OSError: pass
            finally:
                if operation_timer is not None: operation_timer.cancel()
                if held: lock.release()
    class Server(ThreadingHTTPServer):
        def server_close(self):
            if hasattr(self, "diagnostics"):
                self.diagnostics.close()
            super().server_close()
    server = Server(("127.0.0.1", port), Handler)
    try:
        server.diagnostics = DiagnosticWriter()
    except Exception:
        server.server_close()
        raise
    return server


def listener_port(contract, requested=None, upstream=None):
    """CLI policy only; synthetic in-process tests may still bind an ephemeral port."""
    port = (11514 if contract in ("c1","c2","c2-v2") else 11512) if requested is None else requested
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("INVALID_LISTENER_PORT")
    if (contract in ("c1","c2","c2-v2") and port == 11512) or (contract not in ("c1","c2","c2-v2") and port == 11514):
        raise ValueError("LISTENER_RESERVED_FOR_OTHER_CONTRACT")
    if port == upstream:
        raise ValueError("LISTENER_EQUALS_UPSTREAM")
    return port


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--contract", choices=("v1", "v2", "e1", "c1", "c2", "c2-v2"), default="v1")
    parser.add_argument('--profile',type=Path,help='Local installation profile; remote execution remains disabled')
    parser.add_argument('--initialize-allowance',action='store_true',help='Explicit first installation only; refuses an existing allowance')
    parser.add_argument("--listen-port", type=int,
                        help="Loopback listener: C1/C2 default to 11514; other contracts to 11512")
    args = parser.parse_args(argv)
    try: port = listener_port(args.contract, args.listen_port)
    except ValueError as exc: raise SystemExit(str(exc)) from None
    if ".." in args.state_dir.parts: raise SystemExit("INVALID_STATE_PATH")
    state = args.state_dir.resolve()
    project = Path(__file__).resolve().parents[2]
    if not state.is_relative_to(project / "runtime"):
        raise SystemExit("State must be under this project's runtime directory")
    schema_name = {"v1":"proposal-schema.json","v2":"proposal-schema-v2.json","e1":"extraction-schema.json","c1":"conversation-schema.json","c2":"conversation-plan-schema.json","c2-v2":"conversation-plan-v2-schema.json"}[args.contract]
    if args.contract=="e1" and args.profile is None:raise SystemExit("EXTRACTION_PROFILE_REQUIRED")
    if args.contract in ("c1","c2","c2-v2") and args.profile is None:raise SystemExit("CONVERSATION_PROFILE_REQUIRED")
    schema = strict_json(Path(__file__).with_name(schema_name).read_text(encoding="utf-8"))
    if args.initialize_allowance and args.profile is None:raise SystemExit('PROFILE_REQUIRED')
    if args.profile is not None:
        from deployment import Profile,Allowance,check_conversation_state
        if args.contract in ("c1","c2","c2-v2"):
            if args.initialize_allowance: raise SystemExit("CONVERSATION_USE_EXPLICIT_PREPARATION")
            try: check_conversation_state(args.state_dir.absolute(), args.profile)
            except (OSError, ValueError): raise SystemExit("CONVERSATION_STATE_REJECTED_PRESERVED") from None
        with args.profile.open('rb') as f:profile=Profile.parse(f.read(4097))
        try:
            validate_profile_schema(schema,profile)
            listener_port(args.contract, port, profile.local_port)
        except ValueError as exc:raise SystemExit(str(exc)) from None
        if (state/'transport-claims.sqlite').exists():raise SystemExit('PROFILE_MIGRATION_REQUIRED')
        state.mkdir(parents=True,exist_ok=True)
        allowance=(Allowance.create if args.initialize_allowance else Allowance)(state/'allowance.sqlite',profile)
        if args.contract in ("c1","c2","c2-v2"):
            # Opening only checks profile identity. Inspect claims before binding;
            # a partial initialization must not announce an available listener.
            try: allowance.snapshot()
            except (ValueError, sqlite3.Error): raise SystemExit("CONVERSATION_ALLOWANCE_UNAVAILABLE") from None
        settings=configured_settings(schema,allowance)
    else:
        if (state/'allowance.sqlite').exists():raise SystemExit('INSTALLED_PROFILE_REQUIRED')
        try: listener_port(args.contract, port, Settings(schema, None).upstream_port)
        except ValueError as exc: raise SystemExit(str(exc)) from None
        state.mkdir(parents=True,exist_ok=True)
        settings=Settings(schema, Claims(state / "transport-claims.sqlite"))
    server = make_server(settings, port)
    try:
        print(f"CHRONOS_TRANSPORT_READY 127.0.0.1:{port} -> 127.0.0.1:{settings.upstream_port}", flush=True)
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()


def _stop_on_sigterm(_signum, _frame):
    # Unwind the listener on Docker stop. Any committed claim stays spent.
    raise SystemExit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _stop_on_sigterm)
    main()
