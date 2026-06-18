from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, not_, select
from sqlalchemy.orm import Session

from app.db.models import DataQualityCheck
from app.db.session import session_scope

OK_QUALITY_STATUSES = ("pass", "skip", "info")

QUALITY_CLASS_ACTIVE_CURRENT_FAILURE = "active_current_failure"
QUALITY_CLASS_KNOWN_HISTORICAL_INCIDENT = "known_historical_incident"
QUALITY_CLASS_EXPECTED_DIAGNOSTIC_INCIDENT = "expected_diagnostic_incident"
QUALITY_CLASS_PASS = "pass"
QUALITY_CLASS_SKIP = "skip"
QUALITY_CLASS_INFO = "info"

# Explicitly documented production incidents. These are not hidden: they remain
# in summaries, but they no longer make the operational conclusion look like a
# fresh active failure.
CURRENT_PRICE_DNS_INCIDENT_DATE = date(2026, 5, 26)
HISTORICAL_MUTABLE_BAR_INCIDENT_DATE = date(2026, 5, 29)
USDA_PSD_DIAGNOSTIC_INCIDENT_CUTOFF = date(2026, 6, 15)
USDA_PSD_EXPECTED_SKIP_INCIDENT_CUTOFF = date(2026, 6, 18)

CURRENT_PRICE_DNS_CHECKS = {
    "raw_response_present",
    "price_is_not_null",
    "price_positive",
}
HISTORICAL_MUTABLE_BAR_CHECKS = {
    "historical_existing_bar_hash_changed",
    "historical_latest_bar_updated",
    "historical_old_bar_hash_changed",
}
USDA_PSD_DIAGNOSTIC_CHECKS = {
    "supply_demand_content_type_expected",
    "supply_demand_normalized_rows_found",
}
USDA_PSD_EXPECTED_UNSUPPORTED_METRICS = {
    "total_supply",
    "total_distribution",
    "industrial_dom._cons.",
    "feed_waste_dom._cons.",
    "extr._rate,_999.9999",
}
USDA_PSD_KNOWN_MAPPING_GAP_METRICS = {"crush_volume"}


def is_problematic_quality_status(status: str) -> bool:
    return status not in OK_QUALITY_STATUSES


def problematic_quality_filter():
    return not_(DataQualityCheck.status.in_(OK_QUALITY_STATUSES))


def classify_quality_check(check: DataQualityCheck) -> str:
    status = check.status
    if status == "pass":
        return QUALITY_CLASS_PASS
    if status == "skip":
        return QUALITY_CLASS_SKIP
    if status == "info":
        return QUALITY_CLASS_INFO
    if _is_known_current_price_dns_incident(check):
        return QUALITY_CLASS_KNOWN_HISTORICAL_INCIDENT
    if _is_known_historical_mutable_bar_incident(check):
        return QUALITY_CLASS_KNOWN_HISTORICAL_INCIDENT
    if _is_expected_usda_psd_diagnostic_incident(check):
        return QUALITY_CLASS_EXPECTED_DIAGNOSTIC_INCIDENT
    if _is_expected_usda_psd_skip_or_mapping_incident(check):
        return QUALITY_CLASS_EXPECTED_DIAGNOSTIC_INCIDENT
    return QUALITY_CLASS_ACTIVE_CURRENT_FAILURE


def build_quality_summary(*, limit: int = 20, session: Session | None = None) -> dict[str, Any]:
    if session is not None:
        return _build_quality_summary(session, limit=limit)

    with session_scope() as scoped_session:
        return _build_quality_summary(scoped_session, limit=limit)


