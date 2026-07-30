# Security policy

## Reporting a vulnerability

Please report security issues privately rather than in a public issue. Use
GitHub's [private vulnerability reporting](https://github.com/michel-tricot/apwcli/security/advisories/new)
(Security → Report a vulnerability), or email michel.tricot@gmail.com.

Include what you found, how to reproduce it, and the impact you see. We'll
acknowledge within a few days and keep you posted on a fix and disclosure.

## Scope

apwcli reads and writes Apple Passwords entirely on your Mac, through Apple's
local iCloud Passwords helper and the official browser extension. It makes no
network calls of its own and stores no secrets itself. Especially relevant:

- Handling of secrets in output, the clipboard, and logs.
- The daemon's local unix socket and WebSocket bridge (localhost, token-gated).
- The MCP server's default exclusion of plaintext password reads.

How the pairing, encryption, and browser sandboxing work — and the intended
trust boundaries — is documented in [docs/design/apwlib.md](docs/design/apwlib.md).
