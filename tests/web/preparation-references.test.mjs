import test from "node:test";
import assert from "node:assert/strict";
import {createChronosClient} from "../../src/chronos_web/client.mjs";
import {createPreparationReferences} from "../../src/chronos_web/preparation-references.mjs";

const app = "https://chronos.example/csp/chronos/";
const identity = (actor = "a", scope = "b", applicationUrl = app) =>
  Object.freeze({available: true, actor: "principal-" + actor.repeat(64),
    actorScope: scope.repeat(64), applicationUrl});
const ref = (requestId = "r1", decisionId = "d1") => ({requestId, decisionId});
const canonical = items => JSON.stringify({version: 1, items});
function fixture() {
  const data = new Map(), calls = [];
  let who = identity(), access = {connected: true, canRead: true};
  const client = {sessionStatus: () => access, sessionIdentity: () => who};
  const storage = {
    getItem(key) { calls.push(["get", key]); return data.get(key) ?? null; },
    setItem(key, value) { calls.push(["set", key, value]); data.set(key, value); },
  };
  const store = createPreparationReferences({client, storage});
  return {data, calls, client, storage, store, setIdentity: value => { who = value; },
    setAccess: value => { access = value; }, key: "chronos.preparations.v1:" + app.slice(0, -1) + ":" + "b".repeat(64)};
}

test("construction and scope are inert; round trip preserves only two public IDs", () => {
  const f = fixture();
  assert.equal(f.calls.length, 0);
  assert.equal(f.store.scope(), JSON.stringify([app, "b".repeat(64), "principal-" + "a".repeat(64)]));
  assert.equal(f.calls.length, 0);
  assert.equal(f.store.remember(ref()).code, "REFERENCE_REMEMBERED");
  assert.equal(f.data.get(f.key), canonical([ref()]));
  assert.equal(f.data.size, 1);
  const reloaded = createPreparationReferences({client: f.client, storage: f.storage});
  f.setIdentity(identity()); // Same native scope, new connection object.
  const read = reloaded.list();
  assert.deepEqual(read.items, [ref()]);
  assert.ok(Object.isFrozen(read) && Object.isFrozen(read.items) && Object.isFrozen(read.items[0]));
  assert.throws(() => { read.items[0].decisionId = "different"; }, TypeError);
  assert.equal(reloaded.remember(ref()).code, "ALREADY_REMEMBERED");
  assert.equal(f.calls.filter(c => c[0] === "set").length, 1);
  assert.equal(reloaded.forget(ref()).code, "REFERENCE_FORGOTTEN");
  assert.equal(f.data.get(f.key), canonical([]));
  assert.equal(reloaded.forget(ref()).code, "REFERENCE_NOT_STORED");
});

test("actor, installation and application scopes isolate bookmarks without touching legacy keys", () => {
  const f = fixture();
  f.data.set("chronos.references.v1:legacy", "preserved");
  f.store.remember(ref());
  for (const next of [identity("c", "d"), identity("a", "e"), identity("a", "b", "https://chronos.example/csp/other/")]) {
    f.setIdentity(next);
    assert.deepEqual(f.store.list().items, []);
  }
  f.setIdentity(identity());
  assert.deepEqual(f.store.list().items, [ref()]);
  assert.equal(f.data.get("chronos.references.v1:legacy"), "preserved");
});

test("missing or revoked native metadata prevents all storage access", () => {
  const f = fixture();
  for (const who of [{available: false}, {...identity(), actorScope: "bad"},
    {...identity(), applicationUrl: "https://user:pass@chronos.example/csp/a"},
    {...identity(), applicationUrl: "http://foreign.example/csp/a"}, {...identity(), applicationUrl: app + "?token=x"}]) {
    f.setIdentity(who);
    assert.equal(f.store.scope(), "");
    for (const result of [f.store.list(), f.store.remember(ref()), f.store.forget(ref())]) {
      assert.equal(result.code, "RECOVERY_IDENTITY_UNAVAILABLE");
      assert.deepEqual(result.items, []);
    }
  }
  f.setIdentity(identity());
  for (const access of [{connected: false, canRead: true}, {connected: true, canRead: false}, {connected: true, canRead: 1}]) {
    f.setAccess(access);
    assert.equal(f.store.list().code, "RECOVERY_IDENTITY_UNAVAILABLE");
  }
  assert.equal(f.calls.length, 0);
});

