from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.discovery.price_instruments import (
    BUILT_IN_CANDIDATES,
    build_custom_candidate,
    discover_price_instruments,
    extract_display_name,
)
from app.collectors.prices.current_price_config import CurrentPriceInstrument


class FakeHttpClient:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads

    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> httpx.Response:
        code = params["codes"]
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(
            200,
            content=self.payloads[code],
            headers={"content-type": "text/html;charset=UTF-8"},
            request=request,
        )

    def close(self) -> None:
        return None


def test_discovery_marks_soybean_meal_candidate_ready() -> None:
    payload = b'var quote_json = {"flag":true,"JO_165938":{"showName":"\xe8\xb1\x86\xe7\xb2\x95\xe4\xb8\xbb\xe5\x8a\x9b","q5":2977.0,"time":1779715416000}};'
    client = FakeHttpClient({"JO_165938": payload})
    candidate = BUILT_IN_CANDIDATES[0]

    results = discover_price_instruments(
        candidates=(candidate,),
        http_client=client,
        checked_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
    )

    soybean_meal = next(result for result in results if result.product_code == "soybean_meal")
    assert soybean_meal.status == "ready_to_add"
    assert soybean_meal.external_code == "JO_165938"
    assert soybean_meal.sample_price == 2977.0
    assert soybean_meal.parsed_name == "豆粕主力"


def test_discovery_rejects_mismatched_candidate_name() -> None:
    payload = b'var hq_str_JO_165952 = "\xe8\xb1\x86\xe6\xb2\xb92611,0,8450.0,8449.0,8448.0";'
    client = FakeHttpClient({"JO_165952": payload})
    candidate = BUILT_IN_CANDIDATES[2]

    results = discover_price_instruments(
        candidates=(candidate,),
        http_client=client,
        checked_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
    )

    soybean_meal = next(result for result in results if result.product_code == "soybean_meal")
    assert soybean_meal.status == "not_found"
    assert soybean_meal.rejected_candidates[0]["parsed_name"] == "豆油2611"


def test_discovery_marks_sunflower_products_not_found_without_guessing() -> None:
    results = discover_price_instruments(
        candidates=(),
        http_client=FakeHttpClient({}),
        checked_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
    )

    statuses = {result.product_code: result.status for result in results}
    assert statuses["sunflower_oil"] == "not_found"
    assert statuses["sunflower_meal"] == "not_found"


def test_custom_candidate_builds_default_json_price_path() -> None:
    candidate = build_custom_candidate(
        product_code="soybean_meal",
        title="Соевый шрот",
        endpoint="https://api.jijinhao.com/quoteCenter/realTime.htm",
        external_code="JO_165938",
        parser_type="json",
    )

    assert candidate.response_prefix == "var quote_json = "
    assert candidate.price_path == ("JO_165938", "q5")


def test_extract_display_name_for_csv_payload() -> None:
    instrument = CurrentPriceInstrument(
        product_code="soybean_meal",
        external_code="JO_165938",
        endpoint="https://api.jijinhao.com/sQuoteCenter/realTime.htm",
        params={"codes": "JO_165938"},
        parser_type="csv",
        response_prefix="var hq_str_JO_165938 = ",
        price_index=3,
        currency="CNY",
        unit="metric_ton",
        source_note="test",
    )

    assert extract_display_name(instrument, 'var hq_str_JO_165938 = "豆粕主力,0,2989.0,2976.0";') == "豆粕主力"
