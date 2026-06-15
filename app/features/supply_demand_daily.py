from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DailyProductFeature,
    DailySupplyDemandFeature,
    Product,
    ProductSupplyDemandWeight,
    SupplyDemandCommodity,
    SupplyDemandObservation,
)
from app.db.session import session_scope


SUPPLY_DEMAND_DAILY_FEATURE_VERSION = "supply_demand_daily_features_v1"
SUPPLY_DEMAND_NUMERIC_FIELDS = (
    "production_volume",
    "domestic_consumption",
    "food_use",
    "feed_use",
    "crush_volume",
    "exports_volume",
    "imports_volume",
    "beginning_stocks",
    "ending_stocks",
    "stock_to_use_ratio",
    "planted_area",
    "harvested_area",
    "yield_value",
    "production_forecast_revision",
    "ending_stocks_revision",
    "stock_to_use_revision",
)
SUPPLY_DEMAND_BASE_METRICS = (
    "production_volume",
    "domestic_consumption",
    "food_use",
    "feed_use",
    "crush_volume",
    "exports_volume",
    "imports_volume",
    "beginning_stocks",
    "ending_stocks",
    "stock_to_use_ratio",
    "planted_area",
    "harvested_area",
    "yield",
)
METRIC_FIELD_BY_NAME = {
    "yield": "yield_value",
}


@dataclass(frozen=True)
class SupplyDemandDailyBuildResult:
    products_processed: int = 0
    dates_processed: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    warnings_count: int = 0
    missing_products: list[str] = field(default_factory=list)
    observations_used: int = 0


@dataclass(frozen=True)
class _SupplyDemandWeight:
    product_id: int
    supply_demand_commodity_id: int
    metric_name: str
    metric_group: str
    weight: Decimal
    effective_from: date
    effective_to: date | None


@dataclass(frozen=True)
class _MetricSelection:
    value: Decimal | None
    rows: tuple[SupplyDemandObservation, ...]
    as_of_date: date | None
    report_published_at: datetime | None
    forecast_month: int | None
    marketing_year: str | None


def build_supply_demand_daily_features(
    *,
    product_code: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    session: Session | None = None,
) -> SupplyDemandDailyBuildResult:
    if session is None:
        with session_scope() as scoped_session:
            return _build_supply_demand_daily_features_with_session(
                scoped_session,
                product_code=product_code,
                from_date=from_date,
                to_date=to_date,
            )
    return _build_supply_demand_daily_features_with_session(
        session,
        product_code=product_code,
        from_date=from_date,
        to_date=to_date,
    )


def _build_supply_demand_daily_features_with_session(
    session: Session,
    *,
    product_code: str | None,
    from_date: date | None,
    to_date: date | None,
) -> SupplyDemandDailyBuildResult:
    products = _select_products(session, product_code=product_code)
    if not products:
        return SupplyDemandDailyBuildResult()
    if from_date is not None and to_date is not None and from_date > to_date:
        raise ValueError("from_date must be on or before to_date")

    bounds = _feature_date_bounds(session)
    if bounds is None and (from_date is None or to_date is None):
        return SupplyDemandDailyBuildResult(products_processed=len(products))
    start = from_date or bounds[0]
    end = to_date or bounds[1]
    if start > end:
        raise ValueError("from_date must be on or before to_date")

    feature_dates = tuple(_date_range(start, end))
    weights = _load_product_supply_demand_weights(session)
    observations = _load_supply_demand_observations(session)
    checked_at = datetime.now(timezone.utc)

    rows_created = 0
    rows_updated = 0
    rows_skipped = 0
    warnings_count = 0
    missing_products: set[str] = set()
    observations_used: set[int] = set()

    for product in products:
        product_has_supply_demand_data = False
        product_weights = weights.get(product.id, [])
        for feature_date in feature_dates:
            values, used_ids = _feature_values(
                product=product,
                feature_date=feature_date,
                weights=product_weights,
                observations=observations,
            )
            observations_used.update(used_ids)
            if values["missing_flags"]:
                warnings_count += 1
            if values["supply_demand_as_of_date"] is not None:
                product_has_supply_demand_data = True
            existing = session.scalar(
                select(DailySupplyDemandFeature)
                .where(DailySupplyDemandFeature.product_id == product.id, DailySupplyDemandFeature.feature_date == feature_date)
                .limit(1)
            )
            if existing is None:
                session.add(DailySupplyDemandFeature(product_id=product.id, feature_date=feature_date, **values))
                rows_created += 1
            elif _feature_row_needs_update(existing, values):
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.updated_at = checked_at
                rows_updated += 1
            else:
                rows_skipped += 1
            session.flush()
        if not product_has_supply_demand_data:
            missing_products.add(product.code)

    return SupplyDemandDailyBuildResult(
        products_processed=len(products),
        dates_processed=len(feature_dates),
        rows_created=rows_created,
        rows_updated=rows_updated,
        rows_skipped=rows_skipped,
        warnings_count=warnings_count,
        missing_products=sorted(missing_products),
        observations_used=len(observations_used),
    )


