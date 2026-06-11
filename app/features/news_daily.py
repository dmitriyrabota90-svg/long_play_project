from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CommodityEvent, DailyNewsFeature, DailyProductFeature, NewsArticle, Product
from app.db.session import session_scope


NEWS_DAILY_FEATURE_VERSION = "news_daily_features_v1"
NEWS_CATEGORY_FIELDS = {
    "export_restriction": "export_restriction_count_30d",
    "import_policy": "import_policy_count_30d",
    "war_logistics_disruption": "war_logistics_count_30d",
    "weather_disaster": "weather_disaster_count_30d",
    "crop_report": "crop_report_count_30d",
    "biofuel_policy": "biofuel_policy_count_30d",
    "energy_shock": "energy_shock_count_30d",
    "demand_shock": "demand_shock_count_30d",
    "supply_chain": "supply_chain_count_30d",
}
COUNT_FIELDS = (
    "news_count_1d",
    "news_count_7d",
    "news_count_30d",
    "event_count_1d",
    "event_count_7d",
    "event_count_30d",
    "bullish_event_count_7d",
    "bearish_event_count_7d",
    "mixed_event_count_7d",
    *NEWS_CATEGORY_FIELDS.values(),
)


@dataclass(frozen=True)
class NewsDailyBuildResult:
    products_processed: int = 0
    dates_processed: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    warnings_count: int = 0
    missing_news_products: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _MappedArticle:
    article_id: int
    published_date: date
    product_codes: frozenset[str]
    commodity_families: frozenset[str]


def build_news_daily_features(
    *,
    product_code: str | None = None,
    commodity_family: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    session: Session | None = None,
) -> NewsDailyBuildResult:
    if session is None:
        with session_scope() as scoped_session:
            return _build_news_daily_features_with_session(
                scoped_session,
                product_code=product_code,
                commodity_family=commodity_family,
                from_date=from_date,
                to_date=to_date,
            )
    return _build_news_daily_features_with_session(
        session,
        product_code=product_code,
        commodity_family=commodity_family,
        from_date=from_date,
        to_date=to_date,
    )


def _build_news_daily_features_with_session(
    session: Session,
    *,
    product_code: str | None,
    commodity_family: str | None,
    from_date: date | None,
    to_date: date | None,
) -> NewsDailyBuildResult:
    products = _select_products(session, product_code=product_code, commodity_family=commodity_family)
    if not products:
        return NewsDailyBuildResult()

    bounds = _feature_date_bounds(session)
    if from_date is not None and to_date is not None and from_date > to_date:
        raise ValueError("from_date must be on or before to_date")
    if bounds is None and (from_date is None or to_date is None):
        return NewsDailyBuildResult(products_processed=len(products))

    start = from_date or bounds[0]
    end = to_date or bounds[1]
    if start > end:
        raise ValueError("from_date must be on or before to_date")

    feature_dates = tuple(_date_range(start, end))
    articles = _load_articles(session, to_date=end)
    events = _load_events(session, to_date=end)
    mapped_articles = tuple(_mapped_article(article) for article in articles)
    product_codes_with_news: set[str] = set()
    checked_at = datetime.now(timezone.utc)

    rows_created = 0
    rows_updated = 0
    rows_skipped = 0
    warnings_count = 0

    for product in products:
        product_family = _primary_family(product.code)
        for feature_date in feature_dates:
            values = _feature_values(
                product=product,
                product_family=product_family,
                feature_date=feature_date,
                articles=mapped_articles,
                events=events,
            )
            if values["news_count_30d"] > 0 or values["event_count_30d"] > 0:
                product_codes_with_news.add(product.code)
            if values["missing_flags"]:
                warnings_count += 1

            existing = session.scalar(
                select(DailyNewsFeature)
                .where(DailyNewsFeature.product_id == product.id, DailyNewsFeature.feature_date == feature_date)
                .limit(1)
            )
            if existing is None:
                session.add(
                    DailyNewsFeature(
                        product_id=product.id,
                        commodity_family=product_family,
                        feature_date=feature_date,
                        **values,
                    )
                )
                rows_created += 1
            elif _feature_row_needs_update(existing, values, commodity_family=product_family):
                existing.commodity_family = product_family
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.updated_at = checked_at
                rows_updated += 1
            else:
                rows_skipped += 1
            session.flush()

    missing_news_products = sorted(product.code for product in products if product.code not in product_codes_with_news)
    return NewsDailyBuildResult(
        products_processed=len(products),
        dates_processed=len(feature_dates),
        rows_created=rows_created,
        rows_updated=rows_updated,
        rows_skipped=rows_skipped,
        warnings_count=warnings_count,
        missing_news_products=missing_news_products,
    )


def _select_products(
    session: Session,
    *,
    product_code: str | None,
    commodity_family: str | None,
) -> tuple[Product, ...]:
    statement = select(Product).where(Product.is_active.is_(True)).order_by(Product.code)
    if product_code:
        statement = statement.where(Product.code == product_code)
    products = tuple(session.scalars(statement).all())
    if product_code and not products:
        raise ValueError(f"unknown product code: {product_code}")
    if commodity_family:
        products = tuple(product for product in products if _product_matches_family_filter(product.code, commodity_family))
    return products


