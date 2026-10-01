"""Amazon Creators API クライアント（PA-API 5.0 の後継）。

PA-API 5.0 は 2026年に廃止され、Amazon アソシエイトの商品情報 API は Creators API に移行した。
- 認証: OAuth2 client_credentials（認証情報のバージョン 2.x は Cognito、3.x は Login with Amazon）
- エンドポイント: POST https://creatorsapi.amazon/catalog/v1/getItems
- ヘッダー: Authorization: Bearer <token>（2.x のみ ", Version 2.x" を付ける）、x-marketplace
- リクエスト・レスポンスのキーは lowerCamelCase
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from . import settings
from .config import CreatorsApiConfig
from .errors import ApiAuthError, ApiResponseError, ItemNotFoundError
from .http_client import RateLimiter, parse_json, send, with_retry
from .models import AmazonItem

logger = logging.getLogger("amazon_affiliate.creators_api")

GET_ITEMS_PATH = "/catalog/v1/getItems"

# 取得するリソース（必要なものだけを指定する）
GET_ITEMS_RESOURCES = [
    "itemInfo.title",
    "itemInfo.byLineInfo",
    "itemInfo.classifications",
    "itemInfo.features",
    "images.primary.large",
    "offersV2.listings.price",
    "offersV2.listings.availability",
    "offersV2.listings.isBuyBoxWinner",
    "customerReviews.count",
    "customerReviews.starRating",
    "browseNodeInfo.browseNodes",
    "browseNodeInfo.browseNodes.salesRank",
]


class CreatorsApiClient:
    def __init__(self, config: CreatorsApiConfig, session: requests.Session | None = None,
                 rate_limiter: RateLimiter | None = None):
        self.config = config
        self.session = session or requests.Session()
        self.rate_limiter = rate_limiter or RateLimiter(settings.MIN_REQUEST_INTERVAL_SECONDS)
        self._token: str | None = None
        self._token_expires_at = 0.0

    # ------------------------------------------------------------------ 認証
    def _fetch_token(self) -> None:
        cfg = self.config
        body = {
            "grant_type": "client_credentials",
            "client_id": cfg.credential_id,
            "client_secret": cfg.credential_secret,
        }
        if cfg.uses_lwa:
            # 3.x（Login with Amazon）は JSON
            body["scope"] = "creatorsapi::default"
            kwargs: dict[str, Any] = {"json": body}
        else:
            # 2.x（Cognito）はフォーム形式
            body["scope"] = "creatorsapi/default"
            kwargs = {"data": body}

        def call() -> requests.Response:
            return send(self.session, "POST", cfg.token_endpoint, "Creators API トークン発行", **kwargs)

        try:
            response = with_retry(call, "Creators API トークン発行")
        except ItemNotFoundError as exc:  # トークンエンドポイントの 404 は設定ミス
            raise ApiAuthError(f"トークンエンドポイントが見つかりません。認証情報のバージョンを確認してください: {exc}") from exc
        data = parse_json(response, "Creators API トークン発行")
        token = data.get("access_token")
        if not token:
            raise ApiAuthError("Creators API のトークン発行レスポンスに access_token がありません")
        self._token = token
        # 期限切れ直前のトークンを使わないよう、30秒の余裕を持たせる
        self._token_expires_at = time.time() + int(data.get("expires_in", 3600)) - 30
        logger.info("Creators API に接続しました（認証情報バージョン %s）", cfg.credential_version)

    def _auth_header(self) -> str:
        if not self._token or time.time() >= self._token_expires_at:
            self._fetch_token()
        if self.config.uses_lwa:
            return f"Bearer {self._token}"
        return f"Bearer {self._token}, Version {self.config.credential_version}"

    # ------------------------------------------------------------------ 商品取得
    def get_items(self, asins: list[str]) -> tuple[dict[str, AmazonItem], dict[str, str]]:
        """ASIN のリストから商品情報を取得する。

        戻り値: (取得できた商品 {ASIN: AmazonItem}, 取得できなかった ASIN {ASIN: 理由})
        """
        found: dict[str, AmazonItem] = {}
        failed: dict[str, str] = {}
        batch_size = settings.CREATORS_API_BATCH_SIZE
        for start in range(0, len(asins), batch_size):
            batch = asins[start:start + batch_size]
            try:
                batch_found, batch_failed = self._get_items_batch(batch)
            except ItemNotFoundError as exc:
                # バッチ内の ASIN がすべて存在しないと 404 になる
                batch_found, batch_failed = {}, {asin: f"ASIN が存在しないか取得できません: {exc}" for asin in batch}
            found.update(batch_found)
            failed.update(batch_failed)
        return found, failed

    def _get_items_batch(self, asins: list[str]) -> tuple[dict[str, AmazonItem], dict[str, str]]:
        payload = {
            "partnerTag": self.config.partner_tag,
            "itemIds": asins,
            "itemIdType": "ASIN",
            "resources": GET_ITEMS_RESOURCES,
        }
        url = self.config.api_base_url + GET_ITEMS_PATH

        def call() -> requests.Response:
            self.rate_limiter.wait()
            headers = {
                "Authorization": self._auth_header(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-marketplace": self.config.marketplace,
            }
            return send(self.session, "POST", url, "Creators API getItems", json=payload, headers=headers)

        try:
            response = with_retry(call, f"getItems {','.join(asins)}")
        except ApiAuthError:
            # トークンが失効していた可能性があるため、1回だけ取り直す。2回目の認証エラーはそのまま送出する
            logger.warning("認証エラーのためトークンを再取得して再試行します")
            self._token = None
            response = with_retry(call, f"getItems {','.join(asins)}")

        data = parse_json(response, "Creators API getItems")
        fetched_at = datetime.now(timezone.utc).isoformat()
        items_result = data.get("itemsResult") or {}
        raw_items = items_result.get("items") or []
        if not isinstance(raw_items, list):
            raise ApiResponseError("getItems の itemsResult.items がリストではありません")

        found: dict[str, AmazonItem] = {}
        for raw in raw_items:
            if not isinstance(raw, dict) or not raw.get("asin"):
                logger.warning("ASIN の無い商品データを無視しました")
                continue
            item = parse_item(raw, fetched_at)
            found[item.asin] = item

        failed: dict[str, str] = {}
        error_messages = [f"{e.get('code')}: {e.get('message')}" for e in data.get("errors") or [] if isinstance(e, dict)]
        for asin in asins:
            if asin not in found:
                # どの ASIN のエラーかはメッセージに含まれることが多いので、該当するものを優先する
                related = [m for m in error_messages if asin in m]
                failed[asin] = "; ".join(related or error_messages) or "レスポンスに商品が含まれていません"
        return found, failed


def _get(data: Any, *path: str | int) -> Any:
    """入れ子の辞書・リストから安全に値を取り出す。途中で欠けていれば None。"""
    for key in path:
        if isinstance(key, int):
            if not isinstance(data, list) or len(data) <= key:
                return None
            data = data[key]
        else:
            if not isinstance(data, dict):
                return None
            data = data.get(key)
    return data


def parse_item(raw: dict[str, Any], fetched_at: str) -> AmazonItem:
    """API のレスポンスを AmazonItem に変換する。無い項目は None のまま（推測しない）。"""
    listings = _get(raw, "offersV2", "listings") or []
    # カート獲得（Buy Box）中の出品を優先し、無ければ先頭を使う
    listing = next((l for l in listings if isinstance(l, dict) and l.get("isBuyBoxWinner")), None)
    if listing is None and listings and isinstance(listings[0], dict):
        listing = listings[0]

    amount = _get(listing, "price", "money", "amount")
    review_count = _get(raw, "customerReviews", "count")
    rating = _get(raw, "customerReviews", "starRating", "value")
    sales_rank = _get(raw, "browseNodeInfo", "browseNodes", 0, "salesRank")
    features = _get(raw, "itemInfo", "features", "displayValues") or []

    return AmazonItem(
        asin=raw["asin"],
        title=_get(raw, "itemInfo", "title", "displayValue"),
        brand=_get(raw, "itemInfo", "byLineInfo", "brand", "displayValue"),
        image_url=_get(raw, "images", "primary", "large", "url"),
        detail_page_url=raw.get("detailPageURL"),
        price=float(amount) if isinstance(amount, (int, float)) else None,
        price_display=_get(listing, "price", "money", "displayAmount"),
        currency=_get(listing, "price", "money", "currency"),
        availability=_get(listing, "availability", "type"),
        availability_message=_get(listing, "availability", "message"),
        rating=float(rating) if isinstance(rating, (int, float)) else None,
        review_count=int(review_count) if isinstance(review_count, (int, float)) else None,
        category=(_get(raw, "itemInfo", "classifications", "productGroup", "displayValue")
                  or _get(raw, "browseNodeInfo", "browseNodes", 0, "displayName")),
        sales_rank=int(sales_rank) if isinstance(sales_rank, (int, float)) else None,
        features=[f for f in features if isinstance(f, str)],
        fetched_at=fetched_at,
    )
