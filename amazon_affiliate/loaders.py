"""商品候補を JSON / CSV / Python リストから読み込む。"""

from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable

from .errors import InputFileError
from .models import ResearchCandidate

logger = logging.getLogger("amazon_affiliate.loaders")

ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")

# 入力ファイルの列名の揺れを吸収する（日本語の列名にも対応）
FIELD_ALIASES = {
    "asin": ("asin", "ASIN"),
    "name": ("name", "product_name", "title", "商品名"),
    "category": ("category", "カテゴリー", "カテゴリ"),
    "estimated_price": ("estimated_price", "price", "推定販売価格"),
    "estimated_profit_margin": ("estimated_profit_margin", "profit_margin", "推定利益率"),
    "reason": ("reason", "recommend_reason", "おすすめ理由"),
    "priority": ("priority", "rank", "優先順位"),
}


def _pick(row: dict[str, Any], key: str) -> Any:
    for alias in FIELD_ALIASES[key]:
        if alias in row and row[alias] not in (None, ""):
            return row[alias]
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").replace("円", "").replace("%", "").replace("¥", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return int(number) if number is not None else None


def _parse_rows(rows: Iterable[dict[str, Any]], source: str) -> list[ResearchCandidate]:
    candidates: list[ResearchCandidate] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            logger.warning("%s の %d 件目は辞書形式ではないためスキップしました", source, index)
            continue
        asin = str(_pick(row, "asin") or "").strip().upper()
        name = str(_pick(row, "name") or "").strip()
        if not ASIN_PATTERN.match(asin):
            logger.warning("%s の %d 件目（%s）は ASIN が未設定または不正なためスキップしました: %r",
                           source, index, name or "名称なし", asin)
            continue
        if asin in seen:
            logger.info("%s の ASIN %s が重複しているため、2件目以降をスキップしました", source, asin)
            continue
        seen.add(asin)
        candidates.append(ResearchCandidate(
            asin=asin,
            name=name,
            category=str(_pick(row, "category") or "").strip(),
            estimated_price=_to_float(_pick(row, "estimated_price")),
            estimated_profit_margin=_to_float(_pick(row, "estimated_profit_margin")),
            reason=str(_pick(row, "reason") or "").strip(),
            priority=_to_int(_pick(row, "priority")),
        ))
    logger.info("%s から商品候補を %d 件読み込みました", source, len(candidates))
    return candidates


def load_from_list(rows: list[dict[str, Any]]) -> list[ResearchCandidate]:
    """Python のリスト（辞書のリスト）から読み込む。"""
    return _parse_rows(rows, "Pythonリスト")


def load_candidates(path: str | Path) -> list[ResearchCandidate]:
    """拡張子（.json / .csv）で形式を判定して読み込む。"""
    path = Path(path)
    if not path.exists():
        raise InputFileError(f"商品候補ファイルが見つかりません: {path}")
    try:
        if path.suffix.lower() == ".json":
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            # {"candidates": [...]} と [...] の両方を受け付ける
            if isinstance(data, dict):
                data = data.get("candidates")
            if not isinstance(data, list):
                raise InputFileError(f"JSON の形式が不正です（リスト、または candidates キーが必要）: {path}")
            return _parse_rows(data, path.name)
        if path.suffix.lower() == ".csv":
            # Excel で保存した BOM 付き CSV にも対応する
            with path.open(encoding="utf-8-sig", newline="") as f:
                return _parse_rows(list(csv.DictReader(f)), path.name)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
        raise InputFileError(f"商品候補ファイルを読み込めませんでした: {path}: {exc}") from exc
    raise InputFileError(f"対応していないファイル形式です（.json / .csv のみ）: {path}")