def _feature_date_bounds(session: Session) -> tuple[date, date] | None:
    product_min, product_max = session.execute(
        select(func.min(DailyProductFeature.feature_date), func.max(DailyProductFeature.feature_date))
    ).one()
    if product_min is not None and product_max is not None:
        return product_min, product_max

    article_min, article_max = session.execute(
        select(func.min(NewsArticle.published_at), func.max(NewsArticle.published_at))
    ).one()
    event_min, event_max = session.execute(
        select(func.min(CommodityEvent.event_date), func.max(CommodityEvent.event_date))
    ).one()
    dates: list[date] = []
    if article_min is not None:
        dates.append(_to_utc(article_min).date())
    if article_max is not None:
        dates.append(_to_utc(article_max).date())
    if event_min is not None:
        dates.append(event_min)
    if event_max is not None:
        dates.append(event_max)
    if not dates:
        return None
    return min(dates), max(dates)


def _load_articles(session: Session, *, to_date: date) -> tuple[NewsArticle, ...]:
    cutoff = datetime.combine(to_date, time.max, tzinfo=timezone.utc)
    return tuple(
        session.scalars(
            select(NewsArticle)
            .where(NewsArticle.published_at <= cutoff)
            .order_by(NewsArticle.published_at, NewsArticle.id)
        ).all()
    )


def _load_events(session: Session, *, to_date: date) -> tuple[CommodityEvent, ...]:
    return tuple(
        session.scalars(
            select(CommodityEvent)
            .where(CommodityEvent.event_date <= to_date)
            .order_by(CommodityEvent.event_date, CommodityEvent.id)
        ).all()
    )


def _feature_values(
    *,
    product: Product,
    product_family: str,
    feature_date: date,
    articles: tuple[_MappedArticle, ...],
    events: tuple[CommodityEvent, ...],
) -> dict[str, Any]:
    values: dict[str, Any] = {field: 0 for field in COUNT_FIELDS}
    article_windows = {
        1: _matching_articles(articles, product_code=product.code, feature_date=feature_date, days=1),
        7: _matching_articles(articles, product_code=product.code, feature_date=feature_date, days=7),
        30: _matching_articles(articles, product_code=product.code, feature_date=feature_date, days=30),
    }
    event_windows = {
        1: _matching_events(events, product_code=product.code, product_family=product_family, feature_date=feature_date, days=1),
        7: _matching_events(events, product_code=product.code, product_family=product_family, feature_date=feature_date, days=7),
        30: _matching_events(events, product_code=product.code, product_family=product_family, feature_date=feature_date, days=30),
    }
    values["news_count_1d"] = len(article_windows[1])
    values["news_count_7d"] = len(article_windows[7])
    values["news_count_30d"] = len(article_windows[30])
    values["event_count_1d"] = len(event_windows[1])
    values["event_count_7d"] = len(event_windows[7])
    values["event_count_30d"] = len(event_windows[30])
    values["bullish_event_count_7d"] = sum(1 for event in event_windows[7] if event.direction_hint == "bullish")
    values["bearish_event_count_7d"] = sum(1 for event in event_windows[7] if event.direction_hint == "bearish")
    values["mixed_event_count_7d"] = sum(1 for event in event_windows[7] if event.direction_hint == "mixed")
    for category, field_name in NEWS_CATEGORY_FIELDS.items():
        values[field_name] = sum(1 for event in event_windows[30] if event.event_category == category)

    if values["event_count_7d"] > 0:
        values["sentiment_proxy_7d"] = _quant(
            Decimal(values["bullish_event_count_7d"] - values["bearish_event_count_7d"])
            / Decimal(values["event_count_7d"])
        )
    else:
        values["sentiment_proxy_7d"] = None

    as_of_dates = [item.published_date for item in article_windows[30]]
    as_of_dates.extend(event.event_date for event in event_windows[30])
    values["news_as_of_date"] = max(as_of_dates) if as_of_dates else None
    values["missing_flags"] = _missing_flags(
        all_articles_count=len(articles),
        all_events_count=len(events),
        matched_article_count=values["news_count_30d"],
        matched_event_count=values["event_count_30d"],
    )
    values["metadata_json"] = {
        "feature_version": NEWS_DAILY_FEATURE_VERSION,
        "product_code": product.code,
        "commodity_family": product_family,
        "windows": {"1d": 1, "7d": 7, "30d": 30},
        "article_ids_30d": [item.article_id for item in article_windows[30]],
        "event_ids_30d": [event.id for event in event_windows[30]],
        "sentiment_proxy_formula": "(bullish_event_count_7d - bearish_event_count_7d) / max(event_count_7d, 1); NULL when no events",
        "as_of_policy": "Uses only published_at/event_date <= feature_date.",
        "limitations": [
            "rule_based_events",
            "no_ml_or_llm_classifier",
            "source_country_may_not_equal_event_country",
        ],
    }
    return values


