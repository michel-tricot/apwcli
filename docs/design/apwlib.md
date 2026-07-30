# apwlib design

How `apwlib` reaches Apple Passwords, and how it's built on top of that. The
`apwcli` CLI is a thin wrapper over the library. Code blocks here are
illustrative and are *not* executed by the test suite.

---

# Part 1 — How Apple Passwords communication works

## The problem in one picture

```
   your code                Apple's password helper                iCloud Keychain
  ───────────    ══╳══>    (native-messaging host)      ───────>    (the vault)
                    │
                    └── SIGKILL: the helper only accepts a notarized browser as its parent
```

## The helper

Apple brokers keychain access for third-party browsers through one native
binary, the **browser-extension helper**:

```
/System/Cryptexes/App/System/Library/CoreServices/
  PasswordManagerBrowserExtensionHelper.app/Contents/MacOS/PasswordManagerBrowserExtensionHelper
```

It is entitled for the shared keychain, and its bundle owns the 6-digit PIN
dialog. Chrome-family browsers and Firefox go through it; Safari reaches
passwords directly and doesn't use it.

## The wire: Chrome native messaging

The helper is a Chrome **native-messaging host**, registered via manifests
like `/Library/Google/Chrome/NativeMessagingHosts/com.apple.passwordmanager.json`
(which also name the extension IDs allowed to connect). Communication is the
standard native-messaging exchange:

1. The iCloud Passwords extension's background service worker opens the port
   (`chrome.runtime.connectNative`) and keeps it in a global,
   `g_nativeAppPort`.
2. The **browser** spawns the helper as a child process and wires the port to
   the helper's stdin/stdout.
3. Each message, in either direction, is a **4-byte little-endian length
   followed by that many bytes of UTF-8 JSON**: requests are `postMessage`
   calls on the port, replies arrive via `port.onMessage`.

That stdio pipe between extension and helper is the *only* channel. There is
no socket and no XPC — from outside the browser there is nothing to connect
to.

## Why it must run inside a browser

The helper carries a **kernel-enforced parent launch constraint**: its
immediate parent must be a notarized browser from a fixed allow-list
(Chrome, Brave, Edge, Firefox, Arc, Vivaldi, Opera, ungoogled-chromium,
Zen, …) or carry Apple's web-browser entitlement. Spawn it from anything else
and it's `SIGKILL`ed before a byte moves.

**Consequence:** the only sanctioned path to the helper is *inside* an
approved browser running the real **iCloud Passwords extension** — which is
also where Apple's crypto lives. The extension is the engine; anything we
build is transport around it.

> **Why a headless browser?** Since an approved browser is the only allowed
> parent for the helper and the only host for the extension, apwlib has to
> run one — but it's pure plumbing, nothing is ever browsed in it. So the
> daemon launches it **headless**: no window on screen, running unattended in
> the background for the daemon's lifetime.

## Pairing and encryption

Before the helper answers anything, the extension must pair with it; every
command after that is encrypted with the session key the pairing produced.

1. **SRP-6a pairing** (RFC 5054, 3072-bit group, SHA-256) — a 4-message PAKE
   over the port:
   - `MSG0`/`MSG1` — identity + public values
   - `MSG2` — helper returns salt + its public value **and shows a 6-digit PIN**
   - `MSG3` — client proves knowledge of the PIN (`M1`); helper confirms
     (`HAMK`)

   The PIN is the SRP password; the session key is derived from it.
2. **Per command**, the plaintext body is encrypted into an `SMSG` with the
   session key (AES-128-GCM): envelope `{ TID, SDATA }`; IV appended
   client→helper, prepended helper→client.

Two pairing properties drive the whole design:

- The pairing lives only in the extension's service worker, for that browser's
  lifetime.
- The helper **issues a new PIN for every handshake** and needs a human to read
  it — it never re-authenticates a known identity. So a pairing **cannot be
  persisted** across a browser/helper restart. This is a deliberate security
  boundary, not a gap.

## Commands

The plaintext `body` the extension encrypts, per operation:

| operation | `cmd` | `qid` | `body` |
| --- | --- | --- | --- |
| list accounts | 4 | `CmdGetLoginNames4URL` | `{ACT:5 (GHOST_SEARCH), URL}` |
| get password | 5 | `CmdGetPassword4LoginName` | `{ACT:2 (SEARCH), URL, USR}` |
| save account | 6 | `CmdSetPassword4LoginName_URL` | `{ACT:4 (MAYBE_ADD), URL:"",USR:"",PWD:"", NURL,NUSR,NPWD}` |
| get OTP | 17 | `CmdDidFillOneTimeCode` | `{ACT:2, TYPE:"oneTimeCodes", frameURLs:[url]}` |
| list OTP | 16 | `CmdDidFillOneTimeCode` | `{ACT:5, TYPE:"oneTimeCodes", frameURLs:[url]}` |