def _feature_values(
    *,
    product: Product,
    feature_date: date,
    weights: list[_SupplyDemandWeight],
    observations: dict[int, list[SupplyDemandObservation]],
) -> tuple[dict[str, Any], set[int]]:
    values: dict[str, Any] = {field: None for field in SUPPLY_DEMAND_NUMERIC_FIELDS}
    values.update(
        {
            "forecast_month": None,
            "marketing_year": None,
            "report_published_at": None,
            "supply_demand_as_of_date": None,
            "reporting_lag_days": None,
            "missing_flags": {},
            "metadata_json": {
                "feature_version": SUPPLY_DEMAND_DAILY_FEATURE_VERSION,
                "source_table": "supply_demand_observations",
                "availability_policy": "report_published_at_date_else_published_at_date_else_fetched_at_date <= feature_date",
            },
        }
    )
    missing_flags: dict[str, bool] = {}
    used_ids: set[int] = set()
    active_weights = _active_weights(weights, feature_date)
    if not active_weights:
        missing_flags["no_product_supply_demand_weights"] = True
        values["missing_flags"] = missing_flags
        values["metadata_json"]["product_code"] = product.code
        return values, used_ids

    selections: dict[str, _MetricSelection] = {}
    for metric_name in SUPPLY_DEMAND_BASE_METRICS:
        field_name = _field_name(metric_name)
        selection = _metric_selection(
            metric_name=metric_name,
            feature_date=feature_date,
            weights=active_weights,
            observations=observations,
        )
        selections[field_name] = selection
        values[field_name] = selection.value
        used_ids.update(row.id for row in selection.rows)

    if values["stock_to_use_ratio"] is None:
        derived_stock_to_use = _ratio(values["ending_stocks"], values["domestic_consumption"])
        if derived_stock_to_use is not None:
            values["stock_to_use_ratio"] = derived_stock_to_use

    values["production_forecast_revision"] = _revision_value(
        metric_name="production_volume",
        current=selections["production_volume"],
        feature_date=feature_date,
        weights=active_weights,
        observations=observations,
    )
    values["ending_stocks_revision"] = _revision_value(
        metric_name="ending_stocks",
        current=selections["ending_stocks"],
        feature_date=feature_date,
        weights=active_weights,
        observations=observations,
    )
    values["stock_to_use_revision"] = _revision_value(
        metric_name="stock_to_use_ratio",
        current=selections["stock_to_use_ratio"],
        feature_date=feature_date,
        weights=active_weights,
        observations=observations,
    )

    used_rows = [row for selection in selections.values() for row in selection.rows]
    as_of_dates = [_availability_date(row) for row in used_rows]
    as_of_dates = [item for item in as_of_dates if item is not None]
    values["supply_demand_as_of_date"] = max(as_of_dates) if as_of_dates else None
    values["reporting_lag_days"] = (
        (feature_date - values["supply_demand_as_of_date"]).days if values["supply_demand_as_of_date"] else None
    )
    values["report_published_at"] = _latest_datetime([row.report_published_at for row in used_rows])
    values["forecast_month"] = _latest_int([row.report_month for row in used_rows])
    values["marketing_year"] = _latest_marketing_year(used_rows)

    if not used_rows:
        missing_flags["no_supply_demand_observations"] = True
    if values["production_volume"] is None:
        missing_flags["missing_production_volume"] = True
    if values["domestic_consumption"] is None:
        missing_flags["missing_domestic_consumption"] = True
    if values["crush_volume"] is None:
        missing_flags["missing_crush_volume"] = True
    if values["exports_volume"] is None:
        missing_flags["missing_exports_volume"] = True
    if values["imports_volume"] is None:
        missing_flags["missing_imports_volume"] = True
    if values["ending_stocks"] is None:
        missing_flags["missing_ending_stocks"] = True
    if values["stock_to_use_ratio"] is None:
        missing_flags["missing_stock_to_use_ratio"] = True
    if values["planted_area"] is None or values["harvested_area"] is None or values["yield_value"] is None:
        missing_flags["missing_area_yield"] = True
    if (
        values["production_forecast_revision"] is None
        or values["ending_stocks_revision"] is None
        or values["stock_to_use_revision"] is None
    ):
        missing_flags["missing_forecast_revision"] = True
    if used_rows and all(row.report_published_at is None and row.published_at is None for row in used_rows):
        missing_flags["missing_report_publication_date"] = True
    if values["supply_demand_as_of_date"] is None:
        missing_flags["missing_supply_demand_as_of_date"] = True

    values["missing_flags"] = missing_flags
    values["metadata_json"].update(
        {
            "product_code": product.code,
            "active_supply_demand_commodity_ids": [weight.supply_demand_commodity_id for weight in active_weights],
            "used_observation_ids": sorted(used_ids),
            "selected_country_policy": "prefer_WLD_else_weighted_latest_known_rows",
        }
    )
    return _normalize_feature_values(values), used_ids


