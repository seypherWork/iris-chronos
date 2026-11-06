import test from "node:test";
import assert from "node:assert/strict";
import {createChronosClient, ChronosClientError} from "../../src/chronos_web/client.mjs";

const token = "a".repeat(64); // Synthetic token; never a real session credential.
const origin = "https://chronos.example";
const config = {pageUrl: origin + "/ui/index.html", basePath: "/csp/chronos", timeoutMs: 300};
const session = (extra = {}) => ({code: "CONNECTED", authenticated: true,
  canRead: true, canApprove: true, csrf: token, ...extra});
const json = (data, status = 200) => new Response(JSON.stringify(data),
  {status, headers: {"Content-Type": "application/json; charset=utf-8"}});
const packet = (data = {}, code = "READ_ONLY") => ({code, traceSessionId: 12, data});
const deferred = () => { let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve}; };
const callsOf = handler => {
  const calls = [];
  return {calls, fetchImpl: (url, options) => {calls.push({url, options}); return handler(url, options, calls.length);}};
};
const codeIs = (code, applied = undefined) => error =>
  error instanceof ChronosClientError && error.code === code &&
  (applied === undefined || error.mayHaveApplied === applied);

test("connect uses only same-origin cookies and keeps CSRF out of exposed status", async () => {
  const wire = callsOf(() => json(session()));
  const client = createChronosClient({...config, ...wire});
  assert.equal(wire.calls.length, 0);
  assert.deepEqual(await client.connect(), {connected: true, canRead: true, canApprove: true});
  assert.equal(wire.calls.length, 1);
  const {url, options} = wire.calls[0];
  assert.equal(url, origin + "/csp/chronos/session");
  assert.equal(options.method, "GET");
  assert.equal(options.credentials, "same-origin");
  assert.equal(options.mode, "same-origin");
  assert.equal(options.redirect, "error");
  assert.equal(options.cache, "no-store");
  assert.equal(options.referrerPolicy, "no-referrer");
  assert.equal(options.body, undefined);
  assert.equal(options.headers.Authorization, undefined);
  assert.equal(JSON.stringify(client.sessionStatus()).includes(token), false);
  assert.ok(Object.isFrozen(client.sessionStatus()));
});

test("the eight explicit commands use exact server route families and two-field bodies", async () => {
  const wire = callsOf((url) => json(url.endsWith("/session") ? session() : packet()));
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  for (const [method, command, route] of [
    ["readDecision", "DECISION", "decision"], ["readDecisionDetail", "DECISION_DETAIL", "decision"], ["resolveDecision", "RESOLVE_DECISION", "decision"],
    ["preview", "PREVIEW", "approval"], ["readPreview", "READ", "approval"],
    ["confirmPreview", "CONFIRM", "approval"], ["rejectPreview", "REJECT", "approval"],
    ["reconcilePreview", "RECONCILE", "approval"],
  ]) {
    await client[method]("owned.id-1");
    const call = wire.calls.at(-1);
    assert.equal(call.url, origin + "/csp/chronos/" + route);
    assert.deepEqual(JSON.parse(call.options.body), {command, id: "owned.id-1"});
    assert.equal(call.options.headers["X-Chronos-CSRF"], token);
    assert.equal(call.options.body.includes(token), false);
  }
  assert.equal(wire.calls.length, 9);
});

test("untrusted installation paths cannot redirect session material", () => {
  for (const basePath of ["https://evil.example/api", "//evil.example", "/../evil", "/a/./b",
    "/a\\b", "/a%2fb", "/a?url=evil", "/a#evil", "/", "/a//b", "/a/../b", "api"]) {
    assert.throws(() => createChronosClient({...config, basePath}), codeIs("INVALID_INSTALLATION"));
  }
  for (const pageUrl of ["file:///a", "http://chronos.example", "https://name:secret@chronos.example"]) {
    assert.throws(() => createChronosClient({...config, pageUrl}), codeIs("INVALID_INSTALLATION"));
  }
  for (const pageUrl of ["http://127.0.0.1:1234/ui", "http://[::1]:1234/ui", "https://chronos.example/ui"]) {
    assert.ok(createChronosClient({...config, pageUrl}));
  }
});

