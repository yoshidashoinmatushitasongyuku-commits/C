"""運用設定。

ここにある値を書き換えるだけで、フィルター条件・実行間隔・出力先を変更できます。
認証情報はこのファイルに書かず、環境変数（.env）から読み込みます（config.py を参照）。
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# 1. 商品選定（フィルター）条件
#    None にした条件は判定しません。
# ---------------------------------------------------------------------------
FILTER = {
    # リサーチ側の推定利益率（%）の下限
    "min_profit_margin": 25.0,
    # API から取得した星評価の下限（例: 3.8）
    "min_rating": 3.8,
    # API から取得したレビュー数の下限
    "min_review_count": 5,
    # API から取得した現在価格（円）の範囲
    "min_price": 1000,
    "max_price": 10000,
    # 在庫状況。API の offersV2.listings.availability.type の値で指定する
    "allowed_availability": {"IN_STOCK", "IN_STOCK_SCARCE"},
    # 対象カテゴリー（リサーチ側のカテゴリー名）。空集合ならすべて対象
    "categories": set(),
    # 新品の出品者数の上限（SP-API を有効にした場合のみ判定。無効なら None のままにする）
    "max_offer_count": None,
    # 優先スコア（0〜100）の下限
    "min_priority_score": 50.0,
    # True: API で値が取れなかった項目は「条件を満たさない」とみなす（推測で補完しない）
    # False: 値が取れなかった項目はその条件の判定を省略する
    "strict_missing_values": True,
}

# 1回の実行で投稿データを生成する最大件数
MAX_POSTS_PER_RUN = 5

# 優先スコアの重み（合計が1になるようにする）
SCORE_WEIGHTS = {
    "priority": 0.4,       # リサーチの優先順位（1位が最高点）
    "profit_margin": 0.3,  # 推定利益率
    "rating": 0.2,         # 星評価
    "reviews": 0.1,        # レビュー数（多いほど信頼性が高い）
}

# ---------------------------------------------------------------------------
# 2. 定期実行
#    mode: "cron"（指定時刻）または "interval"（一定間隔）
# ---------------------------------------------------------------------------
SCHEDULE = {
    "mode": "cron",
    # 毎朝 9:00（cron の5項目: 分 時 日 月 曜日）
    "cron": "0 9 * * *",
    # mode="interval" のときの間隔（時間）。6 なら6時間ごと
    "interval_hours": 6,
    "timezone": "Asia/Tokyo",
}

# ---------------------------------------------------------------------------
# 3. API 呼び出し
# ---------------------------------------------------------------------------
HTTP_TIMEOUT_SECONDS = 15
MAX_RETRIES = 4                 # 一時的なエラーのリトライ回数
BACKOFF_BASE_SECONDS = 2.0      # 2, 4, 8, 16 秒…と増やす
BACKOFF_MAX_SECONDS = 60.0
# Creators API は1リクエストあたり最大10 ASIN
CREATORS_API_BATCH_SIZE = 10
# リクエスト間の最小間隔（秒）。公式のレート上限はアカウントごとに異なるため、控えめな値を初期値にしている
MIN_REQUEST_INTERVAL_SECONDS = 1.1

# ---------------------------------------------------------------------------
# 4. 入出力
# ---------------------------------------------------------------------------
CANDIDATES_FILE = BASE_DIR / "data" / "candidates.json"
OUTPUT_DIR = BASE_DIR / "output"
LOG_FILE = BASE_DIR / "logs" / "amazon_affiliate.log"
HISTORY_DB = BASE_DIR / "data" / "processed_asins.sqlite3"

# 同じ ASIN を再処理するまでの日数。None なら一度処理した ASIN は二度と処理しない
REPROCESS_AFTER_DAYS = None

# 紹介文に入れるアソシエイトの開示文（アソシエイト・プログラム運営規約で表示が求められている）
ASSOCIATE_DISCLOSURE = "Amazonのアソシエイトとして、当サイトは適格販売により収入を得ています。"

# 生成する投稿データの CTA 文言
CTA_TEXT = "Amazonで詳細を見る"

# WordPress への下書き投稿（任意）。True にすると .env の WP_* を使う
ENABLE_WORDPRESS_DRAFT = False
