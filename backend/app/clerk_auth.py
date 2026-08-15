from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient, PyJWTError

from .settings import settings


class ClerkTokenError(ValueError):
    pass


@dataclass(frozen=True)
class ClerkIdentity:
    user_id: str
    organization_id: str = ""
    authorized_party: str = ""


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True)


def _organization_id(claims: dict[str, Any]) -> str:
    direct = claims.get("org_id")
    if isinstance(direct, str):
        return direct
    organization = claims.get("o")
    if isinstance(organization, dict) and isinstance(organization.get("id"), str):
        return organization["id"]
    return ""


def _decode_clerk_token(token: str) -> dict[str, Any]:
    if not settings.clerk_issuer:
        raise ClerkTokenError("服务端尚未配置 Clerk issuer。")
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise ClerkTokenError("Clerk Token 签名算法不受支持。")
        key: Any
        if settings.clerk_jwt_key:
            key = settings.clerk_jwt_key
        else:
            jwks_url = settings.clerk_jwks_url or (f"{settings.clerk_issuer}/.well-known/jwks.json")
            key = _jwks_client(jwks_url).get_signing_key_from_jwt(token).key
        options = {"require": ["exp", "iat", "nbf", "iss", "sub"]}
        if not settings.clerk_audience:
            options["verify_aud"] = False
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            audience=settings.clerk_audience or None,
            options=options,
            leeway=settings.clerk_jwt_leeway_seconds,
        )
    except ClerkTokenError:
        raise
    except (PyJWTError, OSError, ValueError) as exc:
        raise ClerkTokenError("Clerk Token 无效或已经过期。") from exc


def verify_clerk_token(token: str) -> ClerkIdentity:
    if not token:
        raise ClerkTokenError("缺少 Clerk Token。")
    claims = _decode_clerk_token(token)
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise ClerkTokenError("Clerk Token 缺少用户标识。")
    authorized_party = claims.get("azp")
    if not isinstance(authorized_party, str):
        authorized_party = ""
    if (
        settings.clerk_authorized_parties
        and authorized_party not in settings.clerk_authorized_parties
    ):
        raise ClerkTokenError("Clerk Token 来源不在允许列表中。")
    return ClerkIdentity(
        user_id=subject,
        organization_id=_organization_id(claims),
        authorized_party=authorized_party,
    )
