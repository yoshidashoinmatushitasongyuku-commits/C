"""Selling Partner API（SP-API）クライアント（任意機能）。

出品者アカウントを持っている場合に限り、Product Pricing API の getItemOffers で
「新品の出品者数」を取得し、競合の多さの判定に使う。

注意:
- SP-API は出品者向けの API で、アソシエイトの紹介コンテンツを作るための API ではない。
  取得したデータは社内のリサーチ（フィルター判定）にだけ使い、投稿データには載せない。
  利用条件は SP-API の利用規約（Acceptable Use Policy・Data Protection Policy）に従うこと。
- 2023年10月以降、SP-API の呼び出しに AWS 署名（SigV4）は不要で、LWA のアクセストークンだけで呼べる。
"""

from __future__ import annotations

import logging
import time

import requests

from .config import SpApiConfig
from .errors import ApiAuthError, ApiResponseError
from .http_client import RateLimiter, parse_json, send, with_retry

logger = logging.getLogger("amazon_affiliate.sp_api")

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
# getItemOffers のレート上限は 0.5 リクエスト/秒
GET_ITEM_OFFERS_INTERVAL_SECONDS = 2.1


class SpApiClient:
    def __init__(self, config: SpApiConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self.rate_limiter = RateLimiter(GET_ITEM_OFFERS_INTERVAL_SECONDS)
        self._token: str | None = None
        self._token_expires_at = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at:
            return self._token
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.config.refresh_token,
            "client_id": self.config.lwa_client_id,
            "client_secret": self.config.lwa_client_secret,
        }
        response = with_retry(lambda: send(self.session, "POST", LWA_TOKEN_URL, "SP-API LWA トークン発行", data=data),
                              "SP-API LWA トークン発行")
        body = parse_json(response, "SP-API LWA トークン発行")
        if not body.get("access_token"):
            raise ApiAuthError("SP-API のトークン発行レスポンスに access_token がありません")
        self._token = body["access_token"]
        self._token_expires_at = time.time() + int(body.get("expires_in", 3600)) - 30
        logger.info("SP-API に接続しました（リージョン %s）", self.config.region)
        return self._token

    def get_offer_count(self, asin: str) -> int | None:
        """新品の出品数（TotalOfferCount）を返す。取得できなければ None。"""
        url = f"{self.config.endpoint}/products/pricing/v0/items/{asin}/offers"
        params = {"MarketplaceId": self.config.marketplace_id, "ItemCondition": "New"}

        def call() -> requests.Response:
            self.rate_limiter.wait()
            headers = {"x-amz-access-token": self._access_token(), "Accept": "application/json"}
            return send(self.session, "GET", url, "SP-API getItemOffers", params=params, headers=headers)

        response = with_retry(call, f"getItemOffers {asin}")
        data = parse_json(response, "SP-API getItemOffers")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise ApiResponseError(f"getItemOffers のレスポンスに payload がありません: {asin}")
        count = (payload.get("Summary") or {}).get("TotalOfferCount")
        return int(count) if isinstance(count, (int, float)) else None