- **Response:** the decrypted `data` has a `STATUS`; entries arrive as an
  `Entries` array or as `Entry_0…Entry_n` keys. `STATUS 3` (no results) → empty;
  any other non-zero status is an error.
- **Status codes:** `SUCCESS 0, GENERIC 1, INVALID_PARAM 2, NO_RESULTS 3,
  FAILED_DELETE 4, FAILED_UPDATE 5, INVALID_MESSAGE 6, DUPLICATE 7,
  UNKNOWN_ACTION 8, INVALID_SESSION 9, SERVER_ERROR 100`.
- **Save quirk:** a save (`cmd 6`) is answered as `cmd 4`.
- **Scope:** every read is keyed to a URL, matched by **registrable domain**.
  There is no enumerate-all command — the protocol is built for per-site
  autofill, so listing an entire vault isn't possible through it.

---

# Part 2 — How the library is designed

`apwlib` drives a headless approved browser, loads a copy of the iCloud
Passwords extension with a small **bridge** injected, and proxies encrypted
messages. The browser does the crypto; Python is transport and orchestration.

## Architecture

```
  ┌─────────────┐   unix socket   ┌──────────────┐    CDP     ┌────────────────────┐
  │   apwcli    │ ──────────────▶ │    daemon    │ ─────────▶ │  headless browser  │
  │  (Typer)    │   JSON lines    │ (apwlib.     │  load ext  │  ┌──────────────┐  │
  │             │                 │   daemon)    │            │  │ iCloud Pwds  │  │
  │ ApplePass-  │ ◀────────────── │              │ ◀────────▶ │  │ extension +  │  │
  │ words facade│                 │  WebSocket   │  bridge.js │  │ bridge.js    │  │
  └─────────────┘                 │  + socket    │  messages  │  │ (SRP + SMSG) │  │
                                  └──────────────┘            │  └──────┬───────┘  │
                                                              └─────────┼──────────┘
                                                                        │ native messaging
                                                                        ▼
                                              PasswordManagerBrowserExtensionHelper
```

The facade never imports the `daemon/` subpackage — it spawns
`python -m apwlib.daemon` and talks over the socket, so `import apwlib` stays
light.

## Module layout

```
client.py       ApplePasswords facade (password API) + _Daemon (transport,
                  lifecycle, pairing; exposed as ApplePasswords.daemon)
protocol.py     Command / Action / Status enums, message builders, response parsing
models.py       PasswordEntry, OTPEntry
errors.py       ApwError hierarchy (SessionError → DaemonNotRunning / NotPaired)
config.py       read/write ~/.apwlib/config.json
paths.py        ~/.apwlib locations (socket, lock, extension dir, browser profile)
browsers.py     discover installed approved browsers + the installed extension source
                  (shared by daemon/ and pinwindow/)
pinwindow/
  __init__.py   request_pin — no-TTY pin_provider (PIN-entry window)
  page.html     the six-box code page
  default.css   default stylesheet (overridden by ~/.apwlib/pinwindow.css or css=)
daemon/
  __main__.py   `python -m apwlib.daemon` entry point
  server.py     owns the browser; WebSocket bridge + unix-socket servers; singleton lock
  extension.py  build a modified extension copy with bridge.js + local config injected
  bridge.js     JavaScript bridge appended to the extension's background worker
  bridge.py     loads bridge.js
  cdp.py        minimal Chrome DevTools client: load the unpacked extension
```

## Request flow

```
  facade.get_password(url)
    → connect ~/.apwlib/apw.sock, write one JSON line {cmd, qid, tabId, frameId, url, body}
    → daemon tags it with an id, forwards over WebSocket to the bridge
    → bridge encrypts body with the extension's SecretSession, posts to the helper
    → helper's encrypted reply decrypted by the bridge → {id, data} back to the daemon
    → daemon returns the line; facade parses data into PasswordEntry/OTPEntry
```

## Daemon lifecycle (auto-managed singleton)

Callers never manage the daemon. A facade call that finds none spawns
`python -m apwlib.daemon` **detached** (`start_new_session`), so it outlives the
caller and survives closing the terminal, waits for the bridge, then retries.
The daemon takes an exclusive `flock` on `~/.apwlib/daemon.lock` first, so
concurrent auto-starts are race-safe (losers exit before touching the
socket/profile). A small control channel (`{"op":"status"}` / `{"op":"stop"}`)
reports readiness/pairing and requests shutdown without involving the
extension.

Because a pairing can't be persisted (Part 1), the model is: pair once per
daemon lifetime, keep the daemon (hence the browser and its in-memory session)
alive to make the PIN rare.

