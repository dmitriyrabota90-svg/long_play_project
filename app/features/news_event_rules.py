from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


EXTRACTION_VERSION = "news_event_rules_v1"
EXTRACTION_METHOD = "keyword_rule"


@dataclass(frozen=True)
class EventRule:
    event_category: str
    keyword_groups: tuple[tuple[str, ...], ...]
    negative_keywords: tuple[str, ...]
    direction_hint: str
    severity_label: str
    severity: Decimal | None
    lag_bucket: str
    strong_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommodityFamilyRule:
    commodity_family: str
    keywords: tuple[str, ...]
    affected_products: tuple[str, ...]


EVENT_RULES: tuple[EventRule, ...] = (
    EventRule(
        event_category="export_restriction",
        keyword_groups=(
            ("export", "exports", "shipment", "shipments"),
            ("ban", "banned", "restriction", "restrictions", "quota", "duty", "tariff", "license", "licence", "sanction"),
        ),
        negative_keywords=("football", "software"),
        direction_hint="bullish",
        severity_label="high",
        severity=Decimal("0.75"),
        lag_bucket="same_day",
        strong_keywords=("ban", "banned", "quota", "sanction"),
    ),
    EventRule(
        event_category="import_policy",
        keyword_groups=(
            ("import", "imports"),
            ("duty", "tariff", "quota", "license", "licence", "restriction", "tax"),
        ),
        negative_keywords=("software",),
        direction_hint="mixed",
        severity_label="medium",
        severity=Decimal("0.50"),
        lag_bucket="1_7d",
        strong_keywords=("tariff", "quota", "duty"),
    ),
    EventRule(
        event_category="war_logistics_disruption",
        keyword_groups=(
            ("black sea", "war", "attack", "sanction", "port", "ports", "shipping", "freight", "rail", "railway"),
            ("disrupt", "disruption", "closed", "closure", "halt", "delay", "blocked", "strike", "damage"),
        ),
        negative_keywords=(),
        direction_hint="bullish",
        severity_label="high",
        severity=Decimal("0.75"),
        lag_bucket="same_day",
        strong_keywords=("black sea", "blocked", "closure", "attack"),
    ),
    EventRule(
        event_category="weather_disaster",
        keyword_groups=(("drought", "flood", "flooding", "frost", "freeze", "heatwave", "heat wave", "wildfire", "storm", "hurricane"),),
        negative_keywords=(),
        direction_hint="bullish",
        severity_label="medium",
        severity=Decimal("0.50"),
        lag_bucket="7_30d",
        strong_keywords=("drought", "flood", "frost", "heatwave", "wildfire"),
    ),
    EventRule(
        event_category="crop_report",
        keyword_groups=(
            ("wasde", "usda", "crop report", "crop forecast", "production forecast", "supply and demand", "stocks report", "acreage"),
        ),
        negative_keywords=(),
        direction_hint="mixed",
        severity_label="medium",
        severity=Decimal("0.50"),
        lag_bucket="same_day",
        strong_keywords=("wasde", "usda", "stocks report", "acreage"),
    ),
    EventRule(
        event_category="biofuel_policy",
        keyword_groups=(("biofuel", "biodiesel", "renewable diesel", "ethanol", "blending mandate", "mandate"),),
        negative_keywords=(),
        direction_hint="mixed",
        severity_label="medium",
        severity=Decimal("0.50"),
        lag_bucket="7_30d",
        strong_keywords=("mandate", "biodiesel", "renewable diesel"),
    ),
    EventRule(
        event_category="energy_shock",
        keyword_groups=(
            ("crude oil", "brent", "wti", "diesel", "natural gas", "gas prices", "energy prices", "fuel prices"),
            ("surge", "spike", "jump", "fall", "drop", "slump", "shock", "record"),
        ),
        negative_keywords=("football",),
        direction_hint="mixed",
        severity_label="medium",
        severity=Decimal("0.50"),
        lag_bucket="same_day",
        strong_keywords=("surge", "spike", "shock", "record"),
    ),
    EventRule(
        event_category="currency_macro",
        keyword_groups=(
            ("currency", "exchange rate", "dollar", "yuan", "ruble", "rouble", "inflation", "interest rate"),
            ("surge", "fall", "weakens", "strengthens", "devaluation", "hike", "cut"),
        ),
        negative_keywords=(),
        direction_hint="mixed",
        severity_label="medium",
        severity=Decimal("0.50"),
        lag_bucket="same_day",
        strong_keywords=("devaluation", "inflation", "interest rate"),
    ),
    EventRule(
        event_category="demand_shock",
        keyword_groups=(
            ("demand", "imports", "crush", "feed demand", "livestock", "china"),
            ("surge", "rise", "jump", "fall", "drop", "slowdown", "weak"),
        ),
        negative_keywords=(),
        direction_hint="mixed",
        severity_label="medium",
        severity=Decimal("0.50"),
        lag_bucket="1_7d",
        strong_keywords=("china", "crush", "feed demand"),
    ),
    EventRule(
        event_category="supply_chain",
        keyword_groups=(
            ("freight", "shipping", "port", "ports", "rail", "railway", "container", "logistics", "truck", "trucking"),
            ("delay", "delays", "strike", "shortage", "disruption", "bottleneck", "closure"),
        ),
        negative_keywords=(),
        direction_hint="bullish",
        severity_label="medium",
        severity=Decimal("0.50"),
        lag_bucket="same_day",
        strong_keywords=("strike", "closure", "bottleneck"),
    ),
)


COMMODITY_FAMILY_RULES: tuple[CommodityFamilyRule, ...] = (
    CommodityFamilyRule(
        commodity_family="soybean",
        keywords=("soybean", "soybeans", "soybean oil", "soybean meal", "soyoil", "soymeal"),
        affected_products=("soybean_oil", "soybean_meal"),
    ),
    CommodityFamilyRule(
        commodity_family="rapeseed",
        keywords=("rapeseed", "canola", "rapeseed oil", "canola oil", "rapeseed meal"),
        affected_products=("rapeseed_oil", "rapeseed_meal"),
    ),
    CommodityFamilyRule(
        commodity_family="vegetable_oils",
        keywords=("vegetable oil", "vegetable oils", "edible oil", "edible oils", "palm oil", "sunflower oil"),
        affected_products=("soybean_oil", "rapeseed_oil"),
    ),
    CommodityFamilyRule(
        commodity_family="grains",
        keywords=("corn", "maize", "wheat"),
        affected_products=(),
    ),
    CommodityFamilyRule(
        commodity_family="fertilizer_energy",
        keywords=("fertilizer", "fertiliser", "diesel", "natural gas", "crude oil", "brent", "wti"),
        affected_products=("rapeseed_oil", "soybean_oil", "rapeseed_meal", "soybean_meal"),
    ),
)

EVENT_RULES_BY_CATEGORY: dict[str, EventRule] = {item.event_category: item for item in EVENT_RULES}
COMMODITY_FAMILY_RULES_BY_FAMILY: dict[str, CommodityFamilyRule] = {
    item.commodity_family: item for item in COMMODITY_FAMILY_RULES
}

