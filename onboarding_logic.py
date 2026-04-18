from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


class DropboxClient(Protocol):
    def users_get_current_account(self): ...


class DropboxClientFactory(Protocol):
    def from_access_token(self, token: str) -> DropboxClient: ...


@dataclass
class TokenValidationResult:
    ok: bool
    account_display_name: Optional[str] = None
    error_message: Optional[str] = None


def validate_access_token(token: str, factory: DropboxClientFactory) -> TokenValidationResult:
    t = (token or "").strip()
    if not t:
        return TokenValidationResult(ok=False, error_message="Access token is required.")

    try:
        dbx = factory.from_access_token(t)
        acc = dbx.users_get_current_account()
        display_name = getattr(getattr(acc, "name", None), "display_name", None)
        if not display_name:
            display_name = "(unknown account)"
        return TokenValidationResult(ok=True, account_display_name=display_name)
    except Exception as e:
        msg = str(e) or e.__class__.__name__
        return TokenValidationResult(ok=False, error_message=f"Token validation failed: {msg}")