def _build_quality_summary(session: Session, *, limit: int) -> dict[str, Any]:
    total_checks = session.scalar(select(func.count()).select_from(DataQualityCheck)) or 0
    checks_by_status = _count_by(session, DataQualityCheck.status)
    checks_by_severity = _count_by(session, DataQualityCheck.severity)
    problematic_checks = session.scalars(
        select(DataQualityCheck)
        .where(problematic_quality_filter())
        .order_by(DataQualityCheck.checked_at.desc(), DataQualityCheck.id.desc())
    ).all()
    classified = _classified_problematic_checks(problematic_checks)

    return {
        "total_checks": total_checks,
        "checks_by_status": checks_by_status,
        "checks_by_severity": checks_by_severity,
        "pass_checks": checks_by_status.get("pass", 0),
        "skip_checks": checks_by_status.get("skip", 0),
        "info_checks": checks_by_status.get("info", 0),
        "skip_info_checks": checks_by_status.get("skip", 0) + checks_by_status.get("info", 0),
        "problematic_checks": len(problematic_checks),
        "active_current_failures": len(classified[QUALITY_CLASS_ACTIVE_CURRENT_FAILURE]),
        "active_problematic_checks": len(classified[QUALITY_CLASS_ACTIVE_CURRENT_FAILURE]),
        "known_historical_incidents": len(classified[QUALITY_CLASS_KNOWN_HISTORICAL_INCIDENT]),
        "expected_diagnostic_incidents": len(classified[QUALITY_CLASS_EXPECTED_DIAGNOSTIC_INCIDENT]),
        "classification_counts": {key: len(value) for key, value in classified.items()},
        "last_problematic_checks": [_quality_check_to_dict(check) for check in problematic_checks[:limit]],
        "last_active_problematic_checks": [
            _quality_check_to_dict(check) for check in classified[QUALITY_CLASS_ACTIVE_CURRENT_FAILURE][:limit]
        ],
        "last_known_historical_incidents": [
            _quality_check_to_dict(check) for check in classified[QUALITY_CLASS_KNOWN_HISTORICAL_INCIDENT][:limit]
        ],
        "last_expected_diagnostic_incidents": [
            _quality_check_to_dict(check) for check in classified[QUALITY_CLASS_EXPECTED_DIAGNOSTIC_INCIDENT][:limit]
        ],
        "conclusion": _conclusion(
            active_current_failures=len(classified[QUALITY_CLASS_ACTIVE_CURRENT_FAILURE]),
            known_historical_incidents=len(classified[QUALITY_CLASS_KNOWN_HISTORICAL_INCIDENT]),
            expected_diagnostic_incidents=len(classified[QUALITY_CLASS_EXPECTED_DIAGNOSTIC_INCIDENT]),
        ),
        "message": _message(
            active_current_failures=len(classified[QUALITY_CLASS_ACTIVE_CURRENT_FAILURE]),
            known_historical_incidents=len(classified[QUALITY_CLASS_KNOWN_HISTORICAL_INCIDENT]),
            expected_diagnostic_incidents=len(classified[QUALITY_CLASS_EXPECTED_DIAGNOSTIC_INCIDENT]),
        ),
    }


def _count_by(session: Session, column) -> dict[str, int]:
    rows = session.execute(
        select(column, func.count()).select_from(DataQualityCheck).group_by(column).order_by(column)
    ).all()
    return {str(value): int(count) for value, count in rows}


def _quality_check_to_dict(check: DataQualityCheck) -> dict[str, Any]:
    classification = classify_quality_check(check)
    return {
        "id": check.id,
        "table_name": check.table_name,
        "check_name": check.check_name,
        "status": check.status,
        "severity": check.severity,
        "checked_at": check.checked_at.isoformat(),
        "classification": classification,
        "classification_reason": _classification_reason(check, classification),
        "details_json": check.details_json,
    }


def _classified_problematic_checks(checks: list[DataQualityCheck]) -> dict[str, list[DataQualityCheck]]:
    classified: dict[str, list[DataQualityCheck]] = {
        QUALITY_CLASS_ACTIVE_CURRENT_FAILURE: [],
        QUALITY_CLASS_KNOWN_HISTORICAL_INCIDENT: [],
        QUALITY_CLASS_EXPECTED_DIAGNOSTIC_INCIDENT: [],
    }
    for check in checks:
        classification = classify_quality_check(check)
        if classification in classified:
            classified[classification].append(check)
    return classified


def _conclusion(
    *,
    active_current_failures: int,
    known_historical_incidents: int,
    expected_diagnostic_incidents: int,
) -> str:
    if active_current_failures:
        return "error"
    if known_historical_incidents or expected_diagnostic_incidents:
        return "ok_with_known_incidents"
    return "ok"


