"""コマンドラインの入口。

  python -m amazon_affiliate.main run        # 1回だけ実行
  python -m amazon_affiliate.main schedule   # settings.SCHEDULE に従って定期実行
  python -m amazon_affiliate.main run --candidates data/candidates.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import settings
from .config import load_config
from .errors import AffiliateToolError, ConfigError
from .logging_setup import setup_logging
from .pipeline import run_once

logger = logging.getLogger("amazon_affiliate.main")


def _job() -> None:
    """定期実行の1回分。例外で scheduler が止まらないよう、ここで受け止めてログに残す。"""
    try:
        run_once(load_config())
    except AffiliateToolError as exc:
        logger.error("実行に失敗しました: %s: %s", type(exc).__name__, exc)
    except Exception:  # 想定外のエラーも記録して次回の実行を続ける
        logger.exception("想定外のエラーで実行に失敗しました")


def start_scheduler() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    cfg = settings.SCHEDULE
    scheduler = BlockingScheduler(timezone=cfg["timezone"])
    if cfg["mode"] == "cron":
        trigger = CronTrigger.from_crontab(cfg["cron"], timezone=cfg["timezone"])
        label = f"cron「{cfg['cron']}」"
    elif cfg["mode"] == "interval":
        trigger = IntervalTrigger(hours=cfg["interval_hours"], timezone=cfg["timezone"])
        label = f"{cfg['interval_hours']}時間ごと"
    else:
        raise ConfigError(f"SCHEDULE['mode'] は cron か interval を指定してください: {cfg['mode']}")

    # 前回の実行が長引いても同時に2つ走らないようにする
    scheduler.add_job(_job, trigger, id="amazon_affiliate", max_instances=1, coalesce=True,
                      misfire_grace_time=3600)
    logger.info("定期実行を開始します（%s、タイムゾーン %s）。停止は Ctrl+C", label, cfg["timezone"])
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("定期実行を停止しました")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Amazon アソシエイト運用の半自動化ツール")
    parser.add_argument("command", choices=["run", "schedule"])
    parser.add_argument("--candidates", help="商品候補ファイル（.json / .csv）。省略時は settings.CANDIDATES_FILE")
    args = parser.parse_args(argv)

    setup_logging(settings.LOG_FILE)
    if args.candidates:
        settings.CANDIDATES_FILE = Path(args.candidates)

    if args.command == "schedule":
        start_scheduler()
        return 0
    try:
        run_once(load_config())
    except AffiliateToolError as exc:
        logger.error("実行に失敗しました: %s: %s", type(exc).__name__, exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
