"""商品の選定（フィルター）と優先スコアの計算。条件は settings.FILTER で変更する。"""

from __future__ import annotations

import logging
from typing import Any

from . import settings
from .models import AmazonItem, ResearchCandidate, ScoredProduct

logger = logging.getLogger("amazon_affiliate.selection")


def priority_score(candidate: ResearchCandidate, item: AmazonItem, total_candidates: int) -> float:
    """0〜100 の優先スコア。値が無い項目は 0 点として扱う（推測で加点しない）。"""
    w = settings.SCORE_WEIGHTS
    parts = {
        "priority": 0.0,
        "profit_margin": 0.0,
        "rating": 0.0,
        "reviews": 0.0,
    }
    if candidate.priority and total_candidates > 0:
        # 1位が100点、最下位が 100/total 点
        parts["priority"] = max(0.0, (total_candidates - candidate.priority + 1) / total_candidates * 100)
    if candidate.estimated_profit_margin is not None:
        # 利益率 50% 以上を満点とする
        parts["profit_margin"] = min(candidate.estimated_profit_margin / 50 * 100, 100)
    if item.rating is not None:
        parts["rating"] = item.rating / 5 * 100
    if item.review_count is not None:
        # 100件以上を満点とする
        parts["reviews"] = min(item.review_count / 100 * 100, 100)
    return round(sum(parts[key] * w[key] for key in parts), 1)


def _check(value: Any, ok: bool, label: str, strict: bool) -> str | None:
    """条件を満たさない場合は理由を返す。"""
    if value is None:
        return f"{label}を取得できませんでした" if strict else None
    return None if ok else f"{label}が条件外です（{value}）"


def rejection_reasons(candidate: ResearchCandidate, item: AmazonItem, score: float) -> list[str]:
    f = settings.FILTER
    strict = f["strict_missing_values"]
    reasons: list[str] = []

    def add(reason: str | None) -> None:
        if reason:
            reasons.append(reason)

    if f["min_profit_margin"] is not None:
        m = candidate.estimated_profit_margin
        add(_check(m, m is not None and m >= f["min_profit_margin"], "推定利益率", strict))
    if f["min_rating"] is not None:
        add(_check(item.rating, item.rating is not None and item.rating >= f["min_rating"], "星評価", strict))
    if f["min_review_count"] is not None:
        c = item.review_count
        add(_check(c, c is not None and c >= f["min_review_count"], "レビュー数", strict))
    if f["min_price"] is not None or f["max_price"] is not None:
        p = item.price
        ok = p is not None and (f["min_price"] is None or p >= f["min_price"]) \
            and (f["max_price"] is None or p <= f["max_price"])
        add(_check(p, ok, "現在価格", strict))
    if f["allowed_availability"]:
        a = item.availability
        add(_check(a, a in f["allowed_availability"], "在庫状況", strict))
    if f.get("max_offer_count") is not None:
        o = item.offer_count
        add(_check(o, o is not None and o <= f["max_offer_count"], "出品者数", strict))
    if f["categories"]:
        if candidate.category not in f["categories"]:
            reasons.append(f"カテゴリーが対象外です（{candidate.category or '未設定'}）")
    if f["min_priority_score"] is not None and score < f["min_priority_score"]:
        reasons.append(f"優先スコアが基準未満です（{score}）")
    return reasons


def select_products(pairs: list[tuple[ResearchCandidate, AmazonItem]]) -> list[ScoredProduct]:
    """条件を満たす商品を優先スコアの高い順に返す。"""
    total = len(pairs)
    selected: list[ScoredProduct] = []
    for candidate, item in pairs:
        score = priority_score(candidate, item, total)
        reasons = rejection_reasons(candidate, item, score)
        if reasons:
            logger.info("除外: %s（%s）理由: %s", item.asin, candidate.name, " / ".join(reasons))
            continue
        logger.info("選定: %s（%s）スコア %.1f", item.asin, candidate.name, score)
        selected.append(ScoredProduct(candidate=candidate, item=item, score=score))
    selected.sort(key=lambda p: p.score, reverse=True)
    return selected
