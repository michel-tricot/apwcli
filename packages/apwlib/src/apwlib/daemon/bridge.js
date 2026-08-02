// The bridge appended to the iCloud Passwords extension's background service worker.
//
// It runs inside the extension, so it can use the extension globals that implement
// Apple's crypto (`g_secretSession`, `g_nativeAppPort`) and pairing (`ChallengePIN`,
// `PINSet`). It talks to the daemon over chauffeur's `py_chauffeur` channel, which
// chauffeur installs in this worker before this code runs:
//
//   - the daemon drives one handler, `py_chauffeur.on("request", …)`, and awaits its
//     result — no id correlation, reconnect, or socket to manage here.
//   - `cmd:2` requests drive pairing (challenge / PIN), answered immediately.
//   - other requests are encrypted with `SecretSession.createSMSG`, posted to the
//     native helper, and the request resolves when the helper's encrypted reply
//     arrives and is decrypted with `parseSMSG`.
//   - the daemon pulls pairing state on demand via `py_chauffeur.on("status", …)`,
//     which reads `g_theState` live. Pulling (not pushing) is race-free: a poll
//     reads the current truth, and if the worker is mid-handshake the read simply
//     queues behind the crypto and returns the settled state.
//
// Status codes, the native timeout, and the "unpaired" wire marker arrive in
// `globalThis.__chauffeur_config`, injected by extension.py — protocol.py is their
// single source of truth, so there are no mirrored literals to keep in sync.
//
// Hardening rules (this worker holds the SRP pairing — if it dies, the user must re-PIN):
//   * Malformed requests are rejected up front — they never reach the crypto/native layer.
//   * Every reference to an extension global is `typeof`-guarded (undeclared globals would
//     otherwise raise ReferenceError). A throw out of a `py_chauffeur.on` handler is
//     already safe — chauffeur's channel converts it into an error reply — so the
//     try/catch here exists to return precise statuses, and to protect the native-port
//     listener (`reply`), which chauffeur does NOT wrap.
//   * A request that the native helper never answers is timed out and released, so one bad
//     request can't wedge the bridge.
//   * Global error/rejection handlers swallow stray failures from the extension's own
//     code rather than let the runtime tear the worker down.

