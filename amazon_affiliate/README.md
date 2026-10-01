# Amazon アソシエイト運用 半自動化ツール

リサーチ工程で抽出した「穴場商品」の候補をもとに、次の流れを自動で行います。

商品情報の取得 → 商品の選定 → 投稿データの生成 → ファイル出力（必要ならブログに下書き作成）→ ログ保存 → 定期実行

Amazon のストアフロントやアイデアリストへの最終的な登録だけは手動です（理由は下記）。

---

## 1. 最初に知っておくべき前提（2026年10月時点）

### PA-API 5.0 は廃止され、Creators API に移行済み
- Product Advertising API 5.0 は **2026年4月30日に非推奨、5月15日に廃止**されました。現在 PA-API を呼ぶと `403 AccessDeniedException` が返ります。
- 後継は **Amazon Creators API** です。このツールは Creators API を使っています。
- 旧 PA-API のアクセスキー・シークレットキー（AWS 形式）は使えません。アソシエイト・セントラルで Creators API 用の認証情報（Credential ID / Secret / Version）を新しく発行してください。
- 利用には、アソシエイトアカウントが承認済みで、**直近に一定の売上実績があること**が条件です（「30日以内に10件の売上」と紹介されることが多いですが、最新の条件はアソシエイト・セントラルで確認してください）。

| 項目 | Creators API の仕様（このツールの実装） |
|---|---|
| 認証 | OAuth2 client_credentials。バージョン 3.x は Login with Amazon、2.x は Cognito |
| 日本のトークン発行先 | 3.3: `https://api.amazon.co.jp/auth/o2/token` ／ 2.3: `https://creatorsapi.auth.us-west-2.amazoncognito.com/oauth2/token` |
| 商品取得 | `POST https://creatorsapi.amazon/catalog/v1/getItems`（1回に最大10 ASIN） |
| ヘッダー | `Authorization: Bearer <token>`（2.x のみ `, Version 2.x` を付ける）、`x-marketplace: www.amazon.co.jp` |
| キーの書き方 | lowerCamelCase（例: `itemInfo.title`、`offersV2.listings.price`） |

### ストアフロント・アイデアリストに投稿する公式 API はない
- Amazon アソシエイト（インフルエンサープログラムを含む）のストアフロント・アイデアリスト・紹介ページに、**商品を追加・投稿する公開 API は提供されていません**。
- そのため、このツールにはこれらへ投稿する処理を**実装していません**。存在しない API を呼ぶ処理や、中身のない投稿関数も作っていません。
- 管理画面を操作するブラウザ自動化（Selenium など）やスクレイピングは、規約違反でアカウントを停止されるおそれがあるため採用していません。

---

## 2. どこまで自動化できるか

| 工程 | 自動 / 手動 | 使う仕組み |
|---|---|---|
| 商品候補の読み込み（JSON / CSV / Python リスト） | 自動 | `loaders.py` |
| 処理済み ASIN の除外（重複投稿の防止） | 自動 | SQLite（`history.py`） |
| 商品名・画像・価格・ブランド・カテゴリー・在庫・評価の取得 | 自動 | Creators API `getItems` |
| アソシエイトリンクの取得 | 自動 | API が返す `detailPageURL`（トラッキングID付き） |
| 出品者数の取得（任意） | 自動 | SP-API `getItemOffers`（出品者アカウントがある場合のみ） |
| 条件による選定・優先スコアの計算 | 自動 | `selection.py`（条件は `settings.py` で変更） |
| 紹介文・おすすめポイント・CTA の生成 | 自動 | `content.py` |
| JSON・CSV・HTML・手動登録用チェックリストの出力 | 自動 | `publishers.py` |
| 自分の WordPress ブログに下書きを作成（任意） | 自動 | WordPress 公式 REST API |
| ログの保存・定期実行 | 自動 | logging ／ APScheduler |
| **ストアフロント・アイデアリストへの登録** | **手動** | 出力された `manual_posting_*.md` を見ながら管理画面で登録 |
| **ブログ下書きの最終確認と公開** | **手動** | 価格・開示文を確認してから公開 |

**手動登録の手順（1商品あたり1〜2分の目安）**
1. 出力された `output/manual_posting_*.md` を開く
2. アソシエイト・セントラル（またはインフルエンサーのストアフロント）の管理画面で、ASIN を検索して商品を追加する
3. チェックリストの紹介文をコメント欄に貼り付ける
4. チェックボックスに印を付ける

**代わりに使える現実的な方法**
- **自分のブログ（WordPress）**: 公式 REST API で下書きまで自動化できます（`ENABLE_WORDPRESS_DRAFT = True`）。
- **SNS やメルマガ**: 出力した JSON・CSV を、各サービスの公式 API や予約投稿機能に渡します。
- **Amazon 側への登録**: 上記の手動登録だけにして、作業はチェックリストで最小限にします。

---

