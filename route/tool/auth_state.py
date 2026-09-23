from __future__ import annotations

import time
from typing import Literal, Protocol, TypeAlias


AuthPurpose: TypeAlias = Literal["login_riro", "login_2fa", "register_riro", "register_verified"]
SessionValue: TypeAlias = str | int | bool | None | dict[str, str | int | None]
AUTH_PENDING_TTL = 600
LOGIN_STATE_KEYS = ("login_id", "b_id", "pending_riro_verification_for_user")
REGISTRATION_PROOF_KEYS = ("riro_verified", "riro_name", "riro_student_number", "riro_generation")
LOGOUT_STATE_KEYS = (
    "state", "id", "user_name", "login_id", "b_id", "pending_riro_verification_for_user",
    "auto_login_checked", "auth_pending", "riro_verified", "riro_name", "riro_student_number",
    "riro_generation", "c_id", "c_pw", "c_ans", "c_que", "c_key", "c_type", "c_email",
)


class SessionState(Protocol):
    def get(self, key: str, default: SessionValue = None) -> SessionValue: ...
    def __setitem__(self, key: str, value: SessionValue) -> None: ...
    def pop(self, key: str, default: SessionValue = None) -> SessionValue: ...


def set_auth_pending(
    session: SessionState,
    purpose: AuthPurpose,
    account_id: str | None,
    issued_at: int | None = None,
) -> None:
    session["auth_pending"] = {
        "purpose": purpose,
        "account_id": account_id,
        "issued_at": int(time.time()) if issued_at is None else issued_at,
    }


def get_auth_pending(session: SessionState, now: int | None = None) -> dict[str, str | int | None] | None:
    pending = session.get("auth_pending")
    if not isinstance(pending, dict):
        return None
    purpose = pending.get("purpose")
    account_id = pending.get("account_id")
    issued_at = pending.get("issued_at")
    if purpose not in ("login_riro", "login_2fa", "register_riro", "register_verified"):
        return None
    if account_id is not None and not isinstance(account_id, str):
        return None
    if not isinstance(issued_at, int) or isinstance(issued_at, bool):
        return None
    current = int(time.time()) if now is None else now
    if issued_at > current or current - issued_at > AUTH_PENDING_TTL:
        return None
    return pending


def auth_pending_matches(
    session: SessionState,
    purpose: AuthPurpose,
    account_id: str | None,
    now: int | None = None,
) -> bool:
    pending = get_auth_pending(session, now)
    return pending is not None and pending.get("purpose") == purpose and pending.get("account_id") == account_id


def _clear(session: SessionState, keys: tuple[str, ...]) -> None:
    for key in keys:
        session.pop(key, None)


def clear_login_state(session: SessionState) -> None:
    _clear(session, LOGIN_STATE_KEYS)
    session.pop("auth_pending", None)


def clear_registration_state(session: SessionState) -> None:
    _clear(session, REGISTRATION_PROOF_KEYS)
    session.pop("auth_pending", None)


def clear_auth_transients(session: SessionState) -> None:
    _clear(session, LOGIN_STATE_KEYS + REGISTRATION_PROOF_KEYS)
    session.pop("auth_pending", None)


def clear_logout_state(session: SessionState) -> None:
    _clear(session, LOGOUT_STATE_KEYS)
