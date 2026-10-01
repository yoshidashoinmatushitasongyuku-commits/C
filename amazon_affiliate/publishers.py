"""投稿データの出力・反映。

Amazon アソシエイトのストアフロントやアイデアリストに商品を追加する公式APIは公開されていない。
そのため、Amazon への最終的な登録は管理画面から手動で行い、このモジュールはそのための
データ（JSON・CSV・手動登録用チェックリスト）を作る。
自分のブログへの反映は、WordPress の公式 REST API で「下書き」として作成できる（任意）。
"""

from __future__ import annotations

import csv
import html
import json
import logging
from datetime import datetime
from pathlib import Path

import requests

from .config import WordPressConfig
from .errors import AffiliateToolError, PublishError
from .http_client import parse_json, send, with_retry
from .models import PostData

logger = logging.getLogger("amazon_affiliate.publishers")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def export_files(posts: list[PostData], output_dir: Path) -> dict[str, Path]:
    """JSON・CSV・手動登録用チェックリスト・HTMLを書き出す。"""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = _timestamp()
        paths = {
            "json": output_dir / f"posts_{stamp}.json",
            "csv": output_dir / f"posts_{stamp}.csv",
            "checklist": output_dir / f"manual_posting_{stamp}.md",
            "html": output_dir / f"posts_{stamp}.html",
        }

        with paths["json"].open("w", encoding="utf-8") as f:
            json.dump([p.to_dict() for p in posts], f, ensure_ascii=False, indent=2)

        with paths["csv"].open("w", encoding="utf-8-sig", newline="") as f:  # Excel で開けるよう BOM 付き
            writer = csv.writer(f)
            writer.writerow(["ASIN", "商品名", "アソシエイトリンク", "画像URL", "価格", "おすすめポイント", "紹介文"])
            for p in posts:
                writer.writerow([p.asin, p.title, p.affiliate_url, p.image_url or "", p.price_text,
                                 " / ".join(p.points), p.description])

        paths["checklist"].write_text(_checklist(posts), encoding="utf-8")
        paths["html"].write_text(_html(posts), encoding="utf-8")
    except OSError as exc:
        raise PublishError(f"投稿データのファイル出力に失敗しました: {exc}") from exc

    for kind, path in paths.items():
        logger.info("投稿データを出力しました（%s）: %s", kind, path)
    return paths


def _checklist(posts: list[PostData]) -> str:
    lines = [
        "# Amazon への手動登録チェックリスト",
        "",
        "ストアフロント・アイデアリストへの追加は公式APIが無いため、管理画面から手動で行ってください。",
        "価格は変動するため、登録・公開の直前に商品ページで確認してください。",
        "",
    ]
    for i, p in enumerate(posts, start=1):
        lines += [
            f"## {i}. {p.title}",
            f"- [ ] ASIN: `{p.asin}`（管理画面の検索欄に貼り付けて商品を追加）",
            f"- [ ] アソシエイトリンク: {p.affiliate_url}",
            f"- [ ] コメント欄に貼る紹介文: {p.points[0] if p.points else '（API で特徴を取得できませんでした）'}",
            f"- 価格: {p.price_text}",
            "",
        ]
    return "\n".join(lines)


def render_post_html(p: PostData) -> str:
    e = html.escape
    image = f'<img src="{e(p.image_url)}" alt="{e(p.title)}" loading="lazy">' if p.image_url else ""
    points = "".join(f"<li>{e(point)}</li>" for point in p.points)
    return (
        f'<div class="amazon-item" data-asin="{e(p.asin)}">\n'
        f"  {image}\n"
        f"  <h3>{e(p.title)}</h3>\n"
        f"  <ul>{points}</ul>\n"
        f"  <p>{e(p.price_text)}</p>\n"
        f'  <p><a href="{e(p.affiliate_url)}" target="_blank" rel="sponsored noopener">{e(p.cta_text)}</a></p>\n'
        f"</div>"
    )


def _html(posts: list[PostData]) -> str:
    disclosure = html.escape(posts[0].disclosure) if posts else ""
    body = "\n".join(render_post_html(p) for p in posts)
    return f'<p class="amazon-disclosure">{disclosure}</p>\n{body}\n'


def create_wordpress_draft(post: PostData, config: WordPressConfig,
                           session: requests.Session | None = None) -> int:
    """WordPress REST API（/wp-json/wp/v2/posts）で下書きを作成し、投稿IDを返す。

    公開はせず下書きにとどめる。価格の確認とアソシエイトの開示文の確認は人が行う。
    """
    session = session or requests.Session()
    payload = {
        "title": post.title,
        "content": f'<p>{html.escape(post.disclosure)}</p>\n{render_post_html(post)}',
        "status": "draft",
    }
    url = f"{config.base_url}/wp-json/wp/v2/posts"
    try:
        response = with_retry(
            lambda: send(session, "POST", url, "WordPress REST API", json=payload,
                         auth=(config.username, config.app_password)),
            f"WordPress 下書き作成 {post.asin}",
        )
        post_id = parse_json(response, "WordPress REST API").get("id")
    except AffiliateToolError as exc:
        raise PublishError(f"{post.asin}: WordPress の下書き作成に失敗しました: {exc}") from exc
    if not isinstance(post_id, int):
        raise PublishError(f"{post.asin}: WordPress のレスポンスに投稿IDがありません")
    logger.info("WordPress に下書きを作成しました: %s（投稿ID %d）", post.asin, post_id)
    return post_id