test("invalid IDs and disconnected calls never send a request", async () => {
  const wire = callsOf(() => {throw new Error("must not be called");});
  const client = createChronosClient({...config, ...wire});
  for (const id of ["", "../x", "a b", "a?b", "x".repeat(129), null, 17]) {
    await assert.rejects(client.confirmPreview(id), codeIs("INVALID_REQUEST", false));
  }
  await assert.rejects(client.readDecision("d1"), codeIs("SESSION_REQUIRED", false));
  assert.equal(wire.calls.length, 0);
});

test("reader can consult/reconcile but cannot create or authorize changes", async () => {
  const wire = callsOf(url => json(url.endsWith("/session") ? session({canApprove: false}) : packet()));
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  for (const method of ["resolveDecision", "preview", "confirmPreview", "rejectPreview"]) {
    await assert.rejects(client[method]("p1"), codeIs("PERMISSION_DENIED", false));
  }
  for (const method of ["readDecision", "readDecisionDetail", "readPreview", "reconcilePreview"]) await client[method]("p1");
  assert.equal(wire.calls.length, 5);
});

test("revoked reader can bootstrap only to log out", async () => {
  const wire = callsOf(url => json(url.endsWith("/session") ?
    session({code: "ACCESS_REVOKED", canRead: false, canApprove: false}) : {code: "SESSION_ENDED"}));
  const client = createChronosClient({...config, ...wire});
  assert.deepEqual(await client.connect(), {connected: true, canRead: false, canApprove: false});
  await assert.rejects(client.readDecision("d1"), codeIs("PERMISSION_DENIED"));
  await assert.rejects(client.readDecisionDetail("d1"), codeIs("PERMISSION_DENIED"));
  assert.deepEqual(await client.logout(), {code: "SESSION_ENDED"});
  assert.deepEqual(client.sessionStatus(), {connected: false, canRead: false, canApprove: false});
  assert.equal(wire.calls.length, 2);
});

test("invalid session shapes cannot grant capabilities", async () => {
  for (const bad of [
    session({authenticated: "true"}), session({canApprove: 1}),
    session({canRead: false, canApprove: true}), session({csrf: "not-a-token"}),
    session({code: "ACCESS_REVOKED"}), {code: "CONNECTED"},
  ]) {
    const client = createChronosClient({...config, fetchImpl: () => json(bad)});
    await assert.rejects(client.connect(), codeIs("INVALID_SESSION"));
    assert.equal(client.sessionStatus().connected, false);
  }
});

test("a timeout after confirm is uncertain and never retries or dispatches again", async () => {
  const wire = callsOf(url => url.endsWith("/session") ? json(session()) : new Promise(() => {}));
  const client = createChronosClient({...config, ...wire, timeoutMs: 20});
  await client.connect();
  await assert.rejects(client.confirmPreview("original-preview"), error => {
    assert.equal(error.code, "REQUEST_TIMEOUT");
    assert.equal(error.command, "CONFIRM");
    assert.equal(error.id, "original-preview");
    assert.equal(error.readbackRequired, true);
    return true;
  });
  assert.equal(wire.calls.length, 2);
  assert.equal(wire.calls[1].options.signal.aborted, true);
  assert.equal(client.sessionStatus().connected, false);
  await assert.rejects(client.confirmPreview("original-preview"), codeIs("SESSION_REQUIRED", false));
  assert.equal(wire.calls.length, 2);
});

test("overlapping button clicks send only one command", async () => {
  const held = deferred();
  const wire = callsOf(url => url.endsWith("/session") ? json(session()) : held.promise);
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  const first = client.confirmPreview("p1");
  await assert.rejects(client.confirmPreview("p1"), codeIs("REQUEST_IN_PROGRESS", false));
  assert.equal(wire.calls.length, 2);
  held.resolve(json(packet({state: "UNKNOWN", operationId: "op1"}, "RESULT_UNCERTAIN")));
  assert.equal((await first).data.state, "UNKNOWN");
});