def _metric_selection(
    *,
    metric_name: str,
    feature_date: date,
    weights: list[_SupplyDemandWeight],
    observations: dict[int, list[SupplyDemandObservation]],
    before_as_of: date | None = None,
) -> _MetricSelection:
    metric_weights = [weight for weight in weights if weight.metric_name == metric_name]
    selected: list[tuple[_SupplyDemandWeight, SupplyDemandObservation]] = []
    for weight in metric_weights:
        candidates = _eligible_rows(
            observations.get(weight.supply_demand_commodity_id, []),
            feature_date=feature_date,
            before_as_of=before_as_of,
        )
        if not candidates:
            continue
        world_rows = [row for row in candidates if row.country_code == "WLD"]
        selected.append((weight, _latest_observation(world_rows or candidates)))
    if not selected:
        return _empty_selection()

    numerator = Decimal("0")
    denominator = Decimal("0")
    selected_rows: list[SupplyDemandObservation] = []
    for weight, row in selected:
        numerator += row.metric_value * weight.weight
        denominator += weight.weight
        selected_rows.append(row)
    value = numerator / denominator if denominator else None
    as_of_dates = [_availability_date(row) for row in selected_rows]
    report_published_at = _latest_datetime([row.report_published_at for row in selected_rows])
    return _MetricSelection(
        value=value,
        rows=tuple(selected_rows),
        as_of_date=max(item for item in as_of_dates if item is not None) if any(as_of_dates) else None,
        report_published_at=report_published_at,
        forecast_month=_latest_int([row.report_month for row in selected_rows]),
        marketing_year=_latest_marketing_year(selected_rows),
    )


def _revision_value(
    *,
    metric_name: str,
    current: _MetricSelection,
    feature_date: date,
    weights: list[_SupplyDemandWeight],
    observations: dict[int, list[SupplyDemandObservation]],
) -> Decimal | None:
    if current.value is None or current.as_of_date is None:
        return None
    previous = _metric_selection(
        metric_name=metric_name,
        feature_date=feature_date,
        weights=weights,
        observations=observations,
        before_as_of=current.as_of_date,
    )
    if previous.value is None:
        return None
    return current.value - previous.value


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
    as_of_dates = [_availability_date(row) for row in session.scalars(select(SupplyDemandObservation)).all()]
    as_of_dates = [item for item in as_of_dates if item is not None]
    if not as_of_dates:
        return None
    return min(as_of_dates), max(as_of_dates)


