/**
 * Per-tab recovery bookmarks. Only kind and non-secret server-issued IDs belong here.
 * actorScope must be a non-secret, stable, server-issued installation+actor
 * discriminator. The source /session contract supplies it only with a valid
 * installer marker. Live installation remains unverified; UI wiring is pending.
 * Never invent it from a username, cookie or a proposal's actor field.
 */
const ID = /^[A-Za-z0-9_.-]{1,128}$/;
const LIMIT = 32, MAX_LENGTH = 8192;
const ownKeys = (value, keys) => value !== null && typeof value === "object" &&
  !Array.isArray(value) && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
const valid = value => ownKeys(value, ["kind", "id"]) &&
  ["decision", "preview", "operation"].includes(value.kind) && typeof value.id === "string" && ID.test(value.id);
const copy = item => Object.freeze({kind: item.kind, id: item.id});
const result = (ok, code, items = []) => Object.freeze({
  ok, code, items: Object.freeze(items.map(copy)),
});
const equal = (a, b) => a.kind === b.kind && a.id === b.id;

export function createRecoveryReferences({storage, applicationUrl, actorScope} = {}) {
  let app;
  try { app = new URL(applicationUrl); } catch { throw new TypeError("INVALID_REFERENCE_SCOPE"); }
  if (!storage || typeof storage.getItem !== "function" || typeof storage.setItem !== "function" ||
      typeof actorScope !== "string" || !/^[0-9a-f]{64}$/.test(actorScope) ||
      app.username || app.password || app.search || app.hash ||
      !/^\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+\/?$/.test(app.pathname) ||
      !(app.protocol === "https:" || (app.protocol === "http:" &&
        ["127.0.0.1", "[::1]", "localhost"].includes(app.hostname)))) {
    throw new TypeError("INVALID_REFERENCE_SCOPE");
  }
  const key = "chronos.references.v1:" + app.origin + app.pathname.replace(/\/$/, "") + ":" + actorScope;
  function read() {
    let raw;
    try { raw = storage.getItem(key); } catch { return {result: result(false, "STORAGE_UNAVAILABLE")}; }
    if (raw === null) return {raw, result: result(true, "REFERENCES_READ")};
    if (typeof raw !== "string" || raw.length > MAX_LENGTH) return {raw, result: result(false, "REFERENCE_STORE_INVALID")};
    try {
      const parsed = JSON.parse(raw);
      if (!ownKeys(parsed, ["version", "items"]) || parsed.version !== 1 ||
          !Array.isArray(parsed.items) || parsed.items.length > LIMIT ||
          !parsed.items.every(valid)) throw new Error("invalid");
      const seen = new Set(parsed.items.map(item => item.kind + ":" + item.id));
      if (seen.size !== parsed.items.length) throw new Error("duplicate");
      // Reject duplicate JSON keys, changed schema or noncanonical foreign data.
      // Never silently repair/overwrite a corrupt store that may hold recovery IDs.
      const canonical = JSON.stringify({version: 1, items: parsed.items.map(item => ({kind: item.kind, id: item.id}))});
      if (canonical !== raw) throw new Error("noncanonical");
      return {raw, result: result(true, "REFERENCES_READ", parsed.items)};
    } catch { return {raw, result: result(false, "REFERENCE_STORE_INVALID")}; }
  }

  function change(reference, forget) {
    if (!valid(reference)) return result(false, "INVALID_REFERENCE");
    const prior = read();
    if (!prior.result.ok) return prior.result;
    const items = prior.result.items;
    const exists = items.some(item => equal(item, reference));
    if (!forget && exists) return result(true, "ALREADY_REMEMBERED", items);
    if (forget && !exists) return result(true, "REFERENCE_NOT_STORED", items);
    if (!forget && items.length >= LIMIT) return result(false, "REFERENCE_STORE_FULL", items);
    const next = forget ? items.filter(item => !equal(item, reference)) : [...items, copy(reference)];
    const encoded = JSON.stringify({version: 1, items: next});
    try {
      // Best-effort conflict detection, NOT a cross-context compare-and-swap.
      if (storage.getItem(key) !== prior.raw) return result(false, "REFERENCE_STORE_CHANGED");
      storage.setItem(key, encoded);
      if (storage.getItem(key) !== encoded) return result(false, "REFERENCE_WRITE_UNCONFIRMED");
    } catch { return result(false, "REFERENCE_WRITE_UNCONFIRMED"); }
    return result(true, forget ? "REFERENCE_FORGOTTEN" : "REFERENCE_REMEMBERED", next);
  }

  return Object.freeze({
    list: () => read().result,
    remember: reference => change(reference, false),
    // Explicit user action only; never clear all storage or auto-evict on overflow.
    forget: reference => change(reference, true),
  });
}