## 3. セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env   # 認証情報を記入する（.env は .gitignore 済み）
```

`.env` の主な項目（詳細は `.env.example`）:

| 環境変数 | 内容 |
|---|---|
| `AMAZON_CREATORS_CREDENTIAL_ID` / `AMAZON_CREATORS_CREDENTIAL_SECRET` | Creators API の認証情報（旧 PA-API の Access Key / Secret Key に相当） |
| `AMAZON_CREATORS_CREDENTIAL_VERSION` | 認証情報のバージョン（日本は `3.3` または `2.3`） |
| `AMAZON_PARTNER_TAG` | トラッキングID（例: `yourtag-22`） |
| `AMAZON_MARKETPLACE` | `www.amazon.co.jp` |
| `SP_API_*` | SP-API の認証情報（任意。LWA クライアントID・シークレット・リフレッシュトークン） |
| `WP_*` | WordPress の URL・ユーザー名・アプリケーションパスワード（任意） |

---

## 4. 商品候補の入力形式

`data/candidates.json`（またはCSV）に、リサーチ結果を入れます。列名は英語・日本語のどちらでも読み込めます。

```json
{"candidates": [
  {"asin": "B0XXXXXXXX", "name": "商品名", "category": "介護用品",
   "estimated_price": 2480, "estimated_profit_margin": 41.4,
   "reason": "おすすめ理由", "priority": 1}
]}
```

| 項目 | JSON のキー | CSV の列名（日本語も可） |
|---|---|---|
| ASIN | `asin` | `ASIN` |
| 商品名 | `name` | `商品名` |
| カテゴリー | `category` | `カテゴリー` |
| 推定販売価格 | `estimated_price` | `推定販売価格` |
| 推定利益率 | `estimated_profit_margin` | `推定利益率` |
| おすすめ理由 | `reason` | `おすすめ理由` |
| 優先順位 | `priority` | `優先順位` |

- **ASIN が空欄または形式が不正な候補は、読み込み時にスキップされます。** 同梱のサンプルは ASIN が空欄なので、Amazon で実在を確認した ASIN を入れてください。
- Python から直接渡す場合は、`loaders.load_from_list([...])` で読み込み、その結果を `pipeline.run_once(config, candidates)` に渡します。

---

## 5. 実行方法

```bash
python -m amazon_affiliate.main run                                  # 1回だけ実行
python -m amazon_affiliate.main run --candidates data/my.csv         # 入力ファイルを指定
python -m amazon_affiliate.main schedule                             # 定期実行
```

定期実行の間隔は `settings.py` の `SCHEDULE` で変更します。

```python
SCHEDULE = {"mode": "cron", "cron": "0 9 * * *"}       # 毎朝 9:00
SCHEDULE = {"mode": "cron", "cron": "0 0 * * *"}       # 毎日1回（0:00）
SCHEDULE = {"mode": "interval", "interval_hours": 6}   # 6時間ごと
```

- `schedule` はプロセスが起動している間だけ動きます。サーバーで常に動かす場合は、systemd や Docker で常駐させてください。
- 常駐させない場合は、OS の cron から `run` を呼ぶ方法でも構いません。

---

## 6. 選定条件の変更

`settings.py` の `FILTER` を書き換えます。

| 設定 | 内容 |
|---|---|
| `min_profit_margin` | 推定利益率の下限（%） |
| `min_rating` | 星評価の下限 |
| `min_review_count` | レビュー数の下限 |
| `min_price` / `max_price` | 価格帯 |
| `allowed_availability` | 在庫状況 |
| `categories` | 対象カテゴリー |
| `max_offer_count` | 出品者数の上限（SP-API を使う場合のみ） |
| `min_priority_score` | 優先スコアの下限 |
| `strict_missing_values` | `True`（初期値）にすると、API で取れなかった値は「条件を満たさない」として扱います（推測で補完しないため） |

---

## 7. 出力ファイル

| 出力先 | 内容 |
|---|---|
| `output/posts_*.json` | 投稿データ（商品名、画像URL、商品URL、アソシエイトリンク、おすすめポイント、紹介文、CTA、開示文） |
| `output/posts_*.csv` | 同じ内容を Excel で開ける形式で |
| `output/posts_*.html` | ブログに貼り付けられる HTML（リンクは `rel="sponsored"` 付き） |
| `output/manual_posting_*.md` | Amazon の管理画面で手動登録するためのチェックリスト |
| `logs/amazon_affiliate.log` | 実行ログ（5MB でローテーション、5世代保存） |
| `data/processed_asins.sqlite3` | 処理済み ASIN の履歴。`REPROCESS_AFTER_DAYS` で再処理までの日数を設定（`None` なら再処理しない） |

---

## 8. 規約上の注意（実装に反映済み）

- **価格には取得日時を併記**し、「最新の価格は Amazon で確認」と添えています。価格を表示する場合は、定期実行で24時間以内に更新することを推奨します。
- **アソシエイトの開示文**（「Amazonのアソシエイトとして…」）を投稿データに入れています。
- **星評価・レビュー数は選定にだけ使い、紹介文には載せていません。**
- **SP-API のデータは出品者向けの用途に限られます。** このツールでは選定の判定にだけ使い、投稿データには載せません。
- **API で取得できなかった項目は空のまま**にし、推測で補完しません。商品名が取れなかった商品は投稿データを作りません。

## 9. テスト

```bash
python -m unittest discover tests
```

API はモックで置き換えているため、認証情報が無くても実行できます。