def _load_product_supply_demand_weights(session: Session) -> dict[int, list[_SupplyDemandWeight]]:
    rows = session.execute(
        select(ProductSupplyDemandWeight, SupplyDemandCommodity)
        .join(SupplyDemandCommodity, SupplyDemandCommodity.id == ProductSupplyDemandWeight.supply_demand_commodity_id)
        .where(ProductSupplyDemandWeight.is_active.is_(True), SupplyDemandCommodity.is_active.is_(True))
        .order_by(ProductSupplyDemandWeight.product_id, ProductSupplyDemandWeight.supply_demand_commodity_id)
    ).all()
    by_product: dict[int, list[_SupplyDemandWeight]] = {}
    for weight, commodity in rows:
        by_product.setdefault(weight.product_id, []).append(
            _SupplyDemandWeight(
                product_id=weight.product_id,
                supply_demand_commodity_id=weight.supply_demand_commodity_id,
                metric_name=commodity.metric_name,
                metric_group=commodity.metric_group,
                weight=weight.weight,
                effective_from=weight.effective_from,
                effective_to=weight.effective_to,
            )
        )
    return by_product


def _load_supply_demand_observations(session: Session) -> dict[int, list[SupplyDemandObservation]]:
    rows = session.scalars(
        select(SupplyDemandObservation).order_by(
            SupplyDemandObservation.supply_demand_commodity_id,
            SupplyDemandObservation.marketing_year,
            SupplyDemandObservation.report_year,
            SupplyDemandObservation.report_month,
            SupplyDemandObservation.id,
        )
    ).all()
    by_commodity: dict[int, list[SupplyDemandObservation]] = {}
    for row in rows:
        by_commodity.setdefault(row.supply_demand_commodity_id, []).append(row)
    return by_commodity


def _active_weights(weights: list[_SupplyDemandWeight], feature_date: date) -> list[_SupplyDemandWeight]:
    return [
        weight
        for weight in weights
        if weight.effective_from <= feature_date and (weight.effective_to is None or weight.effective_to >= feature_date)
    ]


def _eligible_rows(
    rows: list[SupplyDemandObservation],
    *,
    feature_date: date,
    before_as_of: date | None,
) -> list[SupplyDemandObservation]:
    result = []
    for row in rows:
        as_of_date = _availability_date(row)
        if as_of_date is None or as_of_date > feature_date:
            continue
        if before_as_of is not None and as_of_date >= before_as_of:
            continue
        result.append(row)
    return result


def _latest_observation(rows: list[SupplyDemandObservation]) -> SupplyDemandObservation:
    return sorted(
        rows,
        key=lambda row: (
            _availability_date(row) or date.min,
            row.report_year,
            row.report_month,
            row.id,
        ),
    )[-1]


def _availability_date(row: SupplyDemandObservation) -> date | None:
    if row.report_published_at is not None:
        return _to_utc(row.report_published_at).date()
    if row.published_at is not None:
        return _to_utc(row.published_at).date()
    if row.fetched_at is not None:
        return _to_utc(row.fetched_at).date()
    return None


def _field_name(metric_name: str) -> str:
    return METRIC_FIELD_BY_NAME.get(metric_name, metric_name)


def _empty_selection() -> _MetricSelection:
    return _MetricSelection(
        value=None,
        rows=(),
        as_of_date=None,
        report_published_at=None,
        forecast_month=None,
        marketing_year=None,
    )


def _latest_datetime(values: list[datetime | None]) -> datetime | None:
    present = [_to_utc(item) for item in values if item is not None]
    return max(present) if present else None


def _latest_int(values: list[int | None]) -> int | None:
    present = [item for item in values if item is not None]
    return max(present) if present else None


def _latest_marketing_year(rows: list[SupplyDemandObservation]) -> str | None:
    if not rows:
        return None
    latest = _latest_observation(rows)
    return latest.marketing_year


def _ratio(numerator: Any, denominator: Any) -> Decimal | None:
    if numerator is None or denominator is None:
        return None
    denominator = Decimal(denominator)
    if denominator == 0:
        return None
    return Decimal(numerator) / denominator


def _feature_row_needs_update(row: DailySupplyDemandFeature, values: dict[str, Any]) -> bool:
    for key, value in values.items():
        if not _values_equal(getattr(row, key), value):
            return True
    return False


def _normalize_feature_values(values: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(values)
    for field in SUPPLY_DEMAND_NUMERIC_FIELDS:
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
