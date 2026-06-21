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
from app.features.supply_demand_basket_config import (
    DEFAULT_SUPPLY_DEMAND_COUNTRY_WEIGHTS,
    REVIEWED_TIER_A_SUPPLY_DEMAND_COUNTRY_WEIGHTS,
    SUPPLY_DEMAND_GLOBAL_BASKET_POLICY_VERSION,
    SUPPLY_DEMAND_TIER_A_GLOBAL_BASKET_METRICS,
    SupplyDemandCountryWeight,
    SupplyDemandCountryWeights,
)


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
COUNTRY_BASKET_ADDITIVE_METRICS = {
    "production_volume",
    "beginning_stocks",
    "ending_stocks",
    "imports_volume",
    "exports_volume",
    "domestic_consumption",
    "crush_volume",
    "food_use",
}
SUPPLY_DEMAND_COUNTRY_POLICY_LEGACY = "prefer_WLD_else_weighted_latest_known_rows"
SUPPLY_DEMAND_COUNTRY_POLICY_BASKET = "prefer_WLD_else_configured_country_basket_else_latest_known_country"


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
    commodity_family: str
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
    provenance: dict[str, Any]


@dataclass(frozen=True)
class _MetricComponent:
    metric_weight: _SupplyDemandWeight
    value: Decimal
    rows: tuple[SupplyDemandObservation, ...]
    provenance: dict[str, Any]


def build_supply_demand_daily_features(
    *,
    product_code: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    session: Session | None = None,
    country_weights: SupplyDemandCountryWeights | None = None,
) -> SupplyDemandDailyBuildResult:
    country_weights = DEFAULT_SUPPLY_DEMAND_COUNTRY_WEIGHTS if country_weights is None else country_weights
    if session is None:
        with session_scope() as scoped_session:
            return _build_supply_demand_daily_features_with_session(
                scoped_session,
                product_code=product_code,
                from_date=from_date,
                to_date=to_date,
                country_weights=country_weights,
            )
    return _build_supply_demand_daily_features_with_session(
        session,
        product_code=product_code,
        from_date=from_date,
        to_date=to_date,
        country_weights=country_weights,
    )


