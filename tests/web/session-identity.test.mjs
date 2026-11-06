import test from "node:test";
import assert from "node:assert/strict";
import {createChronosClient} from "../../src/chronos_web/client.mjs";
import {createRecoveryReferences} from "../../src/chronos_web/references.mjs";

const base = "https://chronos.example/csp/chronos/";
const options = {pageUrl: base + "ui", basePath: "/csp/chronos", timeoutMs: 300};
const actor = "principal-" + "a".repeat(64), scope = "b".repeat(64);
const identity = extra => ({version: 1, available: true, actor, actorScope: scope, applicationUrl: base, ...extra});
const reply = extra => ({authenticated: true, code: "CONNECTED", canRead: true,
  canApprove: true, csrf: "c".repeat(64), identity: identity(), ...extra});
const json = data => new Response(JSON.stringify(data), {headers: {"Content-Type": "application/json"}});
const empty = {available: false, actor: "", actorScope: "", applicationUrl: ""};
const deferred = () => {let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};};
const invalid = e => e.code === "INVALID_SESSION";

test("public identity exposes only the native actor/scope/exact app and no session material", async () => {
  const api = createChronosClient({...options, fetchImpl: async () => json(reply({username: "not-public", sessionBinding: "not-public"}))});
  assert.deepEqual(api.sessionIdentity(), empty);
  await api.connect();
  assert.deepEqual(api.sessionIdentity(), {available: true, actor, actorScope: scope, applicationUrl: base});
  assert.ok(Object.isFrozen(api.sessionIdentity()));
  assert.deepEqual(api.sessionStatus(), {connected: true, canRead: true, canApprove: true});
  assert.equal(JSON.stringify(api.sessionIdentity()).includes("c".repeat(64)), false);
  assert.equal(JSON.stringify(api.sessionIdentity()).includes("not-public"), false);
});

test("legacy or explicitly unavailable identities do not invent an actor while reads remain usable", async () => {
  for (const value of [(() => {const v = reply(); delete v.identity; return v;})(),
    reply({identity: {version: 1, available: false}})]) {
    let calls = 0;
    const api = createChronosClient({...options, fetchImpl: async url => {
      calls++; return json(url.endsWith("session") ? value : {code: "READ_ONLY", data: {}, traceSessionId: 1});
    }});
    await api.connect();
    assert.deepEqual(api.sessionIdentity(), empty);
    await api.readDecision("known");
    assert.equal(calls, 2);
  }
});

test("malformed or extra identity metadata invalidates the whole bootstrap", async () => {
  for (const bad of [null, [], "actor", {}, identity({version: 2}),
    identity({available: 1}), identity({actor: "preview-actor"}),
    identity({actor: actor.toUpperCase()}), identity({actorScope: scope.slice(1)}),
    identity({actorScope: null}), identity({csrf: "unexpected"}),
    identity({available: false}), {version: 1, available: false, actor},
    {version: 1, available: false, actorScope: scope}]) {
    const api = createChronosClient({...options, fetchImpl: async () => json(reply({identity: bad}))});
    await assert.rejects(api.connect(), invalid);
    assert.deepEqual(api.sessionIdentity(), empty);
    assert.equal(api.sessionStatus().connected, false);
  }
});

test("application identity is exact, not merely same-origin or URL-equivalent", async () => {
  for (const applicationUrl of [base.slice(0, -1), base + "?a=b", base + "#x",
    "https://chronos.example/csp/other/", "https://elsewhere.example/csp/chronos/",
    "https://chronos.example:443/csp/chronos/", "https://chronos.example/csp/%63hronos/",
    "https://name:password@chronos.example/csp/chronos/", base + "../chronos/"]) {
    const api = createChronosClient({...options, fetchImpl: async () => json(reply({identity: identity({applicationUrl})}))});
    await assert.rejects(api.connect(), invalid);
  }
});

test("read-only identities remain available; revoked readers have no identity and can log out", async () => {
  const api = createChronosClient({...options, fetchImpl: async () => json(reply({canApprove: false}))});
  await api.connect();
  assert.equal(api.sessionIdentity().available, true);
  await assert.rejects(api.confirmPreview("p"), e => e.code === "PERMISSION_DENIED");
  assert.equal(api.sessionIdentity().available, true);
  for (const metadata of [undefined, {version: 1, available: false}]) {
    const revoked = reply({code: "ACCESS_REVOKED", canRead: false, canApprove: false});
    if (metadata) revoked.identity = metadata; else delete revoked.identity;
    const client = createChronosClient({...options, fetchImpl: async url => json(
      url.endsWith("session") ? revoked : {code: "SESSION_ENDED"})});
    await client.connect();
    assert.deepEqual(client.sessionIdentity(), empty);
    await client.logout();
    assert.deepEqual(client.sessionIdentity(), empty);
  }
  const client = createChronosClient({...options, fetchImpl: async () => json(
    reply({code: "ACCESS_REVOKED", canRead: false, canApprove: false}))});
  await assert.rejects(client.connect(), invalid);
});

