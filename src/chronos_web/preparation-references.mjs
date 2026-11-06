/** Public preparation bookmarks only; never permission, outcomes or credentials.
 * Session storage is not a cross-context atomic database. Conflict checks are
 * best effort, and failed write confirmation never proves that nothing changed.
 */
const ID = /^[A-Za-z0-9_.-]{1,128}$/;
const LIMIT = 32, MAX_LENGTH = 8192;
const keys = (v, names) => v !== null && typeof v === "object" && !Array.isArray(v) &&
  Reflect.ownKeys(v).length === names.length && names.every(name => Object.hasOwn(v, name));
const pair = v => keys(v, ["requestId", "decisionId"]) &&
  typeof v.requestId === "string" && ID.test(v.requestId) &&
  typeof v.decisionId === "string" && ID.test(v.decisionId);
const copy = v => Object.freeze({requestId: v.requestId, decisionId: v.decisionId});
const answer = (ok, code, items = [], scope = "") => Object.freeze({
  ok, code, items: Object.freeze(items.map(copy)), scope,
});
const encode = items => JSON.stringify({version: 1,
  items: items.map(v => ({requestId: v.requestId, decisionId: v.decisionId}))});

export function createPreparationReferences({client, storage} = {}) {
  if (typeof client?.sessionStatus !== "function" || typeof client?.sessionIdentity !== "function") {
    throw new TypeError("INVALID_RECOVERY_CLIENT");
  }
  let busy = false;
  function capture() {
    try {
      const access = client.sessionStatus(), identity = client.sessionIdentity();
      if (access.connected !== true || access.canRead !== true || identity.available !== true ||
          typeof identity.actor !== "string" ||
          !/^principal-[0-9a-f]{64}$/.test(identity.actor) ||
          typeof identity.actorScope !== "string" || !/^[0-9a-f]{64}$/.test(identity.actorScope) ||
          typeof identity.applicationUrl !== "string") return null;
      const {applicationUrl, actorScope, actor} = identity;
      const app = new URL(applicationUrl);
      if (app.username || app.password || app.search || app.hash ||
          !/^\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+\/?$/.test(app.pathname) ||
          !(app.protocol === "https:" || app.protocol === "http:" &&
            ["127.0.0.1", "[::1]", "localhost"].includes(app.hostname))) return null;
      return {identity, scope: JSON.stringify([applicationUrl, actorScope, actor]),
        key: "chronos.preparations.v1:" + app.origin + app.pathname.replace(/\/$/, "") + ":" + actorScope};
    } catch { return null; }
  }
  function run(method, reference) {
    const binding = capture();
    if (!binding) return answer(false, "RECOVERY_IDENTITY_UNAVAILABLE");
    if (busy) return answer(false, "REFERENCE_STORE_BUSY");
    const current = () => {
      const now = capture();
      return now?.identity === binding.identity && now.scope === binding.scope;
    };
    const scopeChanged = {};
    const check = () => { if (!current()) throw scopeChanged; };
    const io = (method, ...args) => {
      check();
      try { return storage[method](...args); } finally { check(); }
    };
    let writing = false;
    busy = true;
    try {
      if (!storage || typeof storage.getItem !== "function" || typeof storage.setItem !== "function") {
        return answer(false, "STORAGE_UNAVAILABLE");
      }
      let selected;
      if (method !== "list") {
        if (!pair(reference)) return answer(false, "INVALID_REFERENCE");
        selected = copy(reference);
        if (!pair(selected)) return answer(false, "INVALID_REFERENCE");
      }
      const raw = io("getItem", binding.key);
      let items = [];
      if (raw !== null) {
        try {
          if (typeof raw !== "string" || raw.length > MAX_LENGTH) throw new Error();
          const parsed = JSON.parse(raw);
          if (!keys(parsed, ["version", "items"]) || parsed.version !== 1 ||
              !Array.isArray(parsed.items) || parsed.items.length > LIMIT ||
              !parsed.items.every(pair) || new Set(parsed.items.map(v => v.requestId)).size !== parsed.items.length ||
              encode(parsed.items) !== raw) throw new Error();
          items = parsed.items;
        } catch { return answer(false, "REFERENCE_STORE_INVALID"); }
      }
      check();
      const result = (ok, code, values = items) => {
        check();
        return answer(ok, code, values, binding.scope);
      };
      if (method === "list") return result(true, "REFERENCES_READ");
      const existing = items.find(v => v.requestId === selected.requestId);
      if (existing && existing.decisionId !== selected.decisionId) return result(false, "PREPARATION_ID_CONFLICT");
      if (method === "remember" && existing) return result(true, "ALREADY_REMEMBERED");
      if (method === "forget" && !existing) return result(true, "REFERENCE_NOT_STORED");
      if (method === "remember" && items.length >= LIMIT) return result(false, "REFERENCE_STORE_FULL");
      const next = method === "forget" ? items.filter(v => v.requestId !== selected.requestId) : [...items, selected];
      const encoded = encode(next);
      if (encoded.length > MAX_LENGTH) return result(false, "REFERENCE_STORE_FULL");
      if (io("getItem", binding.key) !== raw) return result(false, "REFERENCE_STORE_CHANGED");
      writing = true;
      io("setItem", binding.key, encoded);
      if (io("getItem", binding.key) !== encoded) return result(false, "REFERENCE_WRITE_UNCONFIRMED", []);
      return result(true, method === "forget" ? "REFERENCE_FORGOTTEN" : "REFERENCE_REMEMBERED", next);
    } catch (error) {
      if (error === scopeChanged || !current()) return answer(false, "REFERENCE_SCOPE_CHANGED");
      return answer(false, writing ? "REFERENCE_WRITE_UNCONFIRMED" : "STORAGE_UNAVAILABLE");
    } finally { busy = false; }
  }
  return Object.freeze({
    scope: () => capture()?.scope ?? "",
    list: () => run("list"),
    remember: reference => run("remember", reference),
    forget: reference => run("forget", reference),
  });
}