A running daemon can outlive its bridge (the browser is killed, the worker
gone) and get stuck: a fresh spawn would only lose the singleton-lock race and
exit. So `start` treats *running but bridge-dead* as unhealthy — it stops that
daemon and replaces it — and `deliver` routes a `no extension connected`
response through the same recovery, so commands self-heal instead of waiting on
a bridge that will never come. `restart` (exposed as `apwcli daemon restart`)
forces the stop-and-replace unconditionally.

## Pairing in the library

The facade takes an optional `pin_provider`. On an `unpaired` response it pairs
transparently — triggers the challenge (macOS shows the PIN), calls
`pin_provider()`, waits until paired, and retries the request. Without a
provider, an unpaired call raises `NotPairedError`.

For callers without a terminal, `apwlib.pinwindow.request_pin` is a bundled
`pin_provider` that pops a dialog-sized PIN window: a localhost-only,
single-use HTTP server serves a six-box code page (`page.html`), opened
via an installed browser binary in chromeless `--app` mode with a throwaway
profile — preferring the browser the user is actually running. Anyone who can
read the macOS PIN dialog is at the screen, so an on-screen window is always
answerable when pairing is possible at all. The page posts the PIN back
(or an empty PIN from a close beacon, so a dismissed window fails fast);
launch failure, cancellation, or timeout surface as `NotPairedError`
(exit code 9). Styling is a stylesheet served at `/style.css`, resolved as:
`css=` argument → user override at `~/.apwlib/pinwindow.css` → bundled
`default.css`. The CLI prompts in the terminal on a TTY and falls back to
this window otherwise.

## The bridge

`daemon/bridge.js` runs in the extension's MV3 service worker, which holds the
pairing — if it dies, the user must re-PIN. It is written to never throw out of
an event handler:

- Global `error` / `unhandledrejection` handlers `preventDefault()` stray
  failures so the worker isn't torn down.
- Every extension/native/WebSocket call is wrapped; every extension global is
  `typeof`-guarded (an undeclared global would `ReferenceError` and kill it).
- Requests are validated (cmd/qid/body shape) **before** the crypto/native layer.
- A single in-flight request has a native-reply timeout, so a request the helper
  never answers is released instead of wedging the bridge.
- It reports pairing state (`{paired}`) and reconnects once on WebSocket close.

## Models

```python
from dataclasses import dataclass, field


@dataclass
class PasswordEntry:
    username: str
    domain: str
    password: str | None = None
    title: str | None = None
    sites: list[str] = field(default_factory=list)
    high_level_domain: str | None = None


@dataclass
class OTPEntry:
    username: str
    domain: str
    code: str | None = None
    source: str | None = None
```

## Design decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Approach | Managed browser + real extension | The launch constraint leaves no browserless option; reuse an installed browser and the official extension. |
| Crypto | Runs in the browser, not Python | The extension's `SecretSession` implements Apple's SRP/SMSG correctly — proxy it, no reimplementation risk. |
| Facade API | Sync | The client talks to a local socket with line framing; trivially synchronous and easy from a CLI. |
| Runtime | Auto-managed singleton daemon | Owns the browser and the in-memory session; auto-starts detached and is reused, so the PIN is entered once per daemon lifetime. |
| CLI secrets | Mask in tables, clipboard opt-in | Passwords otherwise land in terminal scrollback. `text`/`json` (pipe targets) stay unmasked; `-c` routes the value via `pbcopy`, never stdout. |
| No-TTY pairing | App-mode PIN window | The PIN must be typed by a human at the screen. A chromeless `--app` window of the managed browser looks like a native dialog and adds no dependency; PyObjC (heavy) and osascript (crude) lost. |
| MCP scope | No plaintext passwords by default | MCP tool results are sent to the model provider. `list_accounts`/`get_otp`/`save_password` are safe; `get_password` is gated behind `--allow-passwords`. |
| Dependencies | `websockets` (lib), `typer`/`rich`/`fastmcp` (CLI) | The daemon needs a WebSocket server (bridge) and client (CDP); no crypto dependency. |
| Platform | macOS 14+, Python ≥ 3.11 | The helper, extension, and PIN flow are macOS-only; a non-macOS spawn fails with a clear error. |

## Notes & limits

- **Service-worker eviction:** the paired session lives in the MV3 worker, which
  the browser may evict; the bridge reconnects, and an evicted pairing surfaces
  as `NotPairedError` so the client can re-pair.
- **Version drift:** the daemon reads the native-messaging manifest for the
  helper path and locates the installed extension dynamically, rather than
  hard-coding versions.
- **Headless loading:** the extension is loaded via CDP `Extensions.loadUnpacked`,
  which needs the browser launched with remote debugging +
  `--enable-unsafe-extension-debugging`.
- **No secrets in logs:** the daemon log (`~/.apwlib/daemon.log`) records
  lifecycle and errors only; command bodies (which carry passwords) are
  encrypted inside the bridge and never logged in plaintext.