test("a superseded connect cannot revive older permissions", async () => {
  const old = deferred();
  const wire = callsOf((_, __, n) => n === 1 ? old.promise : json(session({canApprove: false})));
  const client = createChronosClient({...config, ...wire});
  const first = assert.rejects(client.connect(), codeIs("CONNECTION_CHANGED"));
  await client.connect();
  old.resolve(json(session()));
  await first;
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(client.sessionStatus(), {connected: true, canRead: true, canApprove: false});
});

test("disconnect aborts pending confirm without claiming it did not happen", async () => {
  const held = deferred();
  const wire = callsOf(url => url.endsWith("/session") ? json(session()) : held.promise);
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  const pending = assert.rejects(client.confirmPreview("p1"), codeIs("CONNECTION_CHANGED", true));
  client.disconnect();
  held.resolve(json(packet({state: "ACCEPTED"})));
  await pending;
  assert.equal(client.sessionStatus().connected, false);
});

test("HTTP permission failure clears existing session capabilities", async () => {
  const wire = callsOf(url => json(url.endsWith("/session") ? session() :
    {code: "PERMISSION_DENIED"}, url.endsWith("/session") ? 200 : 403));
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  await assert.rejects(client.readDecision("d1"), codeIs("SESSION_REQUIRED", false));
  assert.equal(client.sessionStatus().connected, false);
});

test("permission failure inside a successful HTTP envelope still clears session", async () => {
  const wire = callsOf(url => json(url.endsWith("/session") ? session() :
    packet({code: "PERMISSION_DENIED"}, "OK")));
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  await assert.rejects(client.readPreview("p1"), codeIs("SESSION_REQUIRED"));
  assert.equal(client.sessionStatus().connected, false);
});

test("HTML, redirects, invalid UTF8 and non-JSON cannot become a connected session", async () => {
  for (const response of [
    new Response("<h1>Sign in private details</h1>", {headers: {"Content-Type": "text/html"}}),
    new Response(null, {status: 302, headers: {Location: "https://evil.example"}}),
    new Response(new Uint8Array([0xff]), {headers: {"Content-Type": "application/json"}}),
    json(["CONNECTED"]), json({code: "<script>secret</script>"}),
  ]) {
    const client = createChronosClient({...config, fetchImpl: () => response});
    await assert.rejects(client.connect(), error => {
      assert.ok(error instanceof ChronosClientError);
      assert.equal(error.message.includes("private"), false);
      assert.equal(error.message.includes("secret"), false);
      return true;
    });
    assert.equal(client.sessionStatus().connected, false);
  }
});

test("response URL changes are rejected before consuming data", async () => {
  const response = json(session());
  Object.defineProperty(response, "url", {value: "https://evil.example/session"});
  const client = createChronosClient({...config, fetchImpl: () => response});
  await assert.rejects(client.connect(), codeIs("UNEXPECTED_RESPONSE_URL"));
});

test("both declared and streamed response size are bounded", async () => {
  const tooLarge = json(session());
  tooLarge.headers.set("Content-Length", String(512 * 1024 + 1));
  for (const response of [tooLarge,
    new Response(" ".repeat(512 * 1024 + 1), {headers: {"Content-Type": "application/json"}})]) {
    const client = createChronosClient({...config, fetchImpl: () => response});
    await assert.rejects(client.connect(), codeIs("RESPONSE_TOO_LARGE"));
  }
});

test("a stalled response body also times out without retry", async () => {
  let cancelled = false;
  const response = new Response(new ReadableStream({cancel() {cancelled = true;}}),
    {headers: {"Content-Type": "application/json"}});
  const wire = callsOf(() => response);
  const client = createChronosClient({...config, ...wire, timeoutMs: 20});
  await assert.rejects(client.connect(), codeIs("REQUEST_TIMEOUT", false));
  assert.equal(wire.calls.length, 1);
  assert.equal(cancelled, true);
});

