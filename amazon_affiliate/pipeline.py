"""1回分の処理: 読み込み → 重複除外 → API取得 → 選定 → 投稿データ生成 → 出力 → 履歴保存。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import settings
from .config import AppConfig
from .content import build_post
from .creators_api import CreatorsApiClient
from .errors import AffiliateToolError, PublishError
from .history import ProcessedHistory
from .loaders import load_candidates
from .models import PostData, ResearchCandidate
from .publishers import create_wordpress_draft, export_files
from .selection import select_products
from .sp_api import SpApiClient

logger = logging.getLogger("amazon_affiliate.pipeline")


@dataclass
class RunResult:
    loaded: int = 0
    skipped_duplicates: int = 0
    fetched: int = 0
    fetch_failed: int = 0
    selected: int = 0
    posts: list[PostData] = field(default_factory=list)
    output_files: dict[str, Path] = field(default_factory=dict)


def run_once(config: AppConfig, candidates: list[ResearchCandidate] | None = None,
             creators_client: CreatorsApiClient | None = None,
             sp_client: SpApiClient | None = None,
             history: ProcessedHistory | None = None) -> RunResult:
    logger.info("===== 実行開始 =====")
    result = RunResult()
    own_history = history is None
    history = history or ProcessedHistory(settings.HISTORY_DB)
    try:
        if candidates is None:
            candidates = load_candidates(settings.CANDIDATES_FILE)
        result.loaded = len(candidates)

        # 重複投稿防止: 処理済みの ASIN は API を呼ぶ前に除外する
        pending = []
        for c in candidates:
            if history.is_processed(c.asin, settings.REPROCESS_AFTER_DAYS):
                logger.info("処理済みのためスキップ: %s（%s）", c.asin, c.name)
                result.skipped_duplicates += 1
            else:
                pending.append(c)
        if not pending:
            logger.info("新しく処理する商品はありません")
            return result

        creators_client = creators_client or CreatorsApiClient(config.creators)
        found, failed = creators_client.get_items([c.asin for c in pending])
        for asin, reason in failed.items():
            logger.warning("商品取得失敗: %s 理由: %s", asin, reason)
        for asin, item in found.items():
            logger.info("商品取得成功: %s %s 価格=%s 在庫=%s", asin, item.title, item.price_display, item.availability)
        result.fetched, result.fetch_failed = len(found), len(failed)

        if config.sp_api is not None:
            sp_client = sp_client or SpApiClient(config.sp_api)
            for asin, item in found.items():
                try:
                    item.offer_count = sp_client.get_offer_count(asin)
                except AffiliateToolError as exc:
                    # 出品者数が取れなくても処理は続ける（値は None のまま）
                    logger.warning("SP-API で出品者数を取得できませんでした: %s: %s", asin, exc)

        pairs = [(c, found[c.asin]) for c in pending if c.asin in found]
        selected = select_products(pairs)[:settings.MAX_POSTS_PER_RUN]
        result.selected = len(selected)
        logger.info("商品選定: %d 件中 %d 件を選定しました", len(pairs), len(selected))

        for product in selected:
            try:
                result.posts.append(build_post(product, config.creators))
                logger.info("投稿データ生成: %s", product.item.asin)
            except PublishError as exc:
                logger.error("投稿データ生成失敗: %s", exc)

        if not result.posts:
            logger.info("出力する投稿データはありません")
            return result

        result.output_files = export_files(result.posts, settings.OUTPUT_DIR)

        if settings.ENABLE_WORDPRESS_DRAFT:
            if config.wordpress is None:
                logger.error("ENABLE_WORDPRESS_DRAFT=True ですが WP_* の環境変数が未設定です")
            else:
                for post in result.posts:
                    try:
                        create_wordpress_draft(post, config.wordpress)
                    except PublishError as exc:
                        logger.error("%s", exc)

        # ファイル出力に成功した商品だけを処理済みにする
        for post in result.posts:
            history.mark_processed(post.asin, post.title, str(result.output_files["json"]))
        return result
    finally:
        if own_history:
            history.close()
        logger.info("===== 処理完了: 読込 %d / 重複除外 %d / 取得成功 %d / 取得失敗 %d / 選定 %d / 生成 %d =====",
                    result.loaded, result.skipped_duplicates, result.fetched, result.fetch_failed,
                    result.selected, len(result.posts))
