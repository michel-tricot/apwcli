# apwlib design

`apwlib` provides programmatic access to Apple Passwords (iCloud Keychain) on macOS; the
`apwcli` CLI is a thin wrapper over it. This document has two parts: how communication with
Apple Passwords works, and how the library is designed on top of it. Code blocks are
illustrative and are *not* executed by the test suite.

---

# Part 1 — How Apple Passwords communication works

## The password helper

Apple ships a native binary that brokers access to iCloud Passwords for third-party
browsers — a Chrome **native-messaging host** (stdio):

```
/System/Cryptexes/App/System/Library/CoreServices/PasswordManagerBrowserExtensionHelper.app/Contents/MacOS/PasswordManagerBrowserExtensionHelper
```

It is entitled for the shared keychain (`keychain-access-groups`,
`com.apple.private.keychain.kcsharing.client`) and its bundle owns the 6-digit PIN dialog
(`PairingPINWindowController`). It is registered for Chrome and Firefox via manifests like
`/Library/Google/Chrome/NativeMessagingHosts/com.apple.passwordmanager.json` — Safari
doesn't use it (WebKit reaches passwords directly), so this path is Chromium/Firefox only.

## Only an approved browser may talk to it

The helper carries a **kernel-enforced parent launch constraint**: its immediate parent
must be a notarized browser (matching signing-identifier + team-identifier from a fixed
allow-list — Chrome, Brave, Edge, Firefox, Arc, Vivaldi, Opera, ungoogled-chromium, Zen,
…), or carry Apple's `com.apple.developer.web-browser.public-key-credential` entitlement.
Spawning it from anything else is `SIGKILL`ed before a byte is exchanged.

**Consequence:** the only sanctioned way to reach the helper is *inside* an approved
browser running the real **iCloud Passwords extension** — which is also where Apple's
crypto lives. So the extension is the engine; anything we build is transport around it.

## Transport & framing

The extension speaks to the helper over Chrome native messaging: each message is a 4-byte
little-endian length prefix + a UTF-8 JSON body, over the helper's stdin/stdout (via
`chrome.runtime.connectNative("com.apple.passwordmanager")`).

A command message envelope is:

```
{ cmd, tabId, frameId, url, payload: JSON.stringify({ QID, SMSG }) }
```

where `SMSG` is the encrypted command body (below). Replies come back with the same `cmd`
and a `payload` carrying an encrypted `SMSG`.

## Pairing (SRP + PIN)

Access is gated by an SRP-6a pairing (RFC 5054 3072-bit group, SHA-256). The handshake is a
4-message PAKE (`MSG0…MSG3`): the client sends its identity + public value, the helper
replies with salt + its public value **and displays a fresh 6-digit PIN**, the client
proves knowledge of the PIN (`M1`), and the helper confirms (`HAMK`). The PIN is the SRP
password; the session key is derived from it.

Two properties matter:

- The pairing lives only in the extension's service worker, for that browser's lifetime.
- The helper **generates a new PIN for every handshake** and requires a human to read it —
  it never re-authenticates a known identity. So a pairing **cannot be persisted** across a
  browser/helper restart; a restart always means a new PIN. (This is a deliberate security
  boundary, not a gap.)

## Message encryption (SMSG)

