"""Typed views over decrypted entries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_NOT_INCLUDED = "Not Included"


@dataclass
class PasswordEntry:
    username: str
    domain: str
    password: str | None = None
    title: str | None = None
    sites: list[str] = field(default_factory=list)
    high_level_domain: str | None = None

    @classmethod
    def _from_raw(cls, raw: dict[str, Any]) -> PasswordEntry:
        sites = raw.get("sites") or []
        pwd = raw.get("PWD")
        return cls(
            username=raw.get("USR", ""),
            domain=sites[0] if sites else "",
            password=None if pwd in (None, _NOT_INCLUDED) else pwd,
            title=raw.get("customTitle"),
            sites=list(sites),
            high_level_domain=raw.get("highLevelDomain"),
        )


@dataclass
class OTPEntry:
    username: str
    domain: str
    code: str | None = None
    source: str | None = None

    @classmethod
    def _from_raw(cls, raw: dict[str, Any]) -> OTPEntry:
        return cls(
            username=raw.get("username", ""),
            domain=raw.get("domain", ""),
            code=raw.get("code"),
            source=raw.get("source"),
        )
