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
// Hardening rules (this worker holds the SRP pairing — if it dies, the user must re-PIN):
//   * NOTHING may throw out of a handler. Every extension/native call is wrapped, and
//     global error/rejection handlers swallow stragglers.
//   * Malformed requests are rejected up front — they never reach the crypto/native layer.
//   * Every reference to an extension global is `typeof`-guarded (undeclared globals would
//     otherwise raise ReferenceError and tear the worker down).
//   * A request that the native helper never answers is timed out and released, so one bad
//     request can't wedge the bridge.

(function apwBridge() {
  "use strict";

  const OK = 0;
  const INVALID_PARAM = 2;
  const INVALID_SESSION = 9;
  const SERVER_ERROR = 100;
  const NATIVE_TIMEOUT_MS = 25000; // below the daemon's 30s request timeout

  let pending = null; // { resolve, cmd, timer }

  // Keep the worker alive: swallow stray errors/rejections rather than let the runtime
  // tear it down (which would drop the pairing).
  const swallow = (event) => {
    try {
      event.preventDefault();
    } catch (_e) {
      /* ignore */
    }
  };
  try {
    self.addEventListener("error", swallow);
    self.addEventListener("unhandledrejection", swallow);
  } catch (_e) {
    /* ignore */
  }

  // The live pairing state, read on demand. Reports the raw handshake state too: it
  // lets the client tell a collapsed handshake (back to NotInSession after a verify —
  // e.g. a wrong PIN) from one still in progress, so it can fail fast instead of waiting
  // out the pairing timeout.
  function readState() {
    const state = typeof g_theState !== "undefined" ? g_theState : null;
    return { paired: state === "SessionKeySet", state: state };
  }

  function clearPending() {
    if (pending && pending.timer) {
      try {
        clearTimeout(pending.timer);
      } catch (_e) {
        /* ignore */
      }
    }
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
      return { status: INVALID_SESSION, error: "unpaired" };
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
  try {
    py_chauffeur.on("status", readState);
    py_chauffeur.on("request", request);
  } catch (_e) {
    /* ignore */
  }

  // Keeping the worker alive (so the pairing isn't dropped) is chauffeur's job:
  // the spec's keep_alive (see extension.py) pokes this worker from Python on a
  // short interval — reliable, unlike an in-worker setInterval that MV3 suspends
  // on a dormant worker.

  // Ensure the native port exists and route its replies to us.
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
