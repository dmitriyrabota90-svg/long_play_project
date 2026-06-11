from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DailyProductFeature, DailyTradeFeature, Product, ProductTradeCodeWeight, TradeFlow
from app.db.session import session_scope


TRADE_DAILY_FEATURE_VERSION = "trade_daily_features_v1"
MAJOR_EXPORTER_REPORTERS = {"BRA", "USA", "ARG", "CAN"}
MAJOR_IMPORTER_REPORTERS = {"CHN"}
TRADE_NUMERIC_FIELDS = (
    "export_volume_1m",
    "export_volume_3m_avg",
    "export_volume_12m_sum",
    "import_volume_1m",
    "import_volume_3m_avg",
    "import_volume_12m_sum",
    "net_export_volume_1m",
    "export_value_usd_1m",
    "import_value_usd_1m",
    "average_export_unit_value_usd",
    "average_import_unit_value_usd",
    "china_import_volume_1m",
    "major_exporter_volume_1m",
    "major_importer_volume_1m",
    "trade_balance_proxy",
    "trade_yoy_change",
)


@dataclass(frozen=True)
class TradeDailyBuildResult:
    products_processed: int = 0
    dates_processed: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    warnings_count: int = 0
    missing_trade_products: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _TradeWeight:
    product_id: int
    trade_commodity_code_id: int
    weight: Decimal
    effective_from: date
    effective_to: date | None


@dataclass(frozen=True)
class _MonthlyAggregate:
    period_start: date
    period_end: date
    volume: Decimal
    value_usd: Decimal | None
    as_of_date: date
    rows_count: int


def build_trade_daily_features(
    *,
    product_code: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    session: Session | None = None,
) -> TradeDailyBuildResult:
    if session is None:
        with session_scope() as scoped_session:
            return _build_trade_daily_features_with_session(
                scoped_session,
                product_code=product_code,
                from_date=from_date,
                to_date=to_date,
            )
    return _build_trade_daily_features_with_session(
        session,
        product_code=product_code,
        from_date=from_date,
        to_date=to_date,
    )


def _build_trade_daily_features_with_session(
    session: Session,
    *,
    product_code: str | None,
    from_date: date | None,
    to_date: date | None,
) -> TradeDailyBuildResult:
    products = _select_products(session, product_code=product_code)
    if not products:
        return TradeDailyBuildResult()
    if from_date is not None and to_date is not None and from_date > to_date:
        raise ValueError("from_date must be on or before to_date")

    bounds = _feature_date_bounds(session)
    if bounds is None and (from_date is None or to_date is None):
        return TradeDailyBuildResult(products_processed=len(products))
    start = from_date or bounds[0]
    end = to_date or bounds[1]
    if start > end:
        raise ValueError("from_date must be on or before to_date")

    feature_dates = tuple(_date_range(start, end))
    weights = _load_product_trade_weights(session)
    trade_flows = _load_trade_flows(session, to_date=end)
    checked_at = datetime.now(timezone.utc)

    rows_created = 0
    rows_updated = 0
    rows_skipped = 0
    warnings_count = 0
    missing_trade_products: set[str] = set()

    for product in products:
        product_weights = weights.get(product.id, [])
        product_has_trade_data = False
        for feature_date in feature_dates:
            values = _feature_values(
                product=product,
                feature_date=feature_date,
                weights=product_weights,
                trade_flows=trade_flows,
            )
            if values["missing_flags"]:
                warnings_count += 1
            if values["trade_as_of_date"] is not None:
                product_has_trade_data = True
            existing = session.scalar(
                select(DailyTradeFeature)
                .where(DailyTradeFeature.product_id == product.id, DailyTradeFeature.feature_date == feature_date)
                .limit(1)
            )
            if existing is None:
                session.add(DailyTradeFeature(product_id=product.id, feature_date=feature_date, **values))
                rows_created += 1
            elif _feature_row_needs_update(existing, values):
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.updated_at = checked_at
                rows_updated += 1
            else:
                rows_skipped += 1
            session.flush()
        if not product_has_trade_data:
            missing_trade_products.add(product.code)

    return TradeDailyBuildResult(
        products_processed=len(products),
        dates_processed=len(feature_dates),
        rows_created=rows_created,
        rows_updated=rows_updated,
        rows_skipped=rows_skipped,
        warnings_count=warnings_count,
        missing_trade_products=sorted(missing_trade_products),
    )