test("exact reference shape and ASCII IDs reject authority data before storage", () => {
  const f = fixture();
  for (const value of [undefined, null, [], {}, {requestId: "r"}, {...ref(), actor: "x"},
    {...ref(), dispatchGranted: true}, {...ref(), [Symbol("hidden")]: "x"},
    ...["", "x".repeat(129), "é", "../r", "space r", true, 7].flatMap(v => [ref(v), ref("r", v)])]) {
    assert.equal(f.store.remember(value).code, "INVALID_REFERENCE");
    assert.equal(f.store.forget(value).code, "INVALID_REFERENCE");
  }
  assert.equal(f.calls.length, 0);
  assert.equal(f.store.remember(ref("A-_.09", "Z-_.09")).ok, true);
});

test("one request ID cannot be rebound or forgotten using a different decision", () => {
  const f = fixture(); f.store.remember(ref()); const original = f.data.get(f.key);
  for (const method of ["remember", "forget"]) {
    assert.equal(f.store[method](ref("r1", "d2")).code, "PREPARATION_ID_CONFLICT");
    assert.equal(f.data.get(f.key), original);
  }
  assert.equal(f.store.remember(ref("r2", "d1")).ok, true);
  assert.deepEqual(f.store.list().items, [ref(), ref("r2", "d1")]);
});

test("corrupt, duplicate, oversized and noncanonical stores are never repaired or overwritten", () => {
  const f = fixture();
  const invalid = ["", "{", "x".repeat(8193), canonical([ref(), ref()]),
    canonical([ref(), ref("r1", "different")]), '{"version":1,"version":1,"items":[]}',
    '{"version":1,"items":[{"requestId":"r","requestId":"r","decisionId":"d"}]}',
    '{"version":1, "items":[]}', '{"items":[],"version":1}',
    JSON.stringify({version: 2, items: []}), JSON.stringify({version: 1, items: [], grant: true}),
    canonical([{...ref(), outcome: "ACCEPTED"}]), canonical(Array.from({length: 33}, (_, i) => ref("r" + i)))];
  for (const raw of invalid) {
    f.data.set(f.key, raw);
    for (const result of [f.store.list(), f.store.remember(ref()), f.store.forget(ref())]) {
      assert.equal(result.code, "REFERENCE_STORE_INVALID");
    }
    assert.equal(f.data.get(f.key), raw);
  }
  assert.equal(f.calls.filter(c => c[0] === "set").length, 0);
});

test("32-entry cap does not evict and idempotent repeat remains allowed when full", () => {
  const f = fixture();
  const refs = Array.from({length: 32}, (_, i) => ref("r" + i, "d" + i));
  for (const value of refs) assert.equal(f.store.remember(value).ok, true);
  const original = f.data.get(f.key);
  assert.equal(f.store.remember(ref("overflow")).code, "REFERENCE_STORE_FULL");
  assert.equal(f.store.remember(refs[0]).code, "ALREADY_REMEMBERED");
  assert.equal(f.data.get(f.key), original);
});

test("8192 character cap also applies before writing otherwise valid long IDs", () => {
  const f = fixture(); let full = false;
  for (let i = 0; i < 32; i++) {
    const before = f.data.get(f.key);
    const result = f.store.remember(ref(String(i).padEnd(128, "r"), "d".repeat(128)));
    if (!result.ok) {
      assert.equal(result.code, "REFERENCE_STORE_FULL");
      assert.equal(f.data.get(f.key), before); full = true; break;
    }
    assert.ok(f.data.get(f.key).length <= 8192);
  }
  assert.equal(full, true);
  assert.equal(f.store.list().ok, true);
});

test("scope or identity-object changes during each I/O fail closed", () => {
  for (const method of ["remember", "forget"]) for (let at = 1; at <= 4; at++) {
    const f = fixture(); f.data.set(f.key, canonical([ref()]));
    let calls = 0;
    for (const operation of ["getItem", "setItem"]) {
      const original = f.storage[operation];
      f.storage[operation] = (...args) => {
        const value = original(...args);
        if (++calls === at) f.setIdentity(identity("c", "d"));
        return value;
      };
    }
    const result = f.store[method](method === "remember" ? ref("r2", "d2") : ref());
    assert.equal(result.code, "REFERENCE_SCOPE_CHANGED", method + ":" + at);
    assert.deepEqual(result.items, []); assert.equal(result.scope, "");
    assert.equal(calls, at);
    assert.equal([...f.data.keys()].length, 1); // Never writes into the new account's store.
  }
  const f = fixture(); f.data.set(f.key, canonical([ref()]));
  const read = f.storage.getItem;
  f.storage.getItem = key => { const v = read(key); f.setIdentity(identity()); return v; };
  assert.equal(f.store.list().code, "REFERENCE_SCOPE_CHANGED"); // Same fields, new object.
});

