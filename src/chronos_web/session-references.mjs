import {createRecoveryReferences} from "./references.mjs";

const empty = code => Object.freeze({ok: false, code, items: Object.freeze([]), scope: ""});

/**
 * Binds every local operation to the client's current authenticated metadata.
 * This stores only bookmarks, not identity, credentials, outcomes or permission.
 * The caller must still reconnect before reopening/removing a displayed item.
 */
export function createSessionRecoveryReferences({client, storage} = {}) {
  if (typeof client?.sessionIdentity !== "function" || typeof client?.sessionStatus !== "function") {
    throw new TypeError("INVALID_RECOVERY_CLIENT");
  }
  function capture() {
    try {
      const access = client.sessionStatus(), identity = client.sessionIdentity();
      if (access.connected !== true || access.canRead !== true || identity.available !== true ||
          typeof identity.actor !== "string" || !/^principal-[0-9a-f]{64}$/.test(identity.actor) ||
          typeof identity.actorScope !== "string" || !/^[0-9a-f]{64}$/.test(identity.actorScope) ||
          typeof identity.applicationUrl !== "string") return null;
      return {identity, scope: JSON.stringify([identity.applicationUrl, identity.actorScope, identity.actor])};
    } catch { return null; }
  }
  function run(method, value) {
    const binding = capture();
    if (!binding) return empty("RECOVERY_IDENTITY_UNAVAILABLE");
    const current = () => {
      const now = capture();
      return now?.identity === binding.identity && now.scope === binding.scope;
    };
    try {
      if (!storage || typeof storage.getItem !== "function" || typeof storage.setItem !== "function") {
        return empty("STORAGE_UNAVAILABLE");
      }
      const guarded = {
        getItem(key) {
          if (!current()) throw new Error("REFERENCE_SCOPE_CHANGED");
          const value = storage.getItem(key);
          if (!current()) throw new Error("REFERENCE_SCOPE_CHANGED");
          return value;
        },
        setItem(key, value) {
          if (!current()) throw new Error("REFERENCE_SCOPE_CHANGED");
          storage.setItem(key, value);
          if (!current()) throw new Error("REFERENCE_SCOPE_CHANGED");
        },
      };
      const store = createRecoveryReferences({storage: guarded,
        applicationUrl: binding.identity.applicationUrl, actorScope: binding.identity.actorScope});
      const result = store[method](value);
      if (!current()) return empty("REFERENCE_SCOPE_CHANGED");
      return Object.freeze({...result, scope: binding.scope});
    } catch {
      return empty(current() ? "STORAGE_UNAVAILABLE" : "REFERENCE_SCOPE_CHANGED");
    }
  }
  return Object.freeze({
    scope: () => capture()?.scope ?? "",
    list: () => run("list"),
    remember: reference => run("remember", reference),
    forget: reference => run("forget", reference),
  });
}