def _message(
    *,
    active_current_failures: int,
    known_historical_incidents: int,
    expected_diagnostic_incidents: int,
) -> str:
    if active_current_failures:
        return "quality checks need review"
    if known_historical_incidents or expected_diagnostic_incidents:
        return "quality checks ok with known incidents"
    return "quality checks ok"


def _classification_reason(check: DataQualityCheck, classification: str) -> str | None:
    if classification == QUALITY_CLASS_KNOWN_HISTORICAL_INCIDENT:
        if _is_known_current_price_dns_incident(check):
            return "known_current_price_dns_incident_2026_05_26"
        if _is_known_historical_mutable_bar_incident(check):
            return "known_historical_mutable_latest_bar_incident_2026_05_29"
    if classification == QUALITY_CLASS_EXPECTED_DIAGNOSTIC_INCIDENT:
        if _is_expected_usda_psd_skip_or_mapping_incident(check):
            return "expected_usda_psd_skip_or_mapping_incident_before_phase_6_9k_fix"
        return "expected_usda_psd_diagnostic_probe_incident_before_zip_contract_fix"
    if classification == QUALITY_CLASS_ACTIVE_CURRENT_FAILURE:
        return "fresh_or_unknown_problematic_check"
    return None


def _is_known_current_price_dns_incident(check: DataQualityCheck) -> bool:
    details = _details(check)
    return (
        check.table_name == "price_observations"
        and check.check_name in CURRENT_PRICE_DNS_CHECKS
        and _checked_date(check) == CURRENT_PRICE_DNS_INCIDENT_DATE
        and details.get("raw_response_id") is None
    )


def _is_known_historical_mutable_bar_incident(check: DataQualityCheck) -> bool:
    return (
        check.table_name in {"historical_price_bars", "historical_price_bar_revisions"}
        and check.check_name in HISTORICAL_MUTABLE_BAR_CHECKS
        and _checked_date(check) == HISTORICAL_MUTABLE_BAR_INCIDENT_DATE
    )


def _is_expected_usda_psd_diagnostic_incident(check: DataQualityCheck) -> bool:
    if check.table_name != "raw_responses" or check.check_name not in USDA_PSD_DIAGNOSTIC_CHECKS:
        return False
    if _checked_date(check) > USDA_PSD_DIAGNOSTIC_INCIDENT_CUTOFF:
        return False
    details = _details(check)
    request = details.get("request")
    if not isinstance(request, dict) or request.get("live_probe") is not True:
        return False
    error = str(details.get("error") or "").lower()
    content_type = str(details.get("content_type") or "").lower()
    return (
        "html shell" in error
        or "downloadable dataset metadata" in error
        or "json response root is not an object" in error
        or "metadata" in error
        or "text/html" in content_type
    )


def _is_expected_usda_psd_skip_or_mapping_incident(check: DataQualityCheck) -> bool:
    if _checked_date(check) > USDA_PSD_EXPECTED_SKIP_INCIDENT_CUTOFF:
        return False
    details = _details(check)
    request = details.get("request")
    if not isinstance(request, dict) or request.get("live_probe") is not True:
        return False

    if check.table_name == "supply_demand_observations" and check.check_name == "supply_demand_malformed_row_skipped":
        if details.get("category") == "expected_unsupported_metric":
            return True
        error = str(details.get("error") or "").lower()
        return any(metric in error for metric in USDA_PSD_EXPECTED_UNSUPPORTED_METRICS)

    if check.table_name == "supply_demand_commodities" and check.check_name == "supply_demand_mapping_found":
        metric_name = str(details.get("metric_name") or "")
        product_code = str(details.get("product_code") or "")
        return metric_name in USDA_PSD_KNOWN_MAPPING_GAP_METRICS and product_code in {"soybean_oil", "rapeseed_oil"}

    return False


def _checked_date(check: DataQualityCheck) -> date:
    return check.checked_at.date()


def _details(check: DataQualityCheck) -> dict[str, Any]:
    return check.details_json if isinstance(check.details_json, dict) else {}
