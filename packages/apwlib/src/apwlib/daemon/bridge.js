// The bridge appended to the iCloud Passwords extension's background service worker.
//
// It runs inside the extension, so it can use the extension globals that implement
// Apple's crypto (`g_secretSession`, `g_nativeAppPort`) and pairing (`ChallengePIN`,
// `PINSet`). It dials the daemon's WebSocket server and proxies:
//
//   - `cmd:2` messages drive pairing (challenge / PIN), answered immediately.
//   - other commands are encrypted with `SecretSession.createSMSG` and posted to the
//     native helper; the helper's encrypted reply is decrypted with `parseSMSG`.
//   - it reports pairing state (`{paired}`) so the daemon can answer status queries.
//
// `self.APW_CONFIG` (port + token) is injected ahead of this script by extension.py.
//
// Hardening rules (this worker holds the SRP pairing — if it dies, the user must re-PIN):
//   * NOTHING may throw out of an event handler. Every extension/native/WebSocket call is
//     wrapped, and global error/rejection handlers swallow stragglers.
//   * Malformed requests are rejected up front — they never reach the crypto/native layer.
//   * Every reference to an extension global is `typeof`-guarded (undeclared globals would
//     otherwise raise ReferenceError and tear the worker down).
//   * A request that the native helper never answers is timed out and released, so one bad
//     request can't wedge the bridge.

(function apwBridge() {
  "use strict";

  const cfg = (self && self.APW_CONFIG) || {};
  const port = cfg.port;
  const token = cfg.token;

  const OK = 0;
  const INVALID_PARAM = 2;
  const INVALID_SESSION = 9;
  const SERVER_ERROR = 100;
  const NATIVE_TIMEOUT_MS = 25000; // below the daemon's 30s request timeout
  const RECONNECT_MS = 3000;

  let ws = null;
  let pending = null; // { id, cmd, timer }
  let reconnectTimer = null;

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

  const isOpen = () => !!ws && ws.readyState === WebSocket.OPEN;

  function send(message) {
    if (!isOpen()) return;
    try {
      ws.send(JSON.stringify(message));
    } catch (_e) {
      /* ignore */
    }
  }

  function fail(id, status, error) {
    if (id != null) send({ id: id, status: status, error: String(error) });
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
        if (typeof ChallengePIN !== "function") return fail(message.id, SERVER_ERROR, "pairing unavailable");
        // An abandoned handshake (challenge shown, PIN never submitted) parks the state
        // machine mid-flight — where ChallengePIN() is a silent no-op and the PIN would
        // never be shown again. Reset to NotInSession first so the challenge restarts.
        if (
          typeof resetTheSession === "function" &&
          typeof ContextState !== "undefined" &&
          typeof g_theState !== "undefined" &&
          (g_theState === ContextState.ChallengeSent || g_theState === ContextState.MSG1Set)
        ) {
          resetTheSession(ContextState.NotInSession);
        }
        ChallengePIN();
      } else {
        if (typeof PINSet !== "function") return fail(message.id, SERVER_ERROR, "pairing unavailable");
        PINSet(String(message.pin));
      }
      send({ id: message.id, status: OK });
    } catch (error) {
      fail(message.id, SERVER_ERROR, error);
    }
  }

  function request(message) {
    if (!message || typeof message !== "object") return;
    const id = message.id;

    if (message.cmd === 2) return pair(message);

    // Validate before touching the crypto or native layers.
    if (
      typeof message.cmd !== "number" ||
      typeof message.qid !== "string" ||
      !message.body ||
      typeof message.body !== "object"
    ) {
      return fail(id, INVALID_PARAM, "malformed request");
    }
    if (typeof g_secretSession === "undefined" || !g_secretSession) {
      return fail(id, INVALID_SESSION, "extension not ready");
    }
    if (typeof g_nativeAppPort === "undefined" || !g_nativeAppPort) {
      return fail(id, INVALID_SESSION, "extension not ready");
    }
    if (typeof g_theState === "undefined" || g_theState !== "SessionKeySet") {
      return fail(id, INVALID_SESSION, "unpaired");
    }
    if (pending) {
      // The daemon serializes requests, so this is defensive only.
      return fail(id, SERVER_ERROR, "busy");
    }

    let smsg;
    try {
      smsg = g_secretSession.createSMSG(JSON.stringify(message.body));
    } catch (error) {
      return fail(id, SERVER_ERROR, error);
    }

    pending = {
      id: id,
      cmd: message.cmd,
      timer: setTimeout(() => {
        const stuck = pending;
        clearPending();
        if (stuck) fail(stuck.id, SERVER_ERROR, "native helper timed out");
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
      fail(id, SERVER_ERROR, error);
    }
  }

  function reportState() {
    const paired = typeof g_theState !== "undefined" && g_theState === "SessionKeySet";
    send({ paired: paired });
  }

  function reply(message) {
    if (!message || typeof message !== "object") return;
    if (message.cmd === 14) {
      reportState(); // the capability hello rebuilds SecretSession — report the fresh state
      return;
    }
    reportState(); // keep the daemon's view of pairing state current
    if (!pending) return;
    const matches = message.cmd === pending.cmd || (pending.cmd === 6 && message.cmd === 4);
    if (!matches) return;
    const id = pending.id;
    clearPending();
    try {
      const data = message.payload
        ? JSON.parse(g_secretSession.parseSMSG(message.payload.SMSG))
        : { STATUS: typeof message.STATUS === "number" ? message.STATUS : OK };
      send({ id: id, data: data });
    } catch (error) {
      fail(id, SERVER_ERROR, error);
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(connect, RECONNECT_MS);
  }

  function connect() {
    reconnectTimer = null;
    try {
      ws = new WebSocket(`ws://127.0.0.1:${port}`);
    } catch (_e) {
      scheduleReconnect();
      return;
    }
    ws.onopen = () => {
      send({ token: token });
      reportState();
    };
    ws.onerror = () => {
      try {
        ws.close();
      } catch (_e) {
        /* ignore */
      }
    };
    ws.onclose = () => {
      clearPending();
      scheduleReconnect();
    };
    ws.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (_e) {
        return; // ignore non-JSON frames
      }
      try {
        request(message);
      } catch (error) {
        fail(message && message.id, SERVER_ERROR, error);
      }
    };
  }

  // Keep the service worker alive. MV3 evicts an idle worker (~30s); eviction would
  // silently drop the pairing and the bridge, and the reconnect timer dies with the
  // worker. A periodic no-op API call resets the idle timer, and we redial the socket
  // if it has dropped. Permission-free (getPlatformInfo needs none), so no manifest
  // change — works across Chromium versions.
  const KEEPALIVE_MS = 20000; // under the ~30s idle-eviction window
  function keepAlive() {
    try {
      if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.getPlatformInfo) {
        chrome.runtime.getPlatformInfo(() => {});
      }
    } catch (_e) {
      /* ignore */
    }
    if (!isOpen()) {
      try {
        connect();
      } catch (_e) {
        /* ignore */
      }
    }
  }
  try {
    setInterval(keepAlive, KEEPALIVE_MS);
  } catch (_e) {
    /* ignore */
  }

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

  connect();
})();
