from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CommodityEvent, DataQualityCheck, NewsArticle, Source
from app.db.session import session_scope
from app.features.news_event_rules import (
    COMMODITY_FAMILY_RULES,
    EVENT_RULES,
    EXTRACTION_METHOD,
    EXTRACTION_VERSION,
    CommodityFamilyRule,
    EventRule,
)
from app.storage.hashes import stable_json_hash


@dataclass(frozen=True)
class MatchedCategory:
    rule: EventRule
    matched_keywords: tuple[str, ...]
    matched_strong_keywords: tuple[str, ...]


@dataclass(frozen=True)
class MatchedCommodityFamily:
    rule: CommodityFamilyRule
    matched_keywords: tuple[str, ...]


@dataclass(frozen=True)
class CandidateCommodityEvent:
    news_article_id: int
    source_id: int
    event_category: str
    commodity_family: str
    affected_products: dict[str, Any]
    country: str | None
    region: str | None
    event_date: date
    published_at: datetime
    direction_hint: str
    severity: Decimal | None
    confidence: Decimal
    lag_bucket: str
    extraction_method: str
    extraction_version: str
    source_text_hash: str
    metadata_json: dict[str, Any]


@dataclass(frozen=True)
class NewsEventExtractionResult:
    articles_scanned: int = 0
    articles_with_events: int = 0
    events_found: int = 0
    events_written: int = 0
    skipped_existing: int = 0
    conflicts_count: int = 0
    errors_count: int = 0
    from_date: str | None = None
    to_date: str | None = None
    source_code: str | None = None
    limit: int | None = None
    article_id: int | None = None
    extraction_version: str = EXTRACTION_VERSION
    dry_run: bool = False


@dataclass
class _ExtractionStats:
    articles_scanned: int = 0
    articles_with_events: int = 0
    events_found: int = 0
    events_written: int = 0
    skipped_existing: int = 0
    conflicts_count: int = 0
    errors: list[str] = field(default_factory=list)


def extract_news_events(
    *,
    session: Session | None = None,
    from_date: date,
    to_date: date,
    source_code: str | None = None,
    limit: int | None = None,
    article_id: int | None = None,
    dry_run: bool = False,
) -> NewsEventExtractionResult:
    _validate_date_range(from_date=from_date, to_date=to_date)
    _validate_limit(limit)
    if session is None:
        with session_scope() as scoped_session:
            return _extract_with_session(
                scoped_session,
                from_date=from_date,
                to_date=to_date,
                source_code=source_code,
                limit=limit,
                article_id=article_id,
                dry_run=dry_run,
            )
    return _extract_with_session(
        session,
        from_date=from_date,
        to_date=to_date,
        source_code=source_code,
        limit=limit,
        article_id=article_id,
        dry_run=dry_run,
    )


def extract_candidates_for_article(article: NewsArticle) -> list[CandidateCommodityEvent]:
    text = build_searchable_text(article)
    normalized_text = normalize_text(text)
    if not normalized_text:
        return []

    source_text_hash = build_source_text_hash(article)
    categories = detect_event_categories(normalized_text)
    commodity_families = detect_commodity_families(normalized_text)
    if not categories or not commodity_families:
        return []

    candidates: list[CandidateCommodityEvent] = []
    for category in categories:
        for family in commodity_families:
            confidence = _confidence(category=category, commodity_family=family)
            candidates.append(
                CandidateCommodityEvent(
                    news_article_id=article.id,
                    source_id=article.source_id,
                    event_category=category.rule.event_category,
                    commodity_family=family.rule.commodity_family,
                    affected_products={
                        "product_codes": list(family.rule.affected_products),
                        "mapping_basis": "commodity_family_keyword",
                    },
                    country=article.country,
                    region=article.region,
                    event_date=_to_utc(article.published_at).date(),
                    published_at=_to_utc(article.published_at),
                    direction_hint=category.rule.direction_hint,
                    severity=category.rule.severity,
                    confidence=confidence,
                    lag_bucket=category.rule.lag_bucket,
                    extraction_method=EXTRACTION_METHOD,
                    extraction_version=EXTRACTION_VERSION,
                    source_text_hash=source_text_hash,
                    metadata_json={
                        "matched_keywords": sorted(set(category.matched_keywords + family.matched_keywords)),
                        "matched_category_rules": {
                            category.rule.event_category: list(category.matched_keywords),
                        },
                        "matched_commodity_keywords": {
                            family.rule.commodity_family: list(family.matched_keywords),
                        },
                        "matched_strong_keywords": list(category.matched_strong_keywords),
                        "severity_label": category.rule.severity_label,
                        "rule_version": EXTRACTION_VERSION,
                        "text_fields_used": _text_fields_used(article),
                        "limitations": [
                            "keyword_rule_only",
                            "event_date_uses_published_at_date",
                            "no_sentiment_model",
                            "no_ml_or_llm_classifier",
                            "english_first_rules",
                        ],
                    },
                )
            )
    return candidates


