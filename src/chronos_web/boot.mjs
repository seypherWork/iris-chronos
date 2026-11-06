import {createChronosClient} from "./client.mjs";
import {mountResultScreen} from "./screen.mjs";

// Installation-owned same-origin route. Empty until native deployment verifies it.
// No query-string override, stored credentials, automatic read or demo data.
let screen = null, client = null;
function stop() {
  screen?.destroy();
  screen = null;
  client?.disconnect();
  client = null;
}
function start() {
  stop();
  const root = document.getElementById("chronos-app");
  if (!root) return;
  const basePath = document.querySelector('meta[name="chronos-api-base"]')?.content;
  if (!basePath) {
    root.textContent = "IRIS Chronos: the native API route is not configured. This source-only screen is not connected.";
    return;
  }
  try {
    client = createChronosClient({basePath, pageUrl: location.href});
    let storage = null;
    try { storage = globalThis.sessionStorage; } catch { /* Reads still work with blocked storage. */ }
    screen = mountResultScreen(root, {client, storage, evidence: "LIVE"});
  } catch {
    client?.disconnect(); client = null;
    root.textContent = "IRIS Chronos could not initialize. Check the installation route and secure origin.";
  }
}
start();
addEventListener("pagehide", stop);
addEventListener("pageshow", event => {
  // A browser back/forward-cache restoration does not reexecute module scripts.
  // Rebuild disconnected, without replaying the previous read or sign-out.
  if (event.persisted) start();
});