def _build_supply_demand_daily_features_with_session(
    session: Session,
    *,
    product_code: str | None,
    from_date: date | None,
    to_date: date | None,
    country_weights: SupplyDemandCountryWeights,
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
                country_weights=country_weights,
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
    country_weights: SupplyDemandCountryWeights,
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
    country_selection_provenance: dict[str, Any] = {}
    selected_country_policy = _selected_country_policy(product.code, weights, country_weights, feature_date)
    for metric_name in SUPPLY_DEMAND_BASE_METRICS:
        field_name = _field_name(metric_name)
        selection = _metric_selection(
            product_code=product.code,
            metric_name=metric_name,
            feature_date=feature_date,
            weights=active_weights,
            observations=observations,
            country_weights=country_weights,
        )
        selections[field_name] = selection
        values[field_name] = selection.value
        used_ids.update(row.id for row in selection.rows)
        if selection.provenance:
            country_selection_provenance[field_name] = selection.provenance

    if values["stock_to_use_ratio"] is None:
        derived_stock_to_use = _ratio(values["ending_stocks"], values["domestic_consumption"])
        if derived_stock_to_use is not None:
            values["stock_to_use_ratio"] = derived_stock_to_use

    values["production_forecast_revision"] = _revision_value(
        product_code=product.code,
        metric_name="production_volume",
        current=selections["production_volume"],
        feature_date=feature_date,
        weights=active_weights,
        observations=observations,
        country_weights=country_weights,
    )
    values["ending_stocks_revision"] = _revision_value(
        product_code=product.code,
        metric_name="ending_stocks",
        current=selections["ending_stocks"],
        feature_date=feature_date,
        weights=active_weights,
        observations=observations,
        country_weights=country_weights,
    )
    values["stock_to_use_revision"] = _revision_value(
        product_code=product.code,
        metric_name="stock_to_use_ratio",
        current=selections["stock_to_use_ratio"],
        feature_date=feature_date,
        weights=active_weights,
        observations=observations,
        country_weights=country_weights,
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
        future_as_of_dates = _future_availability_dates(
            weights=active_weights,
            observations=observations,
            feature_date=feature_date,
        )
        if future_as_of_dates:
            missing_flags["supply_demand_observations_after_feature_date_window"] = True
            values["metadata_json"]["future_supply_demand_as_of_dates"] = [
                item.isoformat() for item in future_as_of_dates
            ]
        else:
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
    if _has_partial_country_basket(selections):
        missing_flags["partial_country_basket"] = True
        missing_flags["supply_demand_global_basket_partial_weight"] = True
    if _has_insufficient_country_basket(selections):
        missing_flags["supply_demand_global_basket_insufficient_weight"] = True

    values["missing_flags"] = missing_flags
    values["metadata_json"].update(
        {
            "product_code": product.code,
            "active_supply_demand_commodity_ids": [weight.supply_demand_commodity_id for weight in active_weights],
            "used_observation_ids": sorted(used_ids),
            "selected_country_policy": selected_country_policy,
            "country_aggregation": country_selection_provenance,
        }
    )
    return _normalize_feature_values(values), used_ids


def _metric_selection(
    *,
    product_code: str,
    metric_name: str,
    feature_date: date,
    weights: list[_SupplyDemandWeight],
    observations: dict[int, list[SupplyDemandObservation]],
    country_weights: SupplyDemandCountryWeights,
    before_as_of: date | None = None,
) -> _MetricSelection:
    metric_weights = [weight for weight in weights if weight.metric_name == metric_name]
    selected: list[_MetricComponent] = []
    for weight in metric_weights:
        candidates = _eligible_rows(
            observations.get(weight.supply_demand_commodity_id, []),
            feature_date=feature_date,
            before_as_of=before_as_of,
        )
        if not candidates:
            continue
        world_rows = [row for row in candidates if row.country_code == "WLD"]
        if world_rows:
            row = _latest_observation(world_rows)
            selected.append(_single_row_component(weight, row, mode="WLD", policy_decision="supply_demand_real_wld"))
            continue
        country_basket = _active_country_weights(
            country_weights,
            product_code=product_code,
            commodity_family=weight.commodity_family,
            feature_date=feature_date,
            metric_name=metric_name,
        )
        if country_basket:
            component, basket_provenance = _country_basket_component(
                metric_weight=weight,
                metric_name=metric_name,
                rows=candidates,
                country_basket=country_basket,
            )
            if component is not None:
                selected.append(component)
            elif basket_provenance is not None:
                return _MetricSelection(
                    value=None,
                    rows=(),
                    as_of_date=None,
                    report_published_at=None,
                    forecast_month=None,
                    marketing_year=None,
                    provenance={"metric_name": metric_name, "components": [basket_provenance]},
                )
            continue
        if metric_name == "stock_to_use_ratio" and _has_active_metric_scoped_country_weights(
            country_weights,
            product_code=product_code,
            commodity_family=weight.commodity_family,
            feature_date=feature_date,
        ):
            continue
        selected.append(
            _single_row_component(
                weight,
                _latest_observation(candidates),
                mode="latest_country_fallback",
                policy_decision="supply_demand_latest_country_fallback",
            )
        )
    if not selected:
        return _empty_selection()

    numerator = Decimal("0")
    denominator = Decimal("0")
    selected_rows: list[SupplyDemandObservation] = []
    components: list[dict[str, Any]] = []
    for component in selected:
        numerator += component.value * component.metric_weight.weight
        denominator += component.metric_weight.weight
        selected_rows.extend(component.rows)
        components.append(component.provenance)
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
        provenance={"metric_name": metric_name, "components": components},
    )


def _revision_value(
    *,
    product_code: str,
    metric_name: str,
    current: _MetricSelection,
    feature_date: date,
    weights: list[_SupplyDemandWeight],
    observations: dict[int, list[SupplyDemandObservation]],
    country_weights: SupplyDemandCountryWeights,
) -> Decimal | None:
    if current.value is None or current.as_of_date is None:
        return None
    previous = _metric_selection(
        product_code=product_code,
        metric_name=metric_name,
        feature_date=feature_date,
        weights=weights,
        observations=observations,
        country_weights=country_weights,
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
    as_of_dates = [_availability_date(row) for row in session.scalars(select(SupplyDemandObservation)).all()]
    as_of_dates = [item for item in as_of_dates if item is not None]
    if product_min is not None and product_max is not None:
        end = max([product_max, *as_of_dates]) if as_of_dates else product_max
        return product_min, end
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
                commodity_family=commodity.commodity_family,
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


def _selected_country_policy(
    product_code: str,
    weights: list[_SupplyDemandWeight],
    country_weights: SupplyDemandCountryWeights,
    feature_date: date,
) -> str:
    for weight in weights:
        if _active_country_weights(
            country_weights,
            product_code=product_code,
            commodity_family=weight.commodity_family,
            feature_date=feature_date,
            metric_name=weight.metric_name,
        ):
            return SUPPLY_DEMAND_COUNTRY_POLICY_BASKET
    return SUPPLY_DEMAND_COUNTRY_POLICY_LEGACY


def _active_country_weights(
    country_weights: SupplyDemandCountryWeights,
    *,
    product_code: str,
    commodity_family: str,
    feature_date: date,
    metric_name: str | None = None,
) -> tuple[SupplyDemandCountryWeight, ...]:
    configured = country_weights.get((product_code, commodity_family), ())
    return tuple(
        item
        for item in configured
        if item.is_active
        and item.product_code == product_code
        and item.commodity_family == commodity_family
        and (metric_name is None or item.metric_code is None or item.metric_code == metric_name)
        and item.effective_from <= feature_date
        and (item.effective_to is None or item.effective_to >= feature_date)
        and item.weight > 0
    )


def _has_active_metric_scoped_country_weights(
    country_weights: SupplyDemandCountryWeights,
    *,
    product_code: str,
    commodity_family: str,
    feature_date: date,
) -> bool:
    configured = country_weights.get((product_code, commodity_family), ())
    return any(
        item.is_active
        and item.product_code == product_code
        and item.commodity_family == commodity_family
        and item.metric_code is not None
        and item.effective_from <= feature_date
        and (item.effective_to is None or item.effective_to >= feature_date)
        and item.weight > 0
        for item in configured
    )


def _single_row_component(
    metric_weight: _SupplyDemandWeight,
    row: SupplyDemandObservation,
    *,
    mode: str,
    policy_decision: str,
) -> _MetricComponent:
    return _MetricComponent(
        metric_weight=metric_weight,
        value=row.metric_value,
        rows=(row,),
        provenance={
            "mode": mode,
            "policy_decision": policy_decision,
            "commodity_family": metric_weight.commodity_family,
            "supply_demand_commodity_id": metric_weight.supply_demand_commodity_id,
            "selected_countries": [row.country_code],
            "used_observation_ids": [row.id],
        },
    )


def _country_basket_component(
    *,
    metric_weight: _SupplyDemandWeight,
    metric_name: str,
    rows: list[SupplyDemandObservation],
    country_basket: tuple[SupplyDemandCountryWeight, ...],
) -> tuple[_MetricComponent | None, dict[str, Any] | None]:
    configured_country_codes = [item.country_code for item in country_basket]
    if metric_name not in COUNTRY_BASKET_ADDITIVE_METRICS:
        return None, None
    configured_weight_total = sum((item.weight for item in country_basket), Decimal("0"))
    minimum_available_weight = max((item.minimum_available_weight for item in country_basket), default=Decimal("0"))
    policy_version = _country_basket_policy_version(country_basket)

    latest_by_country: dict[str, SupplyDemandObservation] = {}
    for country_weight in country_basket:
        country_rows = [row for row in rows if row.country_code == country_weight.country_code]
        if country_rows:
            latest_by_country[country_weight.country_code] = _latest_observation(country_rows)

    selected_pairs = [(item, latest_by_country[item.country_code]) for item in country_basket if item.country_code in latest_by_country]
    selected_country_codes = [row.country_code for _, row in selected_pairs]
    missing_country_codes = [country_code for country_code in configured_country_codes if country_code not in selected_country_codes]
    available_configured_weight = sum((item.weight for item, _ in selected_pairs), Decimal("0"))
    available_approved_basket_weight = available_configured_weight / configured_weight_total if configured_weight_total > 0 else Decimal("0")
    base_provenance = {
        "mode": "configured_country_weighted_basket",
        "policy_decision": policy_version,
        "commodity_family": metric_weight.commodity_family,
        "supply_demand_commodity_id": metric_weight.supply_demand_commodity_id,
        "configured_countries": configured_country_codes,
        "selected_countries": selected_country_codes,
        "missing_configured_countries": missing_country_codes,
        "weights": {item.country_code: str(item.weight) for item in country_basket},
        "configured_weight_total": str(configured_weight_total),
        "available_configured_weight": str(available_configured_weight),
        "available_approved_basket_weight": str(_quant(available_approved_basket_weight)),
        "minimum_available_weight": str(minimum_available_weight),
        "renormalized": bool(missing_country_codes),
        "policy_version": policy_version,
        "source_coverage_threshold": _country_basket_common_decimal(country_basket, "source_coverage_threshold"),
        "proposal_effective_as_of_date": _country_basket_common_date(country_basket, "proposal_effective_as_of_date"),
        "proposal_marketing_years": _country_basket_common_tuple(country_basket, "proposal_marketing_years"),
    }
    if not selected_pairs:
        return None, {
            **base_provenance,
            "policy_decision": "supply_demand_global_basket_insufficient_weight",
            "used_observation_ids": [],
        }
    if available_approved_basket_weight < minimum_available_weight:
        return None, {
            **base_provenance,
            "policy_decision": "supply_demand_global_basket_insufficient_weight",
            "used_observation_ids": [row.id for _, row in selected_pairs],
        }

    denominator = sum((item.weight for item, _ in selected_pairs), Decimal("0"))
    if denominator <= 0:
        return None, {
            **base_provenance,
            "policy_decision": "supply_demand_global_basket_insufficient_weight",
            "used_observation_ids": [row.id for _, row in selected_pairs],
        }
    numerator = sum((row.metric_value * item.weight for item, row in selected_pairs), Decimal("0"))
    selected_rows = tuple(row for _, row in selected_pairs)
    policy_decision = "supply_demand_global_basket_partial_weight" if missing_country_codes else policy_version
    return (
        _MetricComponent(
            metric_weight=metric_weight,
            value=numerator / denominator,
            rows=selected_rows,
            provenance={
                **base_provenance,
                "policy_decision": policy_decision,
                "used_observation_ids": [row.id for row in selected_rows],
            },
        ),
        None,
    )


def _country_basket_policy_version(country_basket: tuple[SupplyDemandCountryWeight, ...]) -> str:
    versions = {item.policy_version for item in country_basket if item.policy_version}
    return sorted(versions)[0] if versions else "configured_country_weighted_basket"


def _country_basket_common_decimal(country_basket: tuple[SupplyDemandCountryWeight, ...], field_name: str) -> str | None:
    values = [getattr(item, field_name) for item in country_basket if getattr(item, field_name) is not None]
    return str(values[0]) if values else None


def _country_basket_common_date(country_basket: tuple[SupplyDemandCountryWeight, ...], field_name: str) -> str | None:
    values = [getattr(item, field_name) for item in country_basket if getattr(item, field_name) is not None]
    return values[0].isoformat() if values else None


def _country_basket_common_tuple(country_basket: tuple[SupplyDemandCountryWeight, ...], field_name: str) -> list[Any]:
    values = [getattr(item, field_name) for item in country_basket if getattr(item, field_name)]
    return list(values[0]) if values else []


def _has_partial_country_basket(selections: dict[str, _MetricSelection]) -> bool:
    for selection in selections.values():
        for component in selection.provenance.get("components", []):
            if component.get("policy_decision") == "supply_demand_global_basket_partial_weight":
                return True
    return False


def _has_insufficient_country_basket(selections: dict[str, _MetricSelection]) -> bool:
    for selection in selections.values():
        for component in selection.provenance.get("components", []):
            if component.get("policy_decision") == "supply_demand_global_basket_insufficient_weight":
                return True
    return False


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


def _future_availability_dates(
    *,
    weights: list[_SupplyDemandWeight],
    observations: dict[int, list[SupplyDemandObservation]],
    feature_date: date,
) -> list[date]:
    commodity_ids = {weight.supply_demand_commodity_id for weight in weights}
    dates: set[date] = set()
    for commodity_id in commodity_ids:
        for row in observations.get(commodity_id, []):
            as_of_date = _availability_date(row)
            if as_of_date is not None and as_of_date > feature_date:
                dates.add(as_of_date)
    return sorted(dates)


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
        provenance={},
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