test("transport exceptions do not expose raw error text or session material", async () => {
  const wire = callsOf(url => {
    if (url.endsWith("/session")) return json(session());
    throw new Error("private password=" + token);
  });
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  await assert.rejects(client.rejectPreview("p1"), error => {
    assert.equal(error.code, "TRANSPORT_UNAVAILABLE");
    assert.equal(error.mayHaveApplied, true);
    assert.equal(JSON.stringify(error).includes(token), false);
    assert.equal(error.message.includes("password"), false);
    return true;
  });
});

test("server unavailable result remains explicitly readback-required", async () => {
  const wire = callsOf(url => json(url.endsWith("/session") ? session() :
    packet({dispatchGranted: false, readbackRequired: true}, "APPROVAL_RESULT_UNAVAILABLE")));
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  const result = await client.confirmPreview("p1");
  assert.equal(result.code, "APPROVAL_RESULT_UNAVAILABLE");
  assert.equal(result.data.readbackRequired, true);
  assert.equal(wire.calls.length, 2);
});

test("ERROR, HOLD and UNKNOWN server states are preserved, never relabeled success", async () => {
  for (const data of [
    {state: "COMPLETED", outcome: {status: "ERROR", code: "MODEL_TIMEOUT"}},
    {state: "COMPLETED", outcome: {status: "VALIDATED_HOLD"}},
    {state: "UNKNOWN", operationId: "op1", dispatchGranted: false},
  ]) {
    const wire = callsOf(url => json(url.endsWith("/session") ? session() : packet(data)));
    const client = createChronosClient({...config, ...wire});
    await client.connect();
    assert.deepEqual((await client.readDecision("d1")).data, data);
  }
});

test("logout is a single explicit POST with empty body, then locally disconnected", async () => {
  const wire = callsOf(url => json(url.endsWith("/session") ? session() : {code: "SESSION_ENDED"}));
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  await client.logout();
  assert.equal(wire.calls[1].url, origin + "/csp/chronos/logout");
  assert.equal(wire.calls[1].options.body, "{}");
  assert.equal(wire.calls[1].options.headers["X-Chronos-CSRF"], token);
  assert.equal(client.sessionStatus().connected, false);
});

test("failed logout does not claim native session ended or restore local permission", async () => {
  const wire = callsOf(url => json(url.endsWith("/session") ? session() : {code: "SESSION_END_REQUIRED"}, 200));
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  await assert.rejects(client.logout(), codeIs("LOGOUT_UNCONFIRMED", true));
  assert.equal(client.sessionStatus().connected, false);
});

test("logout while confirm is pending cancels local wait, not the remote operation", async () => {
  const held = deferred();
  const wire = callsOf(url => url.endsWith("/session") ? json(session()) :
    url.endsWith("/logout") ? json({code: "SESSION_ENDED"}) : held.promise);
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  const pending = assert.rejects(client.confirmPreview("p1"), codeIs("CONNECTION_CHANGED", true));
  await client.logout();
  held.resolve(json(packet({state: "ACCEPTED"})));
  await pending;
  assert.equal(wire.calls.length, 3);
  assert.equal(client.sessionStatus().connected, false);
});

test("session invalidation at each promise boundary cannot restore disconnected capabilities", async () => {
  for (let ticks = 0; ticks < 32; ticks += 1) {
    const client = createChronosClient({...config, fetchImpl: () => json(session())});
    const completion = client.connect().then(() => null, error => error);
    await new Promise(resolve => {
      let remaining = ticks;
      const step = () => {
        if (remaining-- === 0) { client.disconnect(); resolve(); }
        else queueMicrotask(step);
      };
      queueMicrotask(step);
    });
    await completion;
    assert.equal(client.sessionStatus().connected, false, "disconnect boundary " + ticks);
  }
});

