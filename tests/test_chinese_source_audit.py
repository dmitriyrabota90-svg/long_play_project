from __future__ import annotations

import httpx

from app.discovery.chinese_source_audit import (
    build_audit,
    known_instruments,
    product_candidates,
)


class FakeHttpClient:
    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        if "historys.htm" in url:
            code = params["codes"]
            payload = (
                'var quote_json = {"flag":true,"style":3,"data":{'
                f'"{code}_unit":"元/吨","{code}_productName":"豆粕主力",'
                f'"{code}":[{{"q1":2998.0,"q2":2990.0,"q3":2999.0,"q4":2984.0,"q60":123.0,"q62":456.0,"time":1779379200000}}]'
                "}};"
            )
            return httpx.Response(200, text=payload, headers={"content-type": "text/html;charset=UTF-8"}, request=request)
        code = params.get("codes", "JO_165938")
        if "sQuoteCenter" in url:
            payload = f'var hq_str_{code} = "豆油主力,0,8450.0,8449.0,8448.0";'
        else:
            payload = f'var quote_json = {{"flag":true,"{code}":{{"showName":"豆粕主力","q5":2977.0}}}};'
        return httpx.Response(200, text=payload, headers={"content-type": "text/html;charset=UTF-8"}, request=request)

    def close(self) -> None:
        return None


def test_known_instruments_include_four_current_products() -> None:
    products = {item.product_code for item in known_instruments()}

    assert products == {"rapeseed_oil", "soybean_oil", "rapeseed_meal", "soybean_meal"}


def test_product_candidates_keep_sunflower_not_found() -> None:
    statuses = {item.product_code: item.status for item in product_candidates()}

    assert statuses["sunflower_oil"] == "not_found"
    assert statuses["sunflower_meal"] == "not_found"


def test_inventory_mode_does_not_run_network_probes() -> None:
    audit = build_audit("inventory", http_client=FakeHttpClient())

    assert audit.probes == []
    assert audit.data_capabilities


def test_check_known_mode_records_current_and_history_probes() -> None:
    audit = build_audit("check-known", http_client=FakeHttpClient())

    names = {probe.name for probe in audit.probes}
    assert "current_soybean_meal" in names
    assert "historys_soybean_meal" in names
    assert all(probe.status == "ok" for probe in audit.probes)


def test_search_keywords_is_explicitly_not_supported() -> None:
    audit = build_audit("search-keywords", http_client=FakeHttpClient())

    assert audit.search_keywords_status == "not_supported"
    assert audit.probes[0].status == "not_supported"