test("mutating metadata fields or revoking READ during I/O is detected", () => {
  for (const revoke of [false, true]) {
    const f = fixture(), who = {...identity()}; f.setIdentity(who);
    f.storage.getItem = () => {
      if (revoke) f.setAccess({connected: true, canRead: false}); else who.actorScope = "f".repeat(64);
      return canonical([ref()]);
    };
    assert.equal(f.store.list().code, "REFERENCE_SCOPE_CHANGED");
  }
});

test("concurrent stored change is preserved without overwriting", () => {
  const f = fixture(); let reads = 0; const other = canonical([ref("other", "decision")]);
  f.storage.getItem = key => { if (++reads === 2) f.data.set(key, other); return f.data.get(key) ?? null; };
  assert.equal(f.store.remember(ref()).code, "REFERENCE_STORE_CHANGED");
  assert.equal(f.data.get(f.key), other);
  assert.equal(f.calls.filter(c => c[0] === "set").length, 0);
});

test("readback mismatch and throwing writes remain explicitly unconfirmed", () => {
  for (const fail of ["drop", "throw-before", "throw-after", "readback"]) {
    const f = fixture(); let reads = 0;
    f.storage.getItem = key => { if (++reads === 3 && fail === "readback") throw new Error("private"); return f.data.get(key) ?? null; };
    f.storage.setItem = (key, value) => {
      if (fail === "throw-before") throw new Error("private");
      if (fail !== "drop") f.data.set(key, value);
      if (fail === "throw-after") throw new Error("private");
    };
    const result = f.store.remember(ref());
    assert.equal(result.code, "REFERENCE_WRITE_UNCONFIRMED");
    assert.equal(result.ok, false); assert.deepEqual(result.items, []);
    assert.equal(JSON.stringify(result).includes("private"), false);
  }
});

test("unavailable storage and reading errors do not report success or disclose exceptions", () => {
  const f = fixture();
  assert.equal(createPreparationReferences({client: f.client, storage: null}).list().code, "STORAGE_UNAVAILABLE");
  f.storage.getItem = () => { throw new Error("private-password"); };
  const r = f.store.list(); assert.equal(r.code, "STORAGE_UNAVAILABLE");
  assert.equal(JSON.stringify(r).includes("private-password"), false);
});

test("reentrant storage hook cannot start a second write on the same facade", () => {
  const f = fixture(); let nested;
  const get = f.storage.getItem;
  f.storage.getItem = key => { nested = f.store.remember(ref("nested")); return get(key); };
  assert.equal(f.store.remember(ref()).ok, true);
  assert.equal(nested.code, "REFERENCE_STORE_BUSY");
  assert.deepEqual(f.store.list().items, [ref()]);
});

test("actual client validated session identity activates storage without exposing wire version", async () => {
  const calls = [], data = new Map();
  const client = createChronosClient({pageUrl: "https://chronos.example/ui/", basePath: "/csp/chronos/",
    fetchImpl: async (url, options) => {
      calls.push([url, options]);
      return new Response(JSON.stringify({code: "CONNECTED", authenticated: true, canRead: true,
        canApprove: false, csrf: "f".repeat(64), identity: {version: 1, ...identity()}}),
        {status: 200, headers: {"Content-Type": "application/json"}});
    }});
  const store = createPreparationReferences({client, storage: {
    getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value),
  }});
  assert.equal(store.remember(ref()).code, "RECOVERY_IDENTITY_UNAVAILABLE");
  assert.equal(calls.length, 0);
  await client.connect();
  assert.equal(Object.hasOwn(client.sessionIdentity(), "version"), false);
  assert.equal(store.remember(ref()).ok, true);
  assert.deepEqual(store.list().items, [ref()]);
  client.disconnect();
  assert.equal(store.list().code, "RECOVERY_IDENTITY_UNAVAILABLE");
  assert.equal(data.size, 1);
  assert.equal(calls.length, 1); // Facade never connects, sends, or refreshes permissions.
});