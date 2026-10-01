"""データ構造の定義。

ResearchCandidate はリサーチ工程で推定した値、AmazonItem は API から取得した値を保持する。
API で取れなかった項目は None のまま残し、推測で埋めない。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ResearchCandidate:
    """別工程（AI・リサーチプログラム）で抽出した商品候補。"""

    asin: str
    name: str
    category: str = ""
    estimated_price: float | None = None        # 推定販売価格（円）
    estimated_profit_margin: float | None = None  # 推定利益率（%）
    reason: str = ""                             # おすすめ理由
    priority: int | None = None                  # 優先順位（1が最優先）


@dataclass
class AmazonItem:
    """Creators API から取得した商品情報。取得できなかった項目は None。"""

    asin: str
    title: str | None = None
    brand: str | None = None
    image_url: str | None = None
    detail_page_url: str | None = None  # API が返すアソシエイトタグ付きURL
    price: float | None = None
    price_display: str | None = None
    currency: str | None = None
    availability: str | None = None
    availability_message: str | None = None
    rating: float | None = None
    review_count: int | None = None
    category: str | None = None
    sales_rank: int | None = None
    features: list[str] = field(default_factory=list)
    fetched_at: str | None = None  # 取得日時（ISO 8601）。価格表示の「時点」に使う
    offer_count: int | None = None  # SP-API で取得した場合のみ入る出品者数


@dataclass
class ScoredProduct:
    candidate: ResearchCandidate
    item: AmazonItem
    score: float


@dataclass
class PostData:
    """アフィリエイト投稿用データ。"""

    asin: str
    title: str
    image_url: str | None
    product_url: str
    affiliate_url: str
    brand: str | None
    price_text: str
    points: list[str]
    description: str
    cta_text: str
    disclosure: str
    category: str
    score: float
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