def _feature_values(
    *,
    product: Product,
    feature_date: date,
    weights: list[_TradeWeight],
    trade_flows: dict[int, list[TradeFlow]],
) -> dict[str, Any]:
    values: dict[str, Any] = {field: None for field in TRADE_NUMERIC_FIELDS}
    values.update(
        {
            "trade_as_of_date": None,
            "reporting_lag_days": None,
            "missing_flags": {},
            "metadata_json": {
                "feature_version": TRADE_DAILY_FEATURE_VERSION,
                "source_table": "trade_flows",
                "availability_policy": "published_at_date_else_fetched_at_date <= feature_date",
            },
        }
    )
    missing_flags: dict[str, bool] = {}
    active_weights = _active_weights(weights, feature_date)
    if not active_weights:
        missing_flags["no_product_trade_code_weights"] = True
        values["missing_flags"] = missing_flags
        return values

    eligible_rows = _eligible_rows(active_weights=active_weights, trade_flows=trade_flows, feature_date=feature_date)
    if not eligible_rows:
        missing_flags["no_trade_flows"] = True
        values["missing_flags"] = missing_flags
        values["metadata_json"]["active_trade_code_ids"] = [weight.trade_commodity_code_id for weight in active_weights]
        return values

    export_months = _monthly_aggregates(
        eligible_rows,
        active_weights=active_weights,
        flow_direction="export",
    )
    import_months = _monthly_aggregates(
        eligible_rows,
        active_weights=active_weights,
        flow_direction="import",
    )
    latest_export = export_months[-1] if export_months else None
    latest_import = import_months[-1] if import_months else None
    if latest_export is None:
        missing_flags["missing_export_volume"] = True
    if latest_import is None:
        missing_flags["missing_import_volume"] = True

    values["export_volume_1m"] = latest_export.volume if latest_export else None
    values["import_volume_1m"] = latest_import.volume if latest_import else None
    values["export_value_usd_1m"] = latest_export.value_usd if latest_export else None
    values["import_value_usd_1m"] = latest_import.value_usd if latest_import else None
    values["export_volume_3m_avg"] = _avg_latest(export_months, 3)
    values["import_volume_3m_avg"] = _avg_latest(import_months, 3)
    values["export_volume_12m_sum"] = _sum_latest(export_months, 12)
    values["import_volume_12m_sum"] = _sum_latest(import_months, 12)
    values["net_export_volume_1m"] = _diff(values["export_volume_1m"], values["import_volume_1m"])
    values["trade_balance_proxy"] = values["net_export_volume_1m"]
    values["average_export_unit_value_usd"] = _unit_value(values["export_value_usd_1m"], values["export_volume_1m"])
    values["average_import_unit_value_usd"] = _unit_value(values["import_value_usd_1m"], values["import_volume_1m"])
    values["china_import_volume_1m"] = _latest_subset_volume(
        eligible_rows,
        active_weights=active_weights,
        flow_direction="import",
        reporter_codes={"CHN"},
    )
    values["major_exporter_volume_1m"] = _latest_subset_volume(
        eligible_rows,
        active_weights=active_weights,
        flow_direction="export",
        reporter_codes=MAJOR_EXPORTER_REPORTERS,
    )
    values["major_importer_volume_1m"] = _latest_subset_volume(
        eligible_rows,
        active_weights=active_weights,
        flow_direction="import",
        reporter_codes=MAJOR_IMPORTER_REPORTERS,
    )
    yoy_base = "export" if latest_export is not None else "import"
    values["trade_yoy_change"] = _yoy_change(export_months if yoy_base == "export" else import_months)

    if values["export_volume_3m_avg"] is None:
        missing_flags["missing_3m_history"] = True
    if values["export_volume_12m_sum"] is None:
        missing_flags["missing_12m_history"] = True
    if values["trade_yoy_change"] is None:
        missing_flags["missing_yoy_history"] = True
    if values["china_import_volume_1m"] is None:
        missing_flags["missing_china_import_proxy"] = True
    if values["major_exporter_volume_1m"] is None:
        missing_flags["missing_major_exporter_proxy"] = True
    if values["major_importer_volume_1m"] is None:
        missing_flags["missing_major_importer_proxy"] = True

    as_of_dates = [_availability_date(row) for row in eligible_rows]
    values["trade_as_of_date"] = max(as_of_dates) if as_of_dates else None
    values["reporting_lag_days"] = (feature_date - values["trade_as_of_date"]).days if values["trade_as_of_date"] else None
    values["missing_flags"] = missing_flags
    values["metadata_json"].update(
        {
            "product_code": product.code,
            "active_trade_code_ids": [weight.trade_commodity_code_id for weight in active_weights],
            "eligible_rows_count": len(eligible_rows),
            "latest_export_period": latest_export.period_start.isoformat() if latest_export else None,
            "latest_import_period": latest_import.period_start.isoformat() if latest_import else None,
        }
    )
    return _normalize_feature_values(values)