def detect_event_categories(normalized_text: str) -> list[MatchedCategory]:
    matches: list[MatchedCategory] = []
    for rule in EVENT_RULES:
        if any(_keyword_found(normalized_text, item) for item in rule.negative_keywords):
            continue
        matched_keywords: list[str] = []
        for group in rule.keyword_groups:
            group_matches = tuple(keyword for keyword in group if _keyword_found(normalized_text, keyword))
            if not group_matches:
                matched_keywords = []
                break
            matched_keywords.extend(group_matches)
        if not matched_keywords:
            continue
        strong = tuple(keyword for keyword in rule.strong_keywords if _keyword_found(normalized_text, keyword))
        matches.append(
            MatchedCategory(
                rule=rule,
                matched_keywords=tuple(dict.fromkeys(matched_keywords)),
                matched_strong_keywords=strong,
            )
        )
    return matches


def detect_commodity_families(normalized_text: str) -> list[MatchedCommodityFamily]:
    matches: list[MatchedCommodityFamily] = []
    for rule in COMMODITY_FAMILY_RULES:
        matched = tuple(keyword for keyword in rule.keywords if _keyword_found(normalized_text, keyword))
        if matched:
            matches.append(MatchedCommodityFamily(rule=rule, matched_keywords=matched))
    return matches


def build_searchable_text(article: NewsArticle) -> str:
    return "\n".join(item for item in (article.title, article.summary, article.body_text) if item)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.casefold().split())


def build_source_text_hash(article: NewsArticle) -> str:
    return stable_json_hash(
        {
            "title": normalize_text(article.title),
            "summary": normalize_text(article.summary),
            "body_text": normalize_text(article.body_text),
        }
    )


def _extract_with_session(
    session: Session,
    *,
    from_date: date,
    to_date: date,
    source_code: str | None,
    limit: int | None,
    article_id: int | None,
    dry_run: bool,
) -> NewsEventExtractionResult:
    source_id = _source_id_for_code(session, source_code) if source_code else None
    articles = _select_articles(
        session,
        from_date=from_date,
        to_date=to_date,
        source_id=source_id,
        article_id=article_id,
        limit=limit,
    )
    stats = _ExtractionStats()
    checked_at = datetime.now(timezone.utc)
    for article in articles:
        stats.articles_scanned += 1
        candidates = extract_candidates_for_article(article)
        if not dry_run:
            _write_article_level_checks(session, article=article, candidates=candidates, checked_at=checked_at)
        if not candidates:
            continue
        stats.articles_with_events += 1
        stats.events_found += len(candidates)
        for candidate in candidates:
            if dry_run:
                continue
            _write_candidate_quality_checks(session, candidate=candidate, checked_at=checked_at)
            existing = _find_existing_event(session, candidate)
            if existing is not None:
                if _same_event(existing, candidate):
                    stats.skipped_existing += 1
                    continue
                stats.conflicts_count += 1
                _write_conflict_quality_check(session, existing=existing, candidate=candidate, checked_at=checked_at)
                continue
            session.add(
                CommodityEvent(
                    news_article_id=candidate.news_article_id,
                    source_id=candidate.source_id,
                    event_category=candidate.event_category,
                    commodity_family=candidate.commodity_family,
                    affected_products=candidate.affected_products,
                    country=candidate.country,
                    region=candidate.region,
                    event_date=candidate.event_date,
                    published_at=candidate.published_at,
                    direction_hint=candidate.direction_hint,
                    severity=candidate.severity,
                    confidence=candidate.confidence,
                    lag_bucket=candidate.lag_bucket,
                    extraction_method=candidate.extraction_method,
                    extraction_version=candidate.extraction_version,
                    source_text_hash=candidate.source_text_hash,
                    metadata_json=candidate.metadata_json,
                )
            )
            stats.events_written += 1
            _write_quality_check(
                session,
                source_id=candidate.source_id,
                table_name="commodity_events",
                check_name="news_event_inserted",
                status="pass",
                severity="info",
                details=_candidate_details(candidate),
                checked_at=checked_at,
            )
            session.flush()
    return NewsEventExtractionResult(
        articles_scanned=stats.articles_scanned,
        articles_with_events=stats.articles_with_events,
        events_found=stats.events_found,
        events_written=stats.events_written,
        skipped_existing=stats.skipped_existing,
        conflicts_count=stats.conflicts_count,
        errors_count=len(stats.errors),
        from_date=from_date.isoformat(),
        to_date=to_date.isoformat(),
        source_code=source_code,
        limit=limit,
        article_id=article_id,
        extraction_version=EXTRACTION_VERSION,
        dry_run=dry_run,
    )