test("early protocol rejection cancels an unread response stream", async () => {
  for (const [httpStatus, contentType] of [[200, "text/html"], [403, "application/json"],
    [302, "application/json"]]) {
    let cancelled = false;
    const response = new Response(new ReadableStream({cancel() {cancelled = true;}}),
      {status: httpStatus, headers: {"Content-Type": contentType}});
    const client = createChronosClient({...config, fetchImpl: () => response});
    await assert.rejects(client.connect(), error => error instanceof ChronosClientError);
    assert.equal(cancelled, true, "unread response " + httpStatus);
  }
});

test("an older denied read cannot revoke a newer successful connection", async () => {
  for (let ticks = 0; ticks < 32; ticks += 1) {
    const wire = callsOf(url => json(url.endsWith("/session") ? session() :
      packet({code: "PERMISSION_DENIED"}, "OK")));
    const client = createChronosClient({...config, ...wire});
    await client.connect();
    const old = client.readPreview("p1").then(() => null, error => error);
    await new Promise((resolve, reject) => {
      let remaining = ticks;
      const step = () => {
        if (remaining-- === 0) client.connect().then(resolve, reject);
        else queueMicrotask(step);
      };
      queueMicrotask(step);
    });
    await old;
    assert.equal(client.sessionStatus().connected, true, "reconnect boundary " + ticks);
  }
});

test("explicit recovery after a lost confirmation uses the same preview without another confirm", async () => {
  const wire = callsOf((url, options) => {
    if (url.endsWith("/session")) return json(session());
    const {command} = JSON.parse(options.body);
    if (command === "CONFIRM") throw new Error("simulated lost reply");
    if (command === "READ") return json(packet({previewId: "p1", state: "CONFIRMED",
      operation: {operationId: "op1", state: "UNKNOWN"}}, "READ_ONLY"));
    if (command === "RECONCILE") return json(packet({operationId: "op1", state: "ACCEPTED",
      dispatchGranted: false}, "READBACK_RECORDED"));
    throw new Error("unexpected command");
  });
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  await assert.rejects(client.confirmPreview("p1"), codeIs("TRANSPORT_UNAVAILABLE", true));
  await client.connect();
  assert.equal((await client.readPreview("p1")).data.operation.state, "UNKNOWN");
  assert.equal((await client.reconcilePreview("p1")).data.state, "ACCEPTED");
  const sent = wire.calls.filter(call => call.options.method === "POST")
    .map(call => JSON.parse(call.options.body));
  assert.deepEqual(sent, [{command: "CONFIRM", id: "p1"}, {command: "READ", id: "p1"},
    {command: "RECONCILE", id: "p1"}]);
});

test("a detail timeout never implies a write or retries the decision", async () => {
  const wire = callsOf(url => url.endsWith("/session") ? json(session({canApprove: false})) : new Promise(() => {}));
  const client = createChronosClient({...config, ...wire, timeoutMs: 20});
  await client.connect();
  await assert.rejects(client.readDecisionDetail("d1"), error => {
    assert.equal(error.code, "REQUEST_TIMEOUT");
    assert.equal(error.mayHaveApplied, false);
    assert.equal(error.readbackRequired, false);
    return true;
  });
  assert.equal(wire.calls.length, 2);
  assert.deepEqual(JSON.parse(wire.calls[1].options.body), {command: "DECISION_DETAIL", id: "d1"});
  assert.equal(client.sessionStatus().connected, false);
});

test("correlated preparation commands send only their exact public IDs", async () => {
  const wire = callsOf(url => json(url.endsWith("/session") ? session() : packet({state: "STARTED"})));
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  await client.preparePreview("decision-1", "request-1");
  assert.deepEqual(JSON.parse(wire.calls.at(-1).options.body),
    {command: "PREVIEW_REQUEST", id: "decision-1", requestId: "request-1"});
  await client.readPreparation("request-1");
  assert.deepEqual(JSON.parse(wire.calls.at(-1).options.body),
    {command: "READ_PREPARATION", id: "request-1"});
  await client.closePreparation("decision-1", "request-1");
  assert.deepEqual(JSON.parse(wire.calls.at(-1).options.body),
    {command: "CLOSE_PREPARATION", id: "decision-1", requestId: "request-1"});
  for (const call of wire.calls.slice(1)) {
    assert.equal(call.url, origin + "/csp/chronos/approval");
    assert.equal(call.options.headers["X-Chronos-CSRF"], token);
    assert.equal(call.options.credentials, "same-origin");
  }
  assert.equal(wire.calls.length, 4); // No follow-up, polling or confirmation.
});