def _mapped_article(article: NewsArticle) -> _MappedArticle:
    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    products = {str(item) for item in metadata.get("affected_products_hint", []) if item}
    families = {str(metadata.get("commodity_family_hint"))} if metadata.get("commodity_family_hint") else set()
    query_key = metadata.get("query_key")
    if query_key == "grain_oilseed_policy":
        products.update(_all_current_products())
        families.add("fertilizer_energy")
    for family in tuple(families):
        products.update(_products_for_family(family))
    return _MappedArticle(
        article_id=article.id,
        published_date=_to_utc(article.published_at).date(),
        product_codes=frozenset(products),
        commodity_families=frozenset(families),
    )


def _matching_articles(
    articles: tuple[_MappedArticle, ...],
    *,
    product_code: str,
    feature_date: date,
    days: int,
) -> list[_MappedArticle]:
    start = feature_date - timedelta(days=days - 1)
    return [
        article
        for article in articles
        if start <= article.published_date <= feature_date and _article_matches_product(article, product_code)
    ]


def _matching_events(
    events: tuple[CommodityEvent, ...],
    *,
    product_code: str,
    product_family: str,
    feature_date: date,
    days: int,
) -> list[CommodityEvent]:
    start = feature_date - timedelta(days=days - 1)
    return [
        event
        for event in events
        if start <= event.event_date <= feature_date
        and event.published_at is not None
        and _to_utc(event.published_at).date() <= feature_date
        and _event_matches_product(event, product_code=product_code, product_family=product_family)
    ]


def _article_matches_product(article: _MappedArticle, product_code: str) -> bool:
    return product_code in article.product_codes


def _event_matches_product(event: CommodityEvent, *, product_code: str, product_family: str) -> bool:
    product_codes = _event_product_codes(event)
    if product_code in product_codes:
        return True
    event_family = event.commodity_family
    if event_family in _families_for_product(product_code):
        return True
    if event_family in {"fertilizer_energy", "policy_context"}:
        return True
    if event_family == "vegetable_oils" and product_code in {"soybean_oil", "rapeseed_oil"}:
        return True
    return event_family == product_family


def _event_product_codes(event: CommodityEvent) -> set[str]:
    affected = event.affected_products if isinstance(event.affected_products, dict) else {}
    return {str(item) for item in affected.get("product_codes", []) if item}


def _primary_family(product_code: str) -> str:
    if product_code.startswith("soybean_"):
        return "soybean"
    if product_code.startswith("rapeseed_"):
        return "rapeseed"
    return "unknown"


def _product_matches_family_filter(product_code: str, commodity_family: str) -> bool:
    if commodity_family in {"canola", "rapeseed_canola"}:
        commodity_family = "rapeseed"
    if commodity_family == "vegetable_oils":
        return product_code in {"soybean_oil", "rapeseed_oil"}
    if commodity_family in {"fertilizer_energy", "policy_context"}:
        return product_code in _all_current_products()
    return _primary_family(product_code) == commodity_family


def _families_for_product(product_code: str) -> set[str]:
    families = {_primary_family(product_code)}
    if product_code in {"soybean_oil", "rapeseed_oil"}:
        families.add("vegetable_oils")
    families.add("fertilizer_energy")
    return families


def _products_for_family(commodity_family: str) -> set[str]:
    if commodity_family == "soybean":
        return {"soybean_oil", "soybean_meal"}
    if commodity_family in {"rapeseed", "canola", "rapeseed_canola"}:
        return {"rapeseed_oil", "rapeseed_meal"}
    if commodity_family == "vegetable_oils":
        return {"soybean_oil", "rapeseed_oil"}
    if commodity_family in {"fertilizer_energy", "policy_context"}:
        return _all_current_products()
    return set()


def _all_current_products() -> set[str]:
    return {"rapeseed_oil", "soybean_oil", "rapeseed_meal", "soybean_meal"}


def _missing_flags(
    *,
    all_articles_count: int,
    all_events_count: int,
    matched_article_count: int,
    matched_event_count: int,
) -> dict[str, bool] | None:
    flags = {
        "no_news_articles": all_articles_count == 0,
        "no_commodity_events": all_events_count == 0,
        "no_matching_events": all_events_count > 0 and matched_event_count == 0,
        "partial_source_coverage": matched_article_count == 0 or matched_event_count == 0,
    }
    return {key: value for key, value in flags.items() if value} or None


def _feature_row_needs_update(row: DailyNewsFeature, values: dict[str, Any], *, commodity_family: str) -> bool:
    if row.commodity_family != commodity_family:
        return True
    for key, value in values.items():
        if key == "updated_at":
            continue
        if getattr(row, key) != value:
            return True
    return False


def _date_range(start: date, end: date) -> list[date]:
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _quant(value: Any, *, scale: int = 8) -> Decimal | None:
    if value is None:
        return None
    quant = Decimal("1").scaleb(-scale)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)
