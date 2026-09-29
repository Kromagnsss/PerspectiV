from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .database import session_scope
from .models import User
from .settings import AUTH_DISABLED, OIDC_AUDIENCE, OIDC_ISSUER, OIDC_JWKS_URL


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    full_name: str
    role: str
    scopes: frozenset[str]
    subject: str | None = None

    def has_scope(self, scope: str) -> bool:
        return self.role == "admin" or scope in self.scopes


bearer = HTTPBearer(auto_error=False)


def _token_scopes(claims: dict) -> frozenset[str]:
    raw = claims.get("scope", "")
    scopes = set(raw.split()) if isinstance(raw, str) else set(raw or [])
    scopes.update(claims.get("scp", []) if isinstance(claims.get("scp"), list) else [])
    return frozenset(scopes)


def _decode_token(token: str) -> dict:
    if not OIDC_ISSUER:
        raise HTTPException(status_code=503, detail="OIDC n'est pas configuré.")
    jwks_url = OIDC_JWKS_URL or f"{OIDC_ISSUER}/protocol/openid-connect/certs"
    signing_key = jwt.PyJWKClient(jwks_url).get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=OIDC_AUDIENCE,
        issuer=OIDC_ISSUER,
        options={"require": ["exp", "iat", "sub"]},
    )


def _resolve_user(session: Session, claims: dict) -> User:
    subject = str(claims.get("sub", "")).strip()
    username = str(claims.get("preferred_username", "")).strip().lower()
    email = str(claims.get("email", "")).strip().lower()
    user = session.scalar(select(User).where(User.oidc_subject == subject)) if subject else None
    if not user and (username or email):
        identity_filters = []
        if username:
            identity_filters.append(User.username == username)
        if email:
            identity_filters.append(User.email == email)
        user = session.scalar(select(User).where(or_(*identity_filters)))
        if user and not user.oidc_subject:
            user.oidc_subject = subject
            session.flush()
    if not user or not user.active:
        raise HTTPException(status_code=403, detail="Compte PerspectiV inconnu ou inactif.")
    return user


def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    x_perspectiv_user: Annotated[str | None, Header()] = None,
) -> Principal:
    with session_scope() as session:
        if AUTH_DISABLED:
            username = (x_perspectiv_user or "admin").strip().lower()
            user = session.scalar(select(User).where(User.username == username, User.active.is_(True)))
            if not user:
                raise HTTPException(status_code=401, detail="Utilisateur de développement introuvable.")
            scopes = frozenset({"read", "timesheet:write", "planning:write", "projects:write", "delete", "admin"})
            return Principal(user.id, user.username, user.full_name, user.role, scopes)
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Jeton OAuth requis.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            claims = _decode_token(credentials.credentials)
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="Jeton OAuth invalide.") from exc
        user = _resolve_user(session, claims)
        return Principal(user.id, user.username, user.full_name, user.role, _token_scopes(claims), claims.get("sub"))


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_scope(principal: Principal, scope: str) -> None:
    if not principal.has_scope(scope):
        raise HTTPException(status_code=403, detail=f"Permission requise : {scope}.")


def require_manager(principal: Principal) -> None:
    if principal.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Rôle manager ou administrateur requis.")


def require_admin(principal: Principal) -> None:
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="Rôle administrateur requis.")