After pairing, each plaintext command `body` is encrypted into an **SMSG** with the session
key (AES-128-GCM). The SMSG is a JSON envelope `{ TID, SDATA }` — `TID` is the client
identity, `SDATA` the base64/hex ciphertext (the extension's `createSMSG` / `parseSMSG`).
IV placement differs by direction (client→helper appends the IV; helper→client prepends
it).

## Commands & responses

The plaintext `body` the extension encrypts, per operation:

| operation | `cmd` | `qid` | `body` |
| --- | --- | --- | --- |
| list accounts | 4 | `CmdGetLoginNames4URL` | `{ACT:5 (GHOST_SEARCH), URL}` |
| get password | 5 | `CmdGetPassword4LoginName` | `{ACT:2 (SEARCH), URL, USR}` |
| save account | 6 | `CmdSetPassword4LoginName_URL` | `{ACT:4 (MAYBE_ADD), URL:"",USR:"",PWD:"", NURL,NUSR,NPWD}` |
| get OTP | 17 | `CmdDidFillOneTimeCode` | `{ACT:2, TYPE:"oneTimeCodes", frameURLs:[url]}` |
| list OTP | 16 | `CmdDidFillOneTimeCode` | `{ACT:5, TYPE:"oneTimeCodes", frameURLs:[url]}` |

- **Response:** decrypted `data` has a `STATUS`; entries arrive either as an `Entries`
  array or as `Entry_0…Entry_n` keys. `STATUS 3` (no results) → empty; any other non-zero
  status is an error.
- **Status codes:** `SUCCESS 0, GENERIC 1, INVALID_PARAM 2, NO_RESULTS 3, FAILED_DELETE 4,
  FAILED_UPDATE 5, INVALID_MESSAGE 6, DUPLICATE 7, UNKNOWN_ACTION 8, INVALID_SESSION 9,
  SERVER_ERROR 100`.
- **Save quirk:** a save (`cmd 6`) is answered by the helper as `cmd 4`.
- **Scope:** every read is keyed to a URL, matched by **registrable domain** (subdomains
  and associated domains collapse to it). There is no enumerate-all command — the protocol
  is built for per-site autofill, so listing an entire vault is not possible through it.

---

# Part 2 — How the library is designed

Given the constraint above, `apwlib` drives a headless approved browser, loads a copy of
the iCloud Passwords extension with a small **bridge** injected, and proxies encrypted
messages. The browser does the crypto; our Python code is transport and orchestration.

## Architecture

```
apwcli (Typer CLI)  ──unix socket──▶  apwlib daemon  ──CDP──▶  headless approved browser
                                          │                        │  loads modified
   ApplePasswords facade  ◀──────────────┘                        │  iCloud Passwords ext
   (sync socket client)                     ◀──WebSocket (bridge)──┘  (does SRP + SMSG)
                                                                       │  native messaging
                                                                       ▼
                                                       PasswordManagerBrowserExtensionHelper
```

## Module layout

Client-facing modules are top level; all browser/daemon machinery lives in the `daemon/`
subpackage. The facade never imports the daemon — it spawns `python -m apwlib.daemon` and
talks over the socket, so importing `apwlib` stays light.

```
client.py       # ApplePasswords facade (password API) + _Daemon (transport/lifecycle/
                #   pairing, exposed as ApplePasswords.daemon and backing `apwcli daemon …`)
protocol.py     # Command / Action / Status enums, message builders, response parsing
models.py       # PasswordEntry, OTPEntry
errors.py       # ApwError hierarchy (SessionError → DaemonNotRunningError / NotPairedError)
config.py       # read/write ~/.apwlib/config.json
paths.py        # ~/.apwlib locations (socket, lock, extension dir, browser profile)
daemon/
  __main__.py   # `python -m apwlib.daemon` entry point
  server.py     # owns the browser; WebSocket bridge server; unix-socket server; singleton lock
  browsers.py   # discover installed approved browsers + the installed extension source
  extension.py  # build a modified extension copy with bridge.js + local config injected
  bridge.js     # the JavaScript bridge appended to the extension's background worker
  bridge.py     # loads bridge.js
  cdp.py        # minimal Chrome DevTools client: load the unpacked extension
```

## How a request flows

1. `ApplePasswords.get_password(...)` connects to `~/.apwlib/apw.sock` and writes one JSON
   line: the command (`cmd`, `qid`, `tabId`, `frameId`, `url`, `body`).
2. The daemon tags it with an `id` and forwards it over the WebSocket to the bridge in the
   extension's service worker.
3. The bridge encrypts `body` with the extension's `SecretSession` and posts it to the
   helper.
4. The helper's encrypted reply is decrypted by the bridge, which sends `{id, data}` back.
5. The daemon returns that line; the facade parses `data` into models.

## Daemon lifecycle (auto-managed singleton)

Callers never manage the daemon. A facade call that finds none spawns
`python -m apwlib.daemon` **detached** (`start_new_session`), so it outlives the caller and
survives closing the terminal; it waits for the bridge to connect, then retries. The daemon
takes an exclusive `flock` on `~/.apwlib/daemon.lock` as its first step, so concurrent
auto-starts are race-safe (losers exit before touching the socket/profile) and two daemons
can't clobber each other. A small control channel over the socket
(`{"op":"status"}` / `{"op":"stop"}`) reports readiness / pairing and requests shutdown
without involving the extension.

Because a pairing can't be persisted (Part 1), the model is: pair once per daemon lifetime,
and keep the daemon (hence the browser and its in-memory session) alive to make the PIN
rare.

## Pairing in the library

The facade takes an optional `pin_provider`. On an `unpaired` response it runs the pairing
transparently — triggers the challenge (macOS shows the PIN), calls `pin_provider()` for
the code, waits until the daemon reports paired, and retries the original request. The CLI
supplies a terminal prompt; without a provider, an unpaired call raises `NotPairedError`.

## The bridge

`daemon/bridge.js` runs in the extension's MV3 service worker, which holds the pairing — if
it dies, the user must re-PIN. It is written to never throw out of an event handler:

- Global `error` / `unhandledrejection` handlers `preventDefault()` stray failures so the
  worker isn't torn down.
- Every extension/native/WebSocket call is wrapped; every extension global is
  `typeof`-guarded (an undeclared global would raise `ReferenceError` and kill the worker).
- Requests are validated (cmd/qid/body shape) **before** reaching the crypto/native layer.
- A single in-flight request has a native-reply timeout, so a request the helper never
  answers is released instead of wedging the bridge.
- It reports pairing state (`{paired}`) so the daemon can answer status queries, and
  reconnects once on WebSocket close.

## Errors

`ApwError(status, message)` is the base, carrying a protocol `Status`. `SessionError` (for
`INVALID_SESSION`) refines into `DaemonNotRunningError` (no daemon — auto-start + retry) and
`NotPairedError` (up but unpaired — pair, or raise); `ServerError` covers `SERVER_ERROR`.
Reads return `[]` for no results rather than raising.

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

## CLI surface

Data commands return rows and support `--format text|json|table` (table default):

- `apwcli pw get <url> [username]` / `apwcli pw list <url>` / `apwcli pw save <url> <username>`
- `apwcli otp get <url>` / `apwcli otp list <url>`

Daemon & pairing commands (a separate help panel) write dotted statuses, no `--format`:

- `apwcli daemon status` — daemon / extension / pairing state
- `apwcli daemon pair` — pair with a PIN (prompts, or `--pin`)
- `apwcli daemon start [--browser …] [--foreground]` — usually unnecessary; `stop`

## Design decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Approach | Managed browser + real extension | The launch constraint leaves no browserless option; reuse an installed browser and the official extension. |
| Crypto | Runs in the browser, not Python | The extension's `SecretSession` implements Apple's SRP/SMSG correctly — proxy it, no reimplementation risk. |
| Facade API | Sync | The client talks to a local socket with line framing; trivially synchronous and easy from a CLI. |
| Runtime | Auto-managed singleton daemon | Owns the browser and the in-memory session; auto-starts detached and is reused, so the PIN is entered once per daemon lifetime. |
| Dependencies | `websockets` (lib), `typer`/`rich` (CLI) | The daemon needs a WebSocket server (bridge) and client (CDP); no crypto dependency. |
| Platform | macOS 14+, Python ≥ 3.11 | The helper, extension, and PIN flow are macOS-only. |

## Notes & limits

- **Service-worker eviction:** the paired session lives in the MV3 worker, which the
  browser may evict; the bridge reconnects, and an evicted pairing surfaces as
  `NotPairedError` so the client can re-pair.
- **Version drift:** the helper path and extension internals can change across releases —
  the daemon reads the native-messaging manifest for the helper path and locates the
  installed extension dynamically rather than hard-coding versions.
- **Headless loading:** the extension is loaded via CDP `Extensions.loadUnpacked`, which
  requires launching the browser with remote debugging + `--enable-unsafe-extension-debugging`.