def _select_articles(
    session: Session,
    *,
    from_date: date,
    to_date: date,
    source_id: int | None,
    article_id: int | None,
    limit: int | None,
) -> list[NewsArticle]:
    start_at = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(to_date, time.max, tzinfo=timezone.utc)
    statement = select(NewsArticle).where(NewsArticle.published_at >= start_at, NewsArticle.published_at <= end_at)
    if source_id is not None:
        statement = statement.where(NewsArticle.source_id == source_id)
    if article_id is not None:
        statement = statement.where(NewsArticle.id == article_id)
    statement = statement.order_by(NewsArticle.published_at.asc(), NewsArticle.id.asc())
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.scalars(statement).all())


def _source_id_for_code(session: Session, source_code: str) -> int:
    source = session.scalar(select(Source).where(Source.code == source_code))
    if source is None:
        raise ValueError(f"unknown source code: {source_code}")
    return source.id


def _find_existing_event(session: Session, candidate: CandidateCommodityEvent) -> CommodityEvent | None:
    statement = select(CommodityEvent).where(
        CommodityEvent.news_article_id == candidate.news_article_id,
        CommodityEvent.event_category == candidate.event_category,
        CommodityEvent.commodity_family == candidate.commodity_family,
        CommodityEvent.event_date == candidate.event_date,
        CommodityEvent.extraction_method == candidate.extraction_method,
    )
    if candidate.country is None:
        statement = statement.where(CommodityEvent.country.is_(None))
    else:
        statement = statement.where(CommodityEvent.country == candidate.country)
    if candidate.region is None:
        statement = statement.where(CommodityEvent.region.is_(None))
    else:
        statement = statement.where(CommodityEvent.region == candidate.region)
    return session.scalar(statement.limit(1))


def _same_event(existing: CommodityEvent, candidate: CandidateCommodityEvent) -> bool:
    return (
        existing.source_text_hash == candidate.source_text_hash
        and existing.direction_hint == candidate.direction_hint
        and existing.lag_bucket == candidate.lag_bucket
        and _decimal_text(existing.severity) == _decimal_text(candidate.severity)
        and _decimal_text(existing.confidence) == _decimal_text(candidate.confidence)
        and (existing.affected_products or {}) == candidate.affected_products
        and existing.extraction_version == candidate.extraction_version
    )


def _write_article_level_checks(
    session: Session,
    *,
    article: NewsArticle,
    candidates: list[CandidateCommodityEvent],
    checked_at: datetime,
) -> None:
    text = build_searchable_text(article)
    normalized_text = normalize_text(text)
    categories = detect_event_categories(normalized_text)
    families = detect_commodity_families(normalized_text)
    details = {
        "news_article_id": article.id,
        "published_at": _to_utc(article.published_at).isoformat(),
        "event_date": _to_utc(article.published_at).date().isoformat(),
        "matched_categories": [item.rule.event_category for item in categories],
        "matched_commodity_families": [item.rule.commodity_family for item in families],
    }
    _write_quality_check(session, source_id=article.source_id, table_name="commodity_events", check_name="news_event_article_present", status="pass", severity="info", details=details, checked_at=checked_at)
    _write_quality_check(session, source_id=article.source_id, table_name="commodity_events", check_name="news_event_text_present", status="pass" if normalized_text else "skip", severity="info", details={**details, "text_fields_used": _text_fields_used(article)}, checked_at=checked_at)
    _write_quality_check(session, source_id=article.source_id, table_name="commodity_events", check_name="news_event_category_detected", status="pass" if categories else "skip", severity="info", details=details, checked_at=checked_at)
    _write_quality_check(session, source_id=article.source_id, table_name="commodity_events", check_name="news_event_commodity_family_detected", status="pass" if families else "skip", severity="info", details=details, checked_at=checked_at)
    _write_quality_check(session, source_id=article.source_id, table_name="commodity_events", check_name="news_event_published_at_present", status="pass", severity="info", details=details, checked_at=checked_at)
    if not candidates:
        _write_quality_check(session, source_id=article.source_id, table_name="commodity_events", check_name="news_event_no_relevant_event_detected", status="skip", severity="info", details=details, checked_at=checked_at)


