"""アフィリエイト用の投稿データを生成する。

方針:
- 商品名・画像・価格・特徴は API から取得した値だけを使い、取得できなかった項目は書かない。
- 価格は変動するため、取得日時を「時点」として必ず併記する。
- 星評価・レビュー数は選定にだけ使い、紹介文には載せない（規約上の扱いが変わりやすいため）。
- リサーチ側の推定利益率などの社内データは投稿に載せない。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from . import settings
from .config import CreatorsApiConfig
from .errors import PublishError
from .models import PostData, ScoredProduct

logger = logging.getLogger("amazon_affiliate.content")

JST = timezone(timedelta(hours=9))
MAX_POINTS = 3


def _format_time(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).astimezone(JST).strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return ""


def _price_text(product: ScoredProduct) -> str:
    item = product.item
    if item.price is None and not item.price_display:
        return "価格はAmazonの商品ページでご確認ください"
    price = item.price_display or f"¥{item.price:,.0f}"
    at = _format_time(item.fetched_at)
    return f"{price}（{at} 時点の価格。最新の価格はAmazonでご確認ください）" if at else price


def build_post(product: ScoredProduct, api_config: CreatorsApiConfig) -> PostData:
    item, candidate = product.item, product.candidate
    title = item.title
    if not title:
        raise PublishError(f"{item.asin}: 商品名を API から取得できなかったため投稿データを作れません")

    product_url = f"https://{api_config.marketplace}/dp/{quote(item.asin)}"
    if item.detail_page_url:
        affiliate_url = item.detail_page_url  # API が返すトラッキングID付きのURL
    else:
        # Amazon 標準のリンク形式（/dp/ASIN?tag=トラッキングID）で作成する
        affiliate_url = f"{product_url}?tag={quote(api_config.partner_tag)}"
        logger.info("%s: API に detailPageURL が無いため、標準形式でアソシエイトリンクを作成しました", item.asin)

    points = item.features[:MAX_POINTS]
    if candidate.reason:
        points = [candidate.reason] + points[:MAX_POINTS - 1]

    lines = [f"{title}をご紹介します。"]
    if item.brand:
        lines.append(f"ブランド：{item.brand}")
    if candidate.reason:
        lines.append(f"おすすめの理由：{candidate.reason}")
    if item.features:
        lines.append("主な特徴：")
        lines.extend(f"・{feature}" for feature in item.features[:MAX_POINTS])
    lines.append(f"価格：{_price_text(product)}")
    description = "\n".join(lines)

    return PostData(
        asin=item.asin,
        title=title,
        image_url=item.image_url,
        product_url=product_url,
        affiliate_url=affiliate_url,
        brand=item.brand,
        price_text=_price_text(product),
        points=points,
        description=description,
        cta_text=settings.CTA_TEXT,
        disclosure=settings.ASSOCIATE_DISCLOSURE,
        category=item.category or candidate.category,
        score=product.score,
        generated_at=datetime.now(JST).isoformat(timespec="seconds"),
    )
