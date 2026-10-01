"""認証情報を環境変数から読み込む。

コードに認証情報を書かないため、値はすべて環境変数（または .env ファイル）から取得する。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import ConfigError

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv が無くても環境変数だけで動かせるようにする
    load_dotenv = None

# Creators API の認証情報バージョンごとのトークン発行エンドポイント
# （2.x は Amazon Cognito、3.x は Login with Amazon。日本は Far East の 2.3 / 3.3）
CREATORS_TOKEN_ENDPOINTS = {
    "2.1": "https://creatorsapi.auth.us-east-1.amazoncognito.com/oauth2/token",
    "2.2": "https://creatorsapi.auth.eu-south-2.amazoncognito.com/oauth2/token",
    "2.3": "https://creatorsapi.auth.us-west-2.amazoncognito.com/oauth2/token",
    "3.1": "https://api.amazon.com/auth/o2/token",
    "3.2": "https://api.amazon.co.uk/auth/o2/token",
    "3.3": "https://api.amazon.co.jp/auth/o2/token",
}

# SP-API のリージョン別エンドポイントとマーケットプレイスID
SP_API_ENDPOINTS = {
    "na": "https://sellingpartnerapi-na.amazon.com",
    "eu": "https://sellingpartnerapi-eu.amazon.com",
    "fe": "https://sellingpartnerapi-fe.amazon.com",
}
MARKETPLACE_IDS = {
    "www.amazon.co.jp": "A1VC38T7YXB528",
    "www.amazon.com": "ATVPDKIKX0DER",
    "www.amazon.co.uk": "A1F83G8C2ARO7P",
}


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else value


@dataclass(frozen=True)
class CreatorsApiConfig:
    credential_id: str
    credential_secret: str
    credential_version: str
    partner_tag: str
    marketplace: str
    api_base_url: str = "https://creatorsapi.amazon"

    @property
    def token_endpoint(self) -> str:
        return CREATORS_TOKEN_ENDPOINTS[self.credential_version]

    @property
    def uses_lwa(self) -> bool:
        return self.credential_version.startswith("3.")


@dataclass(frozen=True)
class SpApiConfig:
    lwa_client_id: str
    lwa_client_secret: str
    refresh_token: str
    region: str
    marketplace_id: str

    @property
    def endpoint(self) -> str:
        return SP_API_ENDPOINTS[self.region]


@dataclass(frozen=True)
class WordPressConfig:
    base_url: str
    username: str
    app_password: str


@dataclass(frozen=True)
class AppConfig:
    creators: CreatorsApiConfig
    sp_api: SpApiConfig | None
    wordpress: WordPressConfig | None


def load_config(env_file: str | None = ".env") -> AppConfig:
    """環境変数から設定を組み立てる。必須項目が欠けていれば ConfigError を送出する。"""
    if load_dotenv and env_file and os.path.exists(env_file):
        load_dotenv(env_file)

    required = {
        "AMAZON_CREATORS_CREDENTIAL_ID": _env("AMAZON_CREATORS_CREDENTIAL_ID"),
        "AMAZON_CREATORS_CREDENTIAL_SECRET": _env("AMAZON_CREATORS_CREDENTIAL_SECRET"),
        "AMAZON_CREATORS_CREDENTIAL_VERSION": _env("AMAZON_CREATORS_CREDENTIAL_VERSION", "3.3"),
        "AMAZON_PARTNER_TAG": _env("AMAZON_PARTNER_TAG"),
        "AMAZON_MARKETPLACE": _env("AMAZON_MARKETPLACE", "www.amazon.co.jp"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ConfigError(f"必須の環境変数が設定されていません: {', '.join(missing)}")

    version = required["AMAZON_CREATORS_CREDENTIAL_VERSION"]
    if version not in CREATORS_TOKEN_ENDPOINTS:
        raise ConfigError(
            f"AMAZON_CREATORS_CREDENTIAL_VERSION が不正です: {version}"
            f"（指定できる値: {', '.join(CREATORS_TOKEN_ENDPOINTS)}）"
        )

    creators = CreatorsApiConfig(
        credential_id=required["AMAZON_CREATORS_CREDENTIAL_ID"],
        credential_secret=required["AMAZON_CREATORS_CREDENTIAL_SECRET"],
        credential_version=version,
        partner_tag=required["AMAZON_PARTNER_TAG"],
        marketplace=required["AMAZON_MARKETPLACE"],
    )

    sp_api = None
    if _env("SP_API_ENABLED", "false").lower() == "true":
        sp_values = {
            "SP_API_LWA_CLIENT_ID": _env("SP_API_LWA_CLIENT_ID"),
            "SP_API_LWA_CLIENT_SECRET": _env("SP_API_LWA_CLIENT_SECRET"),
            "SP_API_REFRESH_TOKEN": _env("SP_API_REFRESH_TOKEN"),
        }
        sp_missing = [name for name, value in sp_values.items() if not value]
        if sp_missing:
            raise ConfigError(f"SP_API_ENABLED=true ですが未設定の項目があります: {', '.join(sp_missing)}")
        region = _env("SP_API_REGION", "fe")
        if region not in SP_API_ENDPOINTS:
            raise ConfigError(f"SP_API_REGION が不正です: {region}（na / eu / fe）")
        sp_api = SpApiConfig(
            lwa_client_id=sp_values["SP_API_LWA_CLIENT_ID"],
            lwa_client_secret=sp_values["SP_API_LWA_CLIENT_SECRET"],
            refresh_token=sp_values["SP_API_REFRESH_TOKEN"],
            region=region,
            marketplace_id=_env("SP_API_MARKETPLACE_ID") or MARKETPLACE_IDS.get(creators.marketplace, ""),
        )

    wordpress = None
    if all(_env(n) for n in ("WP_BASE_URL", "WP_USERNAME", "WP_APP_PASSWORD")):
        wordpress = WordPressConfig(
            base_url=_env("WP_BASE_URL").rstrip("/"),
            username=_env("WP_USERNAME"),
            app_password=_env("WP_APP_PASSWORD"),
        )

    return AppConfig(creators=creators, sp_api=sp_api, wordpress=wordpress)
