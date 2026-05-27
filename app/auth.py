from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes
from fastapi import HTTPException, Request


@dataclass(frozen=True)
class AuthenticatedUser:
    user_key: str
    subject: str
    tenant_id: str | None = None
    name: str | None = None
    email: str | None = None


_CURRENT_USER: ContextVar[AuthenticatedUser | None] = ContextVar("current_auth_user", default=None)
_OPENID_CONFIG: dict[str, Any] | None = None
_JWKS: dict[str, Any] | None = None


def auth_required() -> bool:
    return os.getenv("AUTH_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}


def get_current_user() -> AuthenticatedUser | None:
    return _CURRENT_USER.get()


def set_current_user(user: AuthenticatedUser | None):
    return _CURRENT_USER.set(user)


def reset_current_user(token) -> None:
    _CURRENT_USER.reset(token)


def scoped_process_id(process_id: str) -> str:
    user = get_current_user()
    if not user:
        return process_id
    return f"{user.user_key}/{process_id}"


def public_process_id(process_id: str) -> str:
    user = get_current_user()
    if user and process_id.startswith(f"{user.user_key}/"):
        return process_id.split("/", 1)[1]
    return process_id


def scope_blob_path(blob_path: str) -> str:
    user = get_current_user()
    if not user or not blob_path.startswith("processes/"):
        return blob_path

    parts = blob_path.split("/")
    if len(parts) >= 3 and parts[1] == user.user_key:
        return blob_path
    if len(parts) >= 3:
        return "/".join(["processes", user.user_key, *parts[1:]])
    return blob_path


def user_processes_prefix() -> str:
    user = get_current_user()
    return f"processes/{user.user_key}/" if user else "processes/"


async def authenticate_request(request: Request) -> AuthenticatedUser | None:
    if not auth_required():
        return None

    header = request.headers.get("authorization") or ""
    scheme, _, header_token = header.partition(" ")
    token = header_token if scheme.lower() == "bearer" else request.query_params.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    claims = await validate_access_token(token.strip())
    return _user_from_claims(claims)


async def validate_access_token(token: str) -> dict[str, Any]:
    header, claims, signing_input, signature = _decode_jwt(token)
    if header.get("alg") != "RS256":
        raise HTTPException(status_code=401, detail="Unsupported token algorithm")

    jwks = await _get_jwks()
    key = next((item for item in jwks.get("keys", []) if item.get("kid") == header.get("kid")), None)
    if not key:
        raise HTTPException(status_code=401, detail="Unknown token signing key")

    public_key = _jwk_to_public_key(key)
    try:
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token signature") from exc

    now = int(time.time())
    if int(claims.get("exp", 0)) <= now:
        raise HTTPException(status_code=401, detail="Token expired")
    if claims.get("nbf") is not None and int(claims["nbf"]) > now + 60:
        raise HTTPException(status_code=401, detail="Token not yet valid")

    _validate_audience(claims)
    _validate_issuer(claims)
    _validate_client(claims)
    _validate_scope(claims)
    return claims


async def _get_openid_config() -> dict[str, Any]:
    global _OPENID_CONFIG
    if _OPENID_CONFIG is None:
        authority = os.getenv("AZURE_AUTH_AUTHORITY", "https://login.microsoftonline.com/common/v2.0").rstrip("/")
        url = f"{authority}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            _OPENID_CONFIG = response.json()
    return _OPENID_CONFIG


async def _get_jwks() -> dict[str, Any]:
    global _JWKS
    if _JWKS is None:
        config = await _get_openid_config()
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(config["jwks_uri"])
            response.raise_for_status()
            _JWKS = response.json()
    return _JWKS


def _decode_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        header = json.loads(_b64url_decode(parts[0]))
        claims = json.loads(_b64url_decode(parts[1]))
        signature = _b64url_decode(parts[2])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token encoding") from exc

    return header, claims, f"{parts[0]}.{parts[1]}".encode("ascii"), signature


def _b64url_decode(value: str) -> bytes:
    padding_len = (-len(value)) % 4
    return base64.urlsafe_b64decode(value + ("=" * padding_len))


def _jwk_to_public_key(jwk: dict[str, Any]):
    n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
    e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
    return rsa.RSAPublicNumbers(e, n).public_key()


def _validate_audience(claims: dict[str, Any]) -> None:
    expected = os.getenv("AZURE_API_AUDIENCE") or os.getenv("AZURE_CLIENT_ID")
    if not expected:
        raise HTTPException(status_code=500, detail="AZURE_API_AUDIENCE is not configured")
    aud = claims.get("aud")
    values = aud if isinstance(aud, list) else [aud]
    accepted = {expected}
    if expected.startswith("api://"):
        accepted.add(expected.removeprefix("api://"))
    else:
        accepted.add(f"api://{expected}")
    if not any(value in accepted for value in values):
        raise HTTPException(status_code=401, detail="Invalid token audience")


def _validate_issuer(claims: dict[str, Any]) -> None:
    issuer = str(claims.get("iss") or "")
    tenant_id = str(claims.get("tid") or "")
    authority = os.getenv("AZURE_AUTH_AUTHORITY", "https://login.microsoftonline.com/common/v2.0").rstrip("/")
    if "/common/" in authority or "/organizations/" in authority or "/consumers/" in authority:
        if tenant_id and issuer == f"https://login.microsoftonline.com/{tenant_id}/v2.0":
            return
        if "/consumers/" in authority and issuer.startswith("https://login.microsoftonline.com/consumers/"):
            return
    elif issuer == authority:
        return
    raise HTTPException(status_code=401, detail="Invalid token issuer")


def _validate_client(claims: dict[str, Any]) -> None:
    allowed = {
        item.strip()
        for item in os.getenv("AZURE_ALLOWED_CLIENT_IDS", "").split(",")
        if item.strip()
    }
    if not allowed:
        return
    client_id = claims.get("azp") or claims.get("appid")
    if client_id not in allowed:
        raise HTTPException(status_code=401, detail="Unauthorized client application")


def _validate_scope(claims: dict[str, Any]) -> None:
    required = os.getenv("AZURE_REQUIRED_SCOPE", "").strip()
    if not required:
        return
    scopes = set(str(claims.get("scp") or "").split())
    if required not in scopes:
        raise HTTPException(status_code=403, detail="Required API scope is missing")


def _user_from_claims(claims: dict[str, Any]) -> AuthenticatedUser:
    tenant_id = claims.get("tid")
    subject = claims.get("oid") or claims.get("sub")
    if not subject:
        raise HTTPException(status_code=401, detail="Token does not identify a user")

    stable_subject = f"{tenant_id or 'msa'}:{subject}"
    user_key = "u_" + hashlib.sha256(stable_subject.encode("utf-8")).hexdigest()[:32]
    return AuthenticatedUser(
        user_key=user_key,
        subject=str(subject),
        tenant_id=str(tenant_id) if tenant_id else None,
        name=claims.get("name"),
        email=claims.get("preferred_username") or claims.get("email"),
    )
