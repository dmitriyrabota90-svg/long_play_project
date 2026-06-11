from __future__ import annotations

from dataclasses import dataclass

SOURCE_CODE = "un_comtrade"
COLLECTOR_NAME = "un_comtrade"
PARSER_VERSION = "un_comtrade_v1"

ENDPOINT = "https://comtradeapi.un.org/data/v1/get/C/M/HS"
REQUEST_TIMEOUT = 20.0
MAX_MONTHS_PER_RUN = 3
DEFAULT_MAXRECORDS = 100
MAX_MAXRECORDS = 500

HEADERS = {
    "User-Agent": "commodity-dataset-builder/0.1 (+https://github.com/dmitriyrabota90-svg/long_play_project)",
    "Accept": "application/json",
}

SUPPORTED_HS_CODES = ("1201", "1507", "2304", "1205", "1514", "2306")

FLOW_CODE_BY_DIRECTION = {
    "import": "M",
    "export": "X",
    "re_import": "RM",
    "re_export": "RX",
}


@dataclass(frozen=True)
class TradePartner:
    code: str
    request_code: str
    name: str
    aliases: tuple[str, ...] = ()


TRADE_PARTNERS = (
    TradePartner("BRA", "76", "Brazil", ("BR", "BRAZIL")),
    TradePartner("USA", "842", "United States", ("US", "UNITED STATES", "UNITED STATES OF AMERICA")),
    TradePartner("ARG", "32", "Argentina", ("ARGENTINA",)),
    TradePartner("CAN", "124", "Canada", ("CANADA",)),
    TradePartner("CHN", "156", "China", ("CN", "CHINA")),
    TradePartner("WLD", "0", "World", ("WORLD", "ALL", "ALL_PARTNERS", "ALL PARTNERS")),
)

TRADE_PARTNERS_BY_CODE = {item.code: item for item in TRADE_PARTNERS}
TRADE_PARTNERS_BY_REQUEST_CODE = {item.request_code: item for item in TRADE_PARTNERS}
TRADE_PARTNER_ALIASES: dict[str, TradePartner] = {}
for item in TRADE_PARTNERS:
    TRADE_PARTNER_ALIASES[item.code] = item
    TRADE_PARTNER_ALIASES[item.request_code] = item
    for alias in item.aliases:
        TRADE_PARTNER_ALIASES[alias.upper()] = item


def resolve_trade_partner(value: str, *, allow_world: bool = True) -> TradePartner:
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError("reporter/partner code cannot be empty")
    partner = TRADE_PARTNER_ALIASES.get(normalized)
    if partner is None:
        supported = ", ".join(sorted(TRADE_PARTNERS_BY_CODE))
        raise ValueError(f"unsupported reporter/partner code: {value}; supported codes: {supported}")
    if partner.code == "WLD" and not allow_world:
        raise ValueError("WLD/world is not supported as reporter for un_comtrade")
    return partner


def is_supported_hs_code(value: str) -> bool:
    return value.strip() in SUPPORTED_HS_CODES


def un_comtrade_params(
    *,
    hs_code: str,
    period: str,
    reporter: TradePartner,
    partner: TradePartner,
    flow_direction: str,
    maxrecords: int,
) -> dict[str, str]:
    flow_code = FLOW_CODE_BY_DIRECTION[flow_direction]
    return {
        "cmdCode": hs_code,
        "period": period.replace("-", ""),
        "reporterCode": reporter.request_code,
        "partnerCode": partner.request_code,
        "flowCode": flow_code,
        "maxRecords": str(maxrecords),
        "format": "json",
        "includeDesc": "true",
    }

