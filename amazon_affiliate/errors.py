"""このツールで扱う例外の定義。"""


class AffiliateToolError(Exception):
    """このツールの例外の基底クラス。"""


class ConfigError(AffiliateToolError):
    """環境変数・設定の不備。"""


class InputFileError(AffiliateToolError):
    """商品候補ファイルの読み込み・形式エラー。"""


class ApiAuthError(AffiliateToolError):
    """API 認証エラー（401/403、トークン取得失敗）。リトライしない。"""


class ApiRateLimitError(AffiliateToolError):
    """レート制限（429）。リトライ対象。"""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ApiTimeoutError(AffiliateToolError):
    """タイムアウト。リトライ対象。"""


class ApiNetworkError(AffiliateToolError):
    """接続エラーなどのネットワーク障害。リトライ対象。"""


class ApiServerError(AffiliateToolError):
    """5xx などの一時的なサーバーエラー。リトライ対象。"""


class ApiResponseError(AffiliateToolError):
    """レスポンスの形式が想定外、または 4xx のリクエストエラー。リトライしない。"""


class ItemNotFoundError(AffiliateToolError):
    """ASIN が存在しない、または API から取得できない。"""


class PublishError(AffiliateToolError):
    """投稿データの生成・保存・投稿の失敗。"""


# リトライしてよい（一時的な）エラー
RETRYABLE_ERRORS = (ApiRateLimitError, ApiTimeoutError, ApiNetworkError, ApiServerError)
