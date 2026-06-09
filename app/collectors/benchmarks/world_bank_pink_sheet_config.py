from __future__ import annotations

from dataclasses import dataclass


SOURCE_CODE = "world_bank_pink_sheet"
COLLECTOR_NAME = "world_bank_pink_sheet_collector"
PARSER_VERSION = "world_bank_pink_sheet_v1"
SOURCE_FILE_URL = (
    "https://thedocs.worldbank.org/en/doc/"
    "74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx"
)
SOURCE_DOCUMENT_URL = (
    "https://thedocs.worldbank.org/en/doc/"
    "74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/"
    "world-bank-commodities-price-data-the-pink-sheet"
)
REQUEST_TIMEOUT = 45.0
MAX_RESPONSE_BYTES = 5_000_000

HEADERS = {
    "User-Agent": "commodity-dataset-builder/0.1 (+https://github.com/dmitriyrabota90-svg/long_play_project)",
    "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream,*/*",
    "Accept-Language": "en,ru;q=0.9",
}


@dataclass(frozen=True)
class WorldBankBenchmark:
    benchmark_code: str
    external_id: str
    benchmark_name: str
    benchmark_category: str
    commodity_family: str
    geography: str
    frequency: str
    currency: str | None
    unit: str
    normalized_currency: str | None
    normalized_unit: str
    unit_note: str
    sheet_name: str
    source_column_candidates: tuple[str, ...]


WORLD_BANK_BENCHMARKS: tuple[WorldBankBenchmark, ...] = (
    WorldBankBenchmark(
        benchmark_code="world_bank_soybean_oil",
        external_id="Monthly Prices: Soybean oil",
        benchmark_name="World Bank soybean oil",
        benchmark_category="vegetable_oil",
        commodity_family="soybean",
        geography="global",
        frequency="monthly",
        currency="USD",
        unit="USD/metric_ton",
        normalized_currency="USD",
        normalized_unit="USD/metric_ton",
        unit_note="Pink Sheet Monthly Prices column Soybean oil, unit shown as ($/mt).",
        sheet_name="Monthly Prices",
        source_column_candidates=("Soybean oil",),
    ),
    WorldBankBenchmark(
        benchmark_code="world_bank_soybeans",
        external_id="Monthly Prices: Soybeans",
        benchmark_name="World Bank soybeans",
        benchmark_category="oilseed",
        commodity_family="soybean",
        geography="global",
        frequency="monthly",
        currency="USD",
        unit="USD/metric_ton",
        normalized_currency="USD",
        normalized_unit="USD/metric_ton",
        unit_note="Pink Sheet Monthly Prices column Soybeans, unit shown as ($/mt).",
        sheet_name="Monthly Prices",
        source_column_candidates=("Soybeans",),
    ),
    WorldBankBenchmark(
        benchmark_code="world_bank_palm_oil",
        external_id="Monthly Prices: Palm oil",
        benchmark_name="World Bank palm oil",
        benchmark_category="vegetable_oil",
        commodity_family="palm",
        geography="global",
        frequency="monthly",
        currency="USD",
        unit="USD/metric_ton",
        normalized_currency="USD",
        normalized_unit="USD/metric_ton",
        unit_note="Pink Sheet Monthly Prices column Palm oil, unit shown as ($/mt).",
        sheet_name="Monthly Prices",
        source_column_candidates=("Palm oil",),
    ),
    WorldBankBenchmark(
        benchmark_code="world_bank_maize",
        external_id="Monthly Prices: Maize",
        benchmark_name="World Bank maize",
        benchmark_category="grain",
        commodity_family="corn",
        geography="global",
        frequency="monthly",
        currency="USD",
        unit="USD/metric_ton",
        normalized_currency="USD",
        normalized_unit="USD/metric_ton",
        unit_note="Pink Sheet Monthly Prices column Maize, unit shown as ($/mt).",
        sheet_name="Monthly Prices",
        source_column_candidates=("Maize",),
    ),
    WorldBankBenchmark(
        benchmark_code="world_bank_wheat",
        external_id="Monthly Prices: Wheat, US SRW",
        benchmark_name="World Bank wheat, US SRW",
        benchmark_category="grain",
        commodity_family="wheat",
        geography="global",
        frequency="monthly",
        currency="USD",
        unit="USD/metric_ton",
        normalized_currency="USD",
        normalized_unit="USD/metric_ton",
        unit_note="Pink Sheet Monthly Prices column Wheat, US SRW, unit shown as ($/mt).",
        sheet_name="Monthly Prices",
        source_column_candidates=("Wheat, US SRW", "Wheat"),
    ),
    WorldBankBenchmark(
        benchmark_code="world_bank_fertilizer_index",
        external_id="Monthly Indices: Fertilizers",
        benchmark_name="World Bank fertilizers index",
        benchmark_category="fertilizer",
        commodity_family="fertilizer",
        geography="global",
        frequency="monthly",
        currency=None,
        unit="index_2010_100",
        normalized_currency=None,
        normalized_unit="index_2010_100",
        unit_note="Pink Sheet Monthly Indices, 2010=100.",
        sheet_name="Monthly Indices",
        source_column_candidates=("Fertilizers **", "Fertilizers"),
    ),
)

WORLD_BANK_BENCHMARKS_BY_CODE: dict[str, WorldBankBenchmark] = {
    item.benchmark_code: item for item in WORLD_BANK_BENCHMARKS
}


def is_known_benchmark(benchmark_code: str) -> bool:
    return benchmark_code in WORLD_BANK_BENCHMARKS_BY_CODE