test("missing or invalid correlation never reaches the network", async () => {
  const wire = callsOf(() => json(session()));
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  for (const bad of [undefined, null, "", "../x", "x y", "x".repeat(129), true, 1, [], {}]) {
    for (const method of ["preparePreview", "closePreparation"]) {
      await assert.rejects(client[method]("decision-1", bad), codeIs("INVALID_REQUEST", false));
      await assert.rejects(client[method](bad, "request-1"), codeIs("INVALID_REQUEST", false));
    }
    await assert.rejects(client.readPreparation(bad), codeIs("INVALID_REQUEST", false));
  }
  assert.equal(wire.calls.length, 1);
});

test("reader can inspect an existing preparation but cannot create or close it", async () => {
  const wire = callsOf(url => json(url.endsWith("/session") ? session({canApprove: false}) : packet()));
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  await assert.rejects(client.preparePreview("d1", "r1"), codeIs("PERMISSION_DENIED", false));
  await assert.rejects(client.closePreparation("d1", "r1"), codeIs("PERMISSION_DENIED", false));
  await client.readPreparation("r1");
  assert.equal(wire.calls.length, 2);
});

test("lost preparation and close responses remain uncertain without retries", async () => {
  for (const method of ["preparePreview", "closePreparation", "readPreparation"]) {
    const wire = callsOf(url => {
      if (url.endsWith("/session")) return json(session());
      throw new Error("private exception text must not escape");
    });
    const client = createChronosClient({...config, ...wire});
    await client.connect();
    await assert.rejects(client[method]("r1", "r2"), codeIs("TRANSPORT_UNAVAILABLE", method !== "readPreparation"));
    assert.equal(wire.calls.length, 2);
    assert.equal(client.sessionStatus().connected, false);
  }
});

test("disconnect invalidates late correlated response and never creates replacement", async () => {
  const pending = deferred();
  const wire = callsOf(url => url.endsWith("/session") ? json(session()) : pending.promise);
  const client = createChronosClient({...config, ...wire});
  await client.connect();
  const sent = client.preparePreview("d1", "r1");
  const checked = assert.rejects(sent, codeIs("CONNECTION_CHANGED", true));
  client.disconnect();
  pending.resolve(json(packet({state: "RECORDED", previewId: "prep-original"})));
  await checked;
  assert.equal(wire.calls.length, 2);
  assert.equal(client.sessionStatus().connected, false);
});


test("operation reads/query accept Reader only, exact ID/route, and no implicit second call", async()=>{
  const wire=callsOf(url=>json(url.endsWith("/session")?session({canApprove:false}):packet()));
  const c=createChronosClient({...config,...wire});await c.connect();
  for(const [method,command,route] of [["readDecisionOperation","DECISION_OPERATION","decision"],["readOperation","READ_OPERATION","approval"],["reconcileOperation","RECONCILE_OPERATION","approval"]]){
    await c[method]("op114");
    assert.deepEqual(JSON.parse(wire.calls.at(-1).options.body),{command,id:"op114"});
    assert.equal(wire.calls.at(-1).url,origin+"/csp/chronos/"+route);
  }
  assert.equal(wire.calls.length,4);
});
test("lost exact-operation query is uncertain evidence, never auto-retried", async()=>{
  const wire=callsOf(url=>url.endsWith("/session")?json(session({canApprove:false})):Promise.reject(new Error("private114")));
  const c=createChronosClient({...config,...wire});await c.connect();
  await assert.rejects(c.reconcileOperation("op114"),e=>e instanceof ChronosClientError&&e.mayHaveApplied&&e.readbackRequired&&e.id==="op114");
  assert.equal(wire.calls.length,2);
});

