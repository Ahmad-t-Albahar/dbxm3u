import keyring
from dataclasses import dataclass
from typing import Optional


@dataclass
class AuthState:
    app_key: Optional[str] = None
    app_secret: Optional[str] = None
    refresh_token: Optional[str] = None
    access_token: Optional[str] = None

    def has_auth(self) -> bool:
        return bool(self.refresh_token) or bool(self.access_token)


class KeyringAuthStore:
    def __init__(self, service_name: str):
        self.service_name = service_name

    def load(self) -> AuthState:
        return AuthState(
            app_key=keyring.get_password(self.service_name, "app_key"),
            app_secret=keyring.get_password(self.service_name, "app_secret"),
            refresh_token=keyring.get_password(self.service_name, "refresh_token"),
            access_token=keyring.get_password(self.service_name, "access_token"),
        )

    def save_access_token(self, token: str) -> None:
        keyring.set_password(self.service_name, "access_token", token)

    def save_app_key_secret(self, app_key: str, app_secret: str) -> None:
        keyring.set_password(self.service_name, "app_key", app_key)
        keyring.set_password(self.service_name, "app_secret", app_secret)

    def save_refresh_token(self, refresh_token: str) -> None:
        keyring.set_password(self.service_name, "refresh_token", refresh_token)

    def wipe_all(self) -> None:
        for k in ["app_key", "app_secret", "refresh_token", "access_token"]:
            try:
                keyring.delete_password(self.service_name, k)
            except Exception:
                pass