test("reconnect clears identity synchronously and replaces it only from the new response", async () => {
  const pending = deferred(); let calls = 0;
  const api = createChronosClient({...options, fetchImpl: () => ++calls === 1 ? json(reply()) : pending.promise});
  await api.connect();
  const again = api.connect();
  assert.deepEqual(api.sessionIdentity(), empty);
  const nextActor = "principal-" + "d".repeat(64), nextScope = "e".repeat(64);
  pending.resolve(json(reply({identity: identity({actor: nextActor, actorScope: nextScope})})));
  await again;
  assert.equal(api.sessionIdentity().actor, nextActor);
  assert.equal(api.sessionIdentity().actorScope, nextScope);
  api.disconnect();
  assert.deepEqual(api.sessionIdentity(), empty);
});

test("late previous login replies cannot restore old identity after a new connection", async () => {
  const pending = deferred(); let calls = 0;
  const api = createChronosClient({...options, fetchImpl: () => ++calls === 1 ? pending.promise :
    json(reply({identity: identity({actorScope: "d".repeat(64)})}))});
  const old = assert.rejects(api.connect(), e => e.code === "CONNECTION_CHANGED");
  await api.connect();
  pending.resolve(json(reply()));
  await old;
  await Promise.resolve();
  assert.equal(api.sessionIdentity().actorScope, "d".repeat(64));
});

test("errors after an authenticated command clear identity and never retry", async () => {
  for (const response of [() => {throw new Error("private failure");},
    () => json({code: "PERMISSION_DENIED"}), () => new Response("<html>login</html>")]) {
    let calls = 0;
    const api = createChronosClient({...options, fetchImpl: () => ++calls === 1 ? json(reply()) : response()});
    await api.connect();
    await assert.rejects(api.readDecision("d"));
    assert.deepEqual(api.sessionIdentity(), empty);
    assert.equal(calls, 2);
  }
});

test("timeout after confirmation clears identity but preserves the original uncertain reference", async () => {
  const api = createChronosClient({...options, timeoutMs: 10, fetchImpl: url =>
    url.endsWith("session") ? json(reply()) : new Promise(() => {})});
  await api.connect();
  await assert.rejects(api.confirmPreview("original-preview"), e =>
    e.code === "REQUEST_TIMEOUT" && e.id === "original-preview" && e.mayHaveApplied);
  assert.deepEqual(api.sessionIdentity(), empty);
});

test("logout clears identity before the network responds, including unconfirmed logout", async () => {
  const pending = deferred();
  const api = createChronosClient({...options, fetchImpl: url => url.endsWith("session") ? json(reply()) : pending.promise});
  await api.connect();
  const done = api.logout();
  assert.deepEqual(api.sessionIdentity(), empty);
  pending.resolve(json({code: "NOT_ENDED"}));
  await assert.rejects(done, e => e.code === "LOGOUT_UNCONFIRMED");
  assert.deepEqual(api.sessionIdentity(), empty);
});

test("mock server scope binds IDs to actor/installation and permits same-scope reload recovery", async () => {
  const data = new Map(), storage = {getItem: k => data.get(k) ?? null, setItem: (k,v) => data.set(k,v)};
  async function references(metadata) {
    const api = createChronosClient({...options, fetchImpl: () => json(reply({identity: metadata}))});
    await api.connect();
    const value = api.sessionIdentity();
    assert.equal(value.available, true);
    return createRecoveryReferences({storage, applicationUrl: value.applicationUrl, actorScope: value.actorScope});
  }
  const first = await references(identity());
  assert.equal(first.remember({kind: "preview", id: "original-preview"}).ok, true);
  const same = await references(identity());
  assert.deepEqual(same.list().items, [{kind: "preview", id: "original-preview"}]);
  for (const metadata of [
    identity({actor: "principal-" + "d".repeat(64), actorScope: "d".repeat(64)}),
    identity({actorScope: "e".repeat(64)}),
  ]) assert.deepEqual((await references(metadata)).list().items, []);
  const serialized = [...data.values()].join("");
  assert.equal(serialized.includes("original-preview"), true);
  for (const forbidden of [actor, scope, "c".repeat(64), "payload", "csrf"]) {
    assert.equal(serialized.includes(forbidden), false);
  }
});