def _select_products(session: Session, *, product_code: str | None) -> tuple[Product, ...]:
    statement = select(Product).where(Product.is_active.is_(True)).order_by(Product.code)
    if product_code:
        statement = statement.where(Product.code == product_code)
    products = tuple(session.scalars(statement).all())
    if product_code and not products:
        raise ValueError(f"unknown product code: {product_code}")
    return products


def _feature_date_bounds(session: Session) -> tuple[date, date] | None:
    product_min, product_max = session.execute(
        select(func.min(DailyProductFeature.feature_date), func.max(DailyProductFeature.feature_date))
    ).one()
    if product_min is not None and product_max is not None:
        return product_min, product_max
    flow_min, flow_max = session.execute(select(func.min(TradeFlow.period_end), func.max(TradeFlow.period_end))).one()
    if flow_min is None or flow_max is None:
        return None
    return flow_min, flow_max


def _load_product_trade_weights(session: Session) -> dict[int, list[_TradeWeight]]:
    rows = session.scalars(
        select(ProductTradeCodeWeight)
        .where(ProductTradeCodeWeight.is_active.is_(True))
        .order_by(ProductTradeCodeWeight.product_id, ProductTradeCodeWeight.trade_commodity_code_id)
    ).all()
    by_product: dict[int, list[_TradeWeight]] = {}
    for row in rows:
        by_product.setdefault(row.product_id, []).append(
            _TradeWeight(
                product_id=row.product_id,
                trade_commodity_code_id=row.trade_commodity_code_id,
                weight=row.weight,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
            )
        )
    return by_product


def _load_trade_flows(session: Session, *, to_date: date) -> dict[int, list[TradeFlow]]:
    rows = session.scalars(
        select(TradeFlow)
        .where(TradeFlow.period_start <= to_date, TradeFlow.period_end <= to_date)
        .order_by(TradeFlow.trade_commodity_code_id, TradeFlow.period_start, TradeFlow.id)
    ).all()
    by_code: dict[int, list[TradeFlow]] = {}
    for row in rows:
        by_code.setdefault(row.trade_commodity_code_id, []).append(row)
    return by_code


def _active_weights(weights: list[_TradeWeight], feature_date: date) -> list[_TradeWeight]:
    return [
        weight
        for weight in weights
        if weight.effective_from <= feature_date and (weight.effective_to is None or weight.effective_to >= feature_date)
    ]


def _eligible_rows(
    *,
    active_weights: list[_TradeWeight],
    trade_flows: dict[int, list[TradeFlow]],
    feature_date: date,
) -> list[TradeFlow]:
    result: list[TradeFlow] = []
    active_code_ids = {weight.trade_commodity_code_id for weight in active_weights}
    for code_id in active_code_ids:
        for row in trade_flows.get(code_id, []):
            if row.period_start > feature_date or row.period_end > feature_date:
                continue
            availability = _availability_date(row)
            if availability is None or availability > feature_date:
                continue
            result.append(row)
    return result