def _write_candidate_quality_checks(session: Session, *, candidate: CandidateCommodityEvent, checked_at: datetime) -> None:
    details = _candidate_details(candidate)
    confidence_valid = Decimal("0") <= candidate.confidence <= Decimal("1")
    _write_quality_check(session, source_id=candidate.source_id, table_name="commodity_events", check_name="news_event_event_date_valid", status="pass", severity="info", details=details, checked_at=checked_at)
    _write_quality_check(session, source_id=candidate.source_id, table_name="commodity_events", check_name="news_event_confidence_valid", status="pass" if confidence_valid else "fail", severity="error" if not confidence_valid else "info", details=details, checked_at=checked_at)
    _write_quality_check(session, source_id=candidate.source_id, table_name="commodity_events", check_name="news_event_source_text_hash_present", status="pass" if candidate.source_text_hash else "fail", severity="error" if not candidate.source_text_hash else "info", details=details, checked_at=checked_at)


def _write_conflict_quality_check(
    session: Session,
    *,
    existing: CommodityEvent,
    candidate: CandidateCommodityEvent,
    checked_at: datetime,
) -> None:
    _write_quality_check(
        session,
        source_id=candidate.source_id,
        table_name="commodity_events",
        check_name="commodity_event_existing_rule_hash_changed",
        status="fail",
        severity="warning",
        details={
            "existing_id": existing.id,
            "news_article_id": candidate.news_article_id,
            "event_category": candidate.event_category,
            "commodity_family": candidate.commodity_family,
            "event_date": candidate.event_date.isoformat(),
            "existing_source_text_hash": existing.source_text_hash,
            "incoming_source_text_hash": candidate.source_text_hash,
            "existing_values": _event_values(existing),
            "incoming_values": _candidate_values(candidate),
            "policy_decision": "rejected_rule_hash_conflict_no_overwrite",
        },
        checked_at=checked_at,
    )


def _candidate_details(candidate: CandidateCommodityEvent) -> dict[str, Any]:
    return {
        "news_article_id": candidate.news_article_id,
        "event_category": candidate.event_category,
        "commodity_family": candidate.commodity_family,
        "event_date": candidate.event_date.isoformat(),
        "direction_hint": candidate.direction_hint,
        "lag_bucket": candidate.lag_bucket,
        "confidence": _decimal_text(candidate.confidence),
        "source_text_hash": candidate.source_text_hash,
        "extraction_version": candidate.extraction_version,
    }


def _event_values(existing: CommodityEvent) -> dict[str, Any]:
    return {
        "direction_hint": existing.direction_hint,
        "severity": _decimal_text(existing.severity),
        "confidence": _decimal_text(existing.confidence),
        "lag_bucket": existing.lag_bucket,
        "affected_products": existing.affected_products,
        "source_text_hash": existing.source_text_hash,
        "extraction_version": existing.extraction_version,
    }


def _candidate_values(candidate: CandidateCommodityEvent) -> dict[str, Any]:
    return {
        "direction_hint": candidate.direction_hint,
        "severity": _decimal_text(candidate.severity),
        "confidence": _decimal_text(candidate.confidence),
        "lag_bucket": candidate.lag_bucket,
        "affected_products": candidate.affected_products,
        "source_text_hash": candidate.source_text_hash,
        "extraction_version": candidate.extraction_version,
    }


def _confidence(*, category: MatchedCategory, commodity_family: MatchedCommodityFamily) -> Decimal:
    score = Decimal("0.50") + Decimal("0.10") + Decimal("0.10")
    if category.matched_strong_keywords:
        score += Decimal("0.10")
    if len(commodity_family.matched_keywords) > 1:
        score += Decimal("0.05")
    return min(score, Decimal("0.95"))


def _keyword_found(normalized_text: str, keyword: str) -> bool:
    normalized_keyword = normalize_text(keyword)
    if not normalized_keyword:
        return False
    if " " in normalized_keyword:
        return normalized_keyword in normalized_text
    return re.search(rf"(?<!\w){re.escape(normalized_keyword)}(?!\w)", normalized_text) is not None


def _text_fields_used(article: NewsArticle) -> list[str]:
    fields: list[str] = []
    if article.title:
        fields.append("title")
    if article.summary:
        fields.append("summary")
    if article.body_text:
        fields.append("body_text")
    return fields


def _validate_date_range(*, from_date: date, to_date: date) -> None:
    if from_date > to_date:
        raise ValueError("from_date must be on or before to_date")


def _validate_limit(limit: int | None) -> None:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")


def _write_quality_check(
    session: Session,
    *,
    source_id: int | None,
    table_name: str,
    check_name: str,
    status: str,
    severity: str,
    details: dict[str, Any],
    checked_at: datetime,
) -> None:
    session.add(
        DataQualityCheck(
            source_id=source_id,
            table_name=table_name,
            check_name=check_name,
            checked_at=checked_at,
            status=status,
            severity=severity,
            details_json=details,
        )
    )


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

