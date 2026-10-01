"""HTTP 通信の共通処理。エラーの分類と指数バックオフによるリトライを担当する。"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, TypeVar

import requests

from . import settings
from .errors import (
    RETRYABLE_ERRORS,
    ApiAuthError,
    ApiNetworkError,
    ApiRateLimitError,
    ApiResponseError,
    ApiServerError,
    ApiTimeoutError,
    ItemNotFoundError,
)

logger = logging.getLogger("amazon_affiliate.http")

T = TypeVar("T")


def _retry_after_seconds(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _body_excerpt(response: requests.Response, limit: int = 300) -> str:
    return (response.text or "")[:limit]


def raise_for_response(response: requests.Response, api_name: str) -> None:
    """HTTP ステータスに応じて、このツールの例外に変換する。"""
    status = response.status_code
    if 200 <= status < 300:
        return
    detail = f"{api_name} HTTP {status}: {_body_excerpt(response)}"
    if status in (401, 403):
        raise ApiAuthError(detail)
    if status == 404:
        raise ItemNotFoundError(detail)
    if status == 429:
        raise ApiRateLimitError(detail, retry_after=_retry_after_seconds(response))
    if status >= 500:
        raise ApiServerError(detail)
    raise ApiResponseError(detail)


def send(session: requests.Session, method: str, url: str, api_name: str, **kwargs: Any) -> requests.Response:
    """リクエストを1回送り、通信エラーを分類して返す。"""
    try:
        response = session.request(method, url, timeout=settings.HTTP_TIMEOUT_SECONDS, **kwargs)
    except requests.Timeout as exc:
        raise ApiTimeoutError(f"{api_name} がタイムアウトしました: {exc}") from exc
    except requests.ConnectionError as exc:
        raise ApiNetworkError(f"{api_name} に接続できませんでした: {exc}") from exc
    except requests.RequestException as exc:
        raise ApiNetworkError(f"{api_name} の通信に失敗しました: {exc}") from exc
    raise_for_response(response, api_name)
    return response


def parse_json(response: requests.Response, api_name: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise ApiResponseError(f"{api_name} のレスポンスが JSON ではありません: {_body_excerpt(response)}") from exc
    if not isinstance(data, dict):
        raise ApiResponseError(f"{api_name} のレスポンス形式が想定外です: {type(data).__name__}")
    return data


def with_retry(func: Callable[[], T], description: str,
               sleep: Callable[[float], None] = time.sleep) -> T:
    """一時的なエラー（429・5xx・タイムアウト・通信断）のときだけ指数バックオフでリトライする。"""
    attempt = 0
    while True:
        try:
            return func()
        except RETRYABLE_ERRORS as exc:
            attempt += 1
            if attempt > settings.MAX_RETRIES:
                logger.error("%s: リトライ上限（%d回）に達しました: %s", description, settings.MAX_RETRIES, exc)
                raise
            delay = min(settings.BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)), settings.BACKOFF_MAX_SECONDS)
            if isinstance(exc, ApiRateLimitError) and exc.retry_after:
                delay = max(delay, exc.retry_after)
            delay += random.uniform(0, delay * 0.1)  # 同時リトライの集中を避ける
            logger.warning("%s: 一時的なエラーのため %.1f 秒後にリトライします（%d/%d回目）: %s",
                           description, delay, attempt, settings.MAX_RETRIES, exc)
            sleep(delay)


class RateLimiter:
    """リクエスト間の最小間隔を守る。"""

    def __init__(self, min_interval: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self.min_interval - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()
