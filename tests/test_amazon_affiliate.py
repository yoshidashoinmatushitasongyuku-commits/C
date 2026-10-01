"""API を実際に呼ばず、モックで各処理を確認するテスト。  python -m unittest discover tests"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from amazon_affiliate import settings
from amazon_affiliate.config import AppConfig, CreatorsApiConfig
from amazon_affiliate.content import build_post
from amazon_affiliate.creators_api import CreatorsApiClient, parse_item
from amazon_affiliate.errors import (
    ApiAuthError,
    ApiRateLimitError,
    ApiServerError,
    InputFileError,
    PublishError,
)
from amazon_affiliate.history import ProcessedHistory
from amazon_affiliate.http_client import RateLimiter, with_retry
from amazon_affiliate.loaders import load_candidates, load_from_list
from amazon_affiliate.models import AmazonItem, ResearchCandidate, ScoredProduct
from amazon_affiliate.pipeline import run_once
from amazon_affiliate.selection import select_products

CREATORS = CreatorsApiConfig("id", "secret", "3.3", "testtag-22", "www.amazon.co.jp")

RAW_ITEM = {
    "asin": "B000000001",
    "detailPageURL": "https://www.amazon.co.jp/dp/B000000001?tag=testtag-22",
    "itemInfo": {
        "title": {"displayValue": "テスト商品"},
        "byLineInfo": {"brand": {"displayValue": "テストブランド"}},
        "features": {"displayValues": ["特徴A", "特徴B"]},
        "classifications": {"productGroup": {"displayValue": "Home"}},
    },
    "images": {"primary": {"large": {"url": "https://m.media-amazon.com/images/I/test.jpg"}}},
    "offersV2": {"listings": [{
        "isBuyBoxWinner": True,
        "price": {"money": {"amount": 2480, "currency": "JPY", "displayAmount": "￥2,480"}},
        "availability": {"type": "IN_STOCK", "message": "在庫あり"},
    }]},
    "customerReviews": {"count": 42, "starRating": {"value": 4.3}},
}


def fake_response(status: int, body: dict | None = None, headers: dict | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body or {}).encode()
    response.headers.update(headers or {})
    return response


class LoaderTests(unittest.TestCase):
    def test_list_skips_invalid_and_duplicate_asin(self):
        rows = [
            {"asin": "b000000001", "name": "A", "推定利益率": "35%", "優先順位": "1"},
            {"asin": "", "name": "ASIN無し"},
            {"asin": "B000000001", "name": "重複"},
        ]
        candidates = load_from_list(rows)
        self.assertEqual([c.asin for c in candidates], ["B000000001"])
        self.assertEqual(candidates[0].estimated_profit_margin, 35.0)
        self.assertEqual(candidates[0].priority, 1)

    def test_csv_with_japanese_headers(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.csv"
            path.write_text("ASIN,商品名,推定販売価格\nB000000002,商品,\"2,480円\"\n", encoding="utf-8-sig")
            candidates = load_candidates(path)
        self.assertEqual(candidates[0].estimated_price, 2480.0)

    def test_missing_and_broken_files(self):
        with self.assertRaises(InputFileError):
            load_candidates("/nonexistent/file.json")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "broken.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(InputFileError):
                load_candidates(path)


class ParseItemTests(unittest.TestCase):
    def test_full_item(self):
        item = parse_item(RAW_ITEM, "2026-10-01T00:00:00+00:00")
        self.assertEqual(item.title, "テスト商品")
        self.assertEqual(item.price, 2480.0)
        self.assertEqual(item.availability, "IN_STOCK")
        self.assertEqual(item.rating, 4.3)
        self.assertEqual(item.review_count, 42)

    def test_missing_fields_stay_none(self):
        item = parse_item({"asin": "B000000003"}, "2026-10-01T00:00:00+00:00")
        self.assertIsNone(item.title)
        self.assertIsNone(item.price)
        self.assertIsNone(item.rating)
        self.assertEqual(item.features, [])


class RetryTests(unittest.TestCase):
    def test_retries_rate_limit_then_succeeds(self):
        calls, sleeps = [], []

        def func():
            calls.append(1)
            if len(calls) < 3:
                raise ApiRateLimitError("429")
            return "ok"

        self.assertEqual(with_retry(func, "test", sleep=sleeps.append), "ok")
        self.assertEqual(len(sleeps), 2)
        self.assertGreater(sleeps[1], sleeps[0])  # 指数的に待ち時間が増える

    def test_gives_up_after_max_retries(self):
        sleeps = []
        with self.assertRaises(ApiServerError):
            with_retry(lambda: (_ for _ in ()).throw(ApiServerError("500")), "test", sleep=sleeps.append)
        self.assertEqual(len(sleeps), settings.MAX_RETRIES)

    def test_auth_error_is_not_retried(self):
        sleeps = []
        with self.assertRaises(ApiAuthError):
            with_retry(lambda: (_ for _ in ()).throw(ApiAuthError("401")), "test", sleep=sleeps.append)
        self.assertEqual(sleeps, [])


class CreatorsClientTests(unittest.TestCase):
    def make_client(self, responses):
        session = mock.Mock(spec=requests.Session)
        session.request.side_effect = responses
        limiter = RateLimiter(0, sleep=lambda s: None)
        return CreatorsApiClient(CREATORS, session=session, rate_limiter=limiter), session

    def test_get_items_reports_missing_asin(self):
        token = fake_response(200, {"access_token": "t", "expires_in": 3600})
        items = fake_response(200, {
            "itemsResult": {"items": [RAW_ITEM]},
            "errors": [{"code": "InvalidParameterValue", "message": "B000000009 は無効です"}],
        })
        client, session = self.make_client([token, items])
        found, failed = client.get_items(["B000000001", "B000000009"])
        self.assertIn("B000000001", found)
        self.assertIn("B000000009", failed)
        call = session.request.call_args_list[1]
        self.assertEqual(call.kwargs["headers"]["x-marketplace"], "www.amazon.co.jp")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer t")
        self.assertEqual(call.kwargs["json"]["partnerTag"], "testtag-22")

    def test_all_not_found_404(self):
        token = fake_response(200, {"access_token": "t", "expires_in": 3600})
        client, _ = self.make_client([token, fake_response(404, {"message": "not found"})])
        found, failed = client.get_items(["B000000009"])
        self.assertEqual(found, {})
        self.assertIn("B000000009", failed)

    def test_refreshes_token_once_on_401(self):
        token = fake_response(200, {"access_token": "t", "expires_in": 3600})
        responses = [token, fake_response(401), token, fake_response(200, {"itemsResult": {"items": [RAW_ITEM]}})]
        client, _ = self.make_client(responses)
        found, _ = client.get_items(["B000000001"])
        self.assertIn("B000000001", found)


class SelectionAndContentTests(unittest.TestCase):
    def candidate(self, **kw):
        base = dict(asin="B000000001", name="テスト", category="生活", estimated_profit_margin=40.0,
                    reason="理由", priority=1)
        base.update(kw)
        return ResearchCandidate(**base)

    def test_strict_missing_values_reject(self):
        item = parse_item({"asin": "B000000001", "itemInfo": {"title": {"displayValue": "x"}}}, "2026-10-01T00:00:00+00:00")
        self.assertEqual(select_products([(self.candidate(), item)]), [])

    def test_selects_good_item(self):
        item = parse_item(RAW_ITEM, "2026-10-01T00:00:00+00:00")
        selected = select_products([(self.candidate(), item)])
        self.assertEqual(len(selected), 1)

    def test_low_margin_rejected(self):
        item = parse_item(RAW_ITEM, "2026-10-01T00:00:00+00:00")
        self.assertEqual(select_products([(self.candidate(estimated_profit_margin=10.0), item)]), [])

    def test_post_uses_only_api_values(self):
        item = parse_item(RAW_ITEM, "2026-10-01T00:00:00+00:00")
        post = build_post(ScoredProduct(self.candidate(), item, 80.0), CREATORS)
        self.assertEqual(post.affiliate_url, RAW_ITEM["detailPageURL"])
        self.assertIn("2026/10/01 09:00 時点", post.price_text)
        self.assertNotIn("40.0", post.description)  # 社内の推定利益率は載せない

    def test_post_requires_title(self):
        item = AmazonItem(asin="B000000001")
        with self.assertRaises(PublishError):
            build_post(ScoredProduct(self.candidate(), item, 80.0), CREATORS)


class PipelineTests(unittest.TestCase):
    def test_run_twice_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(settings, "OUTPUT_DIR", Path(d) / "out"):
            history = ProcessedHistory(Path(d) / "h.sqlite3")
            client = mock.Mock()
            client.get_items.return_value = ({"B000000001": parse_item(RAW_ITEM, "2026-10-01T00:00:00+00:00")}, {})
            config = AppConfig(creators=CREATORS, sp_api=None, wordpress=None)
            candidates = [ResearchCandidate(asin="B000000001", name="テスト", estimated_profit_margin=40.0,
                                            reason="理由", priority=1)]

            first = run_once(config, candidates, creators_client=client, history=history)
            self.assertEqual(len(first.posts), 1)
            self.assertTrue(first.output_files["json"].exists())

            second = run_once(config, candidates, creators_client=client, history=history)
            self.assertEqual(second.skipped_duplicates, 1)
            self.assertEqual(client.get_items.call_count, 1)  # 2回目は API を呼ばない
            history.close()


if __name__ == "__main__":
    unittest.main()