def _monthly_aggregates(
    rows: list[TradeFlow],
    *,
    active_weights: list[_TradeWeight],
    flow_direction: str,
    reporter_codes: set[str] | None = None,
) -> list[_MonthlyAggregate]:
    weights_by_code = {weight.trade_commodity_code_id: weight.weight for weight in active_weights}
    grouped: dict[date, dict[str, Any]] = {}
    for row in rows:
        if row.flow_direction != flow_direction:
            continue
        if reporter_codes is not None and row.reporter_code not in reporter_codes:
            continue
        weight = weights_by_code.get(row.trade_commodity_code_id)
        if weight is None:
            continue
        volume = _trade_volume(row)
        if volume is None:
            continue
        bucket = grouped.setdefault(
            row.period_start,
            {
                "period_end": row.period_end,
                "volume": Decimal("0"),
                "value_usd": Decimal("0"),
                "value_rows": 0,
                "as_of_date": _availability_date(row),
                "rows_count": 0,
            },
        )
        bucket["volume"] += volume * weight
        if row.trade_value_usd is not None:
            bucket["value_usd"] += row.trade_value_usd * weight
            bucket["value_rows"] += 1
        availability = _availability_date(row)
        if availability is not None and (bucket["as_of_date"] is None or availability > bucket["as_of_date"]):
            bucket["as_of_date"] = availability
        bucket["rows_count"] += 1
    result = [
        _MonthlyAggregate(
            period_start=period_start,
            period_end=bucket["period_end"],
            volume=bucket["volume"],
            value_usd=bucket["value_usd"] if bucket["value_rows"] else None,
            as_of_date=bucket["as_of_date"] or period_start,
            rows_count=bucket["rows_count"],
        )
        for period_start, bucket in grouped.items()
    ]
    result.sort(key=lambda item: item.period_start)
    return result


def _latest_subset_volume(
    rows: list[TradeFlow],
    *,
    active_weights: list[_TradeWeight],
    flow_direction: str,
    reporter_codes: set[str],
) -> Decimal | None:
    items = _monthly_aggregates(
        rows,
        active_weights=active_weights,
        flow_direction=flow_direction,
        reporter_codes=reporter_codes,
    )
    return items[-1].volume if items else None


def _avg_latest(items: list[_MonthlyAggregate], count: int) -> Decimal | None:
    if len(items) < count:
        return None
    values = [item.volume for item in items[-count:]]
    return sum(values) / Decimal(count)


def _sum_latest(items: list[_MonthlyAggregate], count: int) -> Decimal | None:
    if len(items) < count:
        return None
    return sum(item.volume for item in items[-count:])


def _yoy_change(items: list[_MonthlyAggregate]) -> Decimal | None:
    if not items:
        return None
    current = items[-1]
    previous_year = current.period_start.replace(year=current.period_start.year - 1)
    previous = next((item for item in items if item.period_start == previous_year), None)
    if previous is None or previous.volume == 0:
        return None
    return (current.volume - previous.volume) / previous.volume


def _trade_volume(row: TradeFlow) -> Decimal | None:
    if row.quantity is not None:
        return row.quantity
    if row.net_weight_kg is not None:
        return row.net_weight_kg / Decimal("1000")
    return None


def _availability_date(row: TradeFlow) -> date | None:
    if row.published_at is not None:
        return _to_utc(row.published_at).date()
    if row.fetched_at is not None:
        return _to_utc(row.fetched_at).date()
    return None


def _diff(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return left - right


def _unit_value(value: Decimal | None, volume: Decimal | None) -> Decimal | None:
    if value is None or volume is None or volume == 0:
        return None
    return value / volume


def _feature_row_needs_update(row: DailyTradeFeature, values: dict[str, Any]) -> bool:
    for key, value in values.items():
        if not _values_equal(getattr(row, key), value):
            return True
    return False


def _normalize_feature_values(values: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(values)
    for field in TRADE_NUMERIC_FIELDS:
        normalized[field] = _quant(normalized.get(field))
    return normalized


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, Decimal) or isinstance(right, Decimal):
        return _quant(left) == _quant(right)
    if isinstance(left, datetime) or isinstance(right, datetime):
        if left is None or right is None:
            return left is right
        return _to_utc(left) == _to_utc(right)
    return left == right


def _quant(value: Any, *, scale: int = 8) -> Decimal | None:
    if value is None:
        return None
    quant = Decimal("1").scaleb(-scale)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current = date.fromordinal(current.toordinal() + 1)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