(function apwBridge() {
  "use strict";

  const CONFIG = globalThis.__chauffeur_config;
  const OK = CONFIG.statusOk;
  const INVALID_PARAM = CONFIG.statusInvalidParam;
  const INVALID_SESSION = CONFIG.statusInvalidSession;
  const SERVER_ERROR = CONFIG.statusServerError;
  const NATIVE_TIMEOUT_MS = CONFIG.nativeTimeoutMs;
  const UNPAIRED = CONFIG.wireUnpaired;

  let pending = null; // { resolve, cmd, timer }

  // Keep the worker alive: swallow stray errors/rejections from the extension's own
  // code rather than let the runtime tear it down (which would drop the pairing).
  self.addEventListener("error", (event) => event.preventDefault());
  self.addEventListener("unhandledrejection", (event) => event.preventDefault());

  // The live pairing state, read on demand. Reports the raw handshake state too: it
  // lets the client tell a collapsed handshake (back to NotInSession after a verify —
  // e.g. a wrong PIN) from one still in progress, so it can fail fast instead of waiting
  // out the pairing timeout.
  function readState() {
    const state = typeof g_theState !== "undefined" ? g_theState : null;
    return { paired: state === "SessionKeySet", state: state };
  }

  function clearPending() {
    if (pending) clearTimeout(pending.timer);
    pending = null;
  }

  function pair(message) {
    try {
      if (message.pin == null) {
        if (typeof ChallengePIN !== "function") return { status: SERVER_ERROR, error: "pairing unavailable" };
        // ChallengePIN() only starts a handshake from NotInSession; from any other state it
        // is a silent no-op. So reset to NotInSession first from ANY active state — a parked
        // mid-handshake (ChallengeSent/MSG1Set) OR an existing pairing (SessionKeySet).
        // Resetting a live pairing matters: otherwise a re-pair shows no PIN dialog, and the
        // stale paired=true makes a wrong PIN look like success. A fresh challenge means a
        // wrong PIN genuinely fails.
        if (
          typeof resetTheSession === "function" &&
          typeof ContextState !== "undefined" &&
          typeof g_theState !== "undefined" &&
          g_theState !== ContextState.NotInSession
        ) {
          resetTheSession(ContextState.NotInSession);
        }
        ChallengePIN();
      } else {
        if (typeof PINSet !== "function") return { status: SERVER_ERROR, error: "pairing unavailable" };
        PINSet(String(message.pin));
      }
      return { status: OK };
    } catch (error) {
      return { status: SERVER_ERROR, error: String(error) };
    }
  }

  // The daemon's single command. Resolves to a response object: `{ data }` on success,
  // `{ status, error }` on failure — the same shape the client keys on.
  async function request(message) {
    if (!message || typeof message !== "object") return { status: INVALID_PARAM, error: "malformed request" };

    if (message.cmd === 2) return pair(message);

    // Validate before touching the crypto or native layers.
    if (
      typeof message.cmd !== "number" ||
      typeof message.qid !== "string" ||
      !message.body ||
      typeof message.body !== "object"
    ) {
      return { status: INVALID_PARAM, error: "malformed request" };
    }
    if (typeof g_secretSession === "undefined" || !g_secretSession) {
      return { status: INVALID_SESSION, error: "extension not ready" };
    }
    if (typeof g_nativeAppPort === "undefined" || !g_nativeAppPort) {
      return { status: INVALID_SESSION, error: "extension not ready" };
    }
    if (typeof g_theState === "undefined" || g_theState !== "SessionKeySet") {
      return { status: INVALID_SESSION, error: UNPAIRED };
    }
    if (pending) {
      // The daemon serializes requests, so this is defensive only.
      return { status: SERVER_ERROR, error: "busy" };
    }

    let smsg;
    try {
      smsg = g_secretSession.createSMSG(JSON.stringify(message.body));
    } catch (error) {
      return { status: SERVER_ERROR, error: String(error) };
    }

    return await new Promise((resolve) => {
      pending = {
        resolve: resolve,
        cmd: message.cmd,
        timer: setTimeout(() => {
          const stuck = pending;
          clearPending();
          if (stuck) stuck.resolve({ status: SERVER_ERROR, error: "native helper timed out" });
        }, NATIVE_TIMEOUT_MS),
      };
      try {
        g_nativeAppPort.postMessage({
          cmd: message.cmd,
          tabId: message.tabId,
          frameId: message.frameId,
          url: message.url,
          payload: JSON.stringify({ QID: message.qid, SMSG: smsg }),
        });
      } catch (error) {
        clearPending();
        resolve({ status: SERVER_ERROR, error: String(error) });
      }
    });
  }

  // Runs on the native port, outside py_chauffeur's dispatch — nothing here may throw.
  function reply(message) {
    if (!message || typeof message !== "object") return;
    if (!pending) return;
    const matches = message.cmd === pending.cmd || (pending.cmd === 6 && message.cmd === 4);
    if (!matches) return;
    const resolve = pending.resolve;
    clearPending();
    try {
      const data = message.payload
        ? JSON.parse(g_secretSession.parseSMSG(message.payload.SMSG))
        : { STATUS: typeof message.STATUS === "number" ? message.STATUS : OK };
      resolve({ data: data });
    } catch (error) {
      resolve({ status: SERVER_ERROR, error: String(error) });
    }
  }

  // Register the daemon-facing handlers. chauffeur installs py_chauffeur in this worker
  // before this script runs, so the channel is ready here. "status" is pulled by the
  // daemon to read live pairing state; "request" carries commands and pairing.
  py_chauffeur.on("status", readState);
  py_chauffeur.on("request", request);

  // Keeping the worker alive (so the pairing isn't dropped) is chauffeur's job:
  // the spec's keep_alive (see extension.py) pokes this worker from Python on a
  // short interval — reliable, unlike an in-worker setInterval that MV3 suspends
  // on a dormant worker.

  // Ensure the native port exists and route its replies to us. Apple's code can
  // throw here (e.g. no native host installed); requests re-check the port per
  // call, so a failed hookup degrades to "extension not ready", not a dead worker.
  try {
    if (typeof g_nativeAppPort === "undefined" || !g_nativeAppPort) {
      if (typeof connectToBackgroundNativeAppAndSetUpListeners === "function") {
        connectToBackgroundNativeAppAndSetUpListeners();
      }
    }
    if (
      typeof g_nativeAppPort !== "undefined" &&
      g_nativeAppPort &&
      g_nativeAppPort.onMessage &&
      typeof g_nativeAppPort.onMessage.addListener === "function"
    ) {
      g_nativeAppPort.onMessage.addListener(reply);
    }
  } catch (_e) {
    /* ignore */
  }
})();
