from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

from .settings import settings

STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _parse_origin(origin: str) -> str | None:
    try:
        parsed = urlparse(origin)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    return f"{parsed.scheme}://{parsed.netloc.lower()}"


def _expected_origins(request: Request) -> set[str]:
    if settings.trusted_origins:
        return {item.lower().rstrip("/") for item in settings.trusted_origins}
    host = request.headers.get("host", "")
    scheme = request.url.scheme
    return {f"{scheme}://{host.lower()}"} if host else set()


async def origin_guard(request: Request, call_next) -> JSONResponse:
    """Cookie 会话的 CSRF 防线：状态变更请求的 Origin/Referer 必须同源。

    没有 Origin/Referer 的请求（脚本、curl、同源旧浏览器）不拒绝，
    由反向代理限流与 SameSite Cookie 共同兜底。
    """
    if request.method in STATE_CHANGING_METHODS:
        declared = request.headers.get("origin") or request.headers.get("referer")
        if declared:
            parsed = _parse_origin(declared)
            if parsed is None or parsed not in _expected_origins(request):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "请求来源与平台不一致，已拒绝。"},
                )
    return await call_next(request)
