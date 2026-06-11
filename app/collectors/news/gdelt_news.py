from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector, CollectorResult
from app.collectors.news.gdelt_config import (
    COLLECTOR_NAME,
    DEFAULT_MAXRECORDS,
    ENDPOINT,
    GDELT_QUERY_PRESETS,
    HEADERS,
    MAX_DATE_RANGE_DAYS,
    MAX_MAXRECORDS,
    PARSER_VERSION,
    REQUEST_TIMEOUT,
    SOURCE_CODE,
    SOURCE_MODE,
    GdeltQueryPreset,
    gdelt_doc_params,
    gdelt_doc_url,
    get_query_preset,
)
from app.db.models import CollectorRun, DataQualityCheck, NewsArticle, RawResponse, Source
from app.db.session import session_scope
from app.storage.hashes import stable_json_hash
from app.storage.raw_store import RawStore

logger = logging.getLogger(__name__)


class GdeltNewsParseError(ValueError):
    """Raised when a GDELT DOC response cannot be parsed safely."""


class HttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        ...


@dataclass(frozen=True)
class GdeltRequest:
    query_key: str | None
    query_string: str
    commodity_family_hint: str | None
    affected_products_hint: tuple[str, ...]
    language: str | None
    from_date: date
    to_date: date
    maxrecords: int


@dataclass(frozen=True)
class ParsedGdeltArticle:
    external_id: str | None
    url: str
    canonical_url: str | None
    title: str
    summary: str | None
    body_text: str | None
    language: str
    source_name: str
    country: str | None
    region: str | None
    published_at: datetime
    raw: dict[str, Any]
    published_at_source_field: str


@dataclass(frozen=True)
class GdeltResponseCheck:
    check_name: str
    status: str
    severity: str
    details: dict[str, Any]


@dataclass(frozen=True)
class GdeltNewsCollectorResult(CollectorResult):
    query_key: str | None = None
    query: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    maxrecords: int = DEFAULT_MAXRECORDS
    skipped_existing: int = 0
    conflicts_count: int = 0
    skipped_malformed: int = 0


@dataclass
class _NewsStats:
    records_found: int = 0
    records_written: int = 0
    skipped_existing: int = 0
    conflicts_count: int = 0
    skipped_malformed: int = 0
    raw_response_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class GdeltNewsCollector(BaseCollector):
    source_code = SOURCE_CODE
    collector_name = COLLECTOR_NAME
    parser_version = PARSER_VERSION

    def __init__(
        self,
        *,
        http_client: HttpClient | None = None,
        raw_store: RawStore | None = None,
        timeout: float = REQUEST_TIMEOUT,
        clock: Any | None = None,
    ) -> None:
        super().__init__()
        self.http_client = http_client or httpx.Client(follow_redirects=True)
        self.raw_store = raw_store or RawStore()
        self.timeout = timeout
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        session: Session | None = None,
        *,
        query_key: str | None = None,
        query: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        maxrecords: int | None = None,
        run_type: str = "manual",
    ) -> GdeltNewsCollectorResult:
        run_type = _normalize_run_type(run_type)
        request = build_gdelt_request(
            query_key=query_key,
            query=query,
            from_date=from_date,
            to_date=to_date,
            maxrecords=maxrecords,
        )
        if session is None:
            with session_scope() as scoped_session:
                return self._run_with_session(scoped_session, request=request, run_type=run_type)
        return self._run_with_session(session, request=request, run_type=run_type)

    def _run_with_session(self, session: Session, *, request: GdeltRequest, run_type: str) -> GdeltNewsCollectorResult:
        started_at = _to_utc(self.clock())
        source = session.scalar(select(Source).where(Source.code == self.source_code))
        collector_run = CollectorRun(
            source_id=source.id if source else None,
            collector_name=self.collector_name,
            started_at=started_at,
            status="running",
            run_type=run_type,
            collection_slot=None,
        )
        session.add(collector_run)
        session.flush()

        if source is None:
            message = f"source mapping not found: {self.source_code}"
            _write_quality_check(
                session,
                source_id=None,
                table_name="sources",
                check_name="news_source_mapping_found",
                status="fail",
                severity="error",
                details={"source_code": self.source_code},
                checked_at=started_at,
            )
            collector_run.status = "error"
            collector_run.finished_at = _to_utc(self.clock())
            collector_run.error_message = message
            session.flush()
            return _result_from_run(self, collector_run, started_at, request=request, errors_count=1)

        _write_request_quality_checks(session, source=source, request=request, checked_at=started_at)
        stats = self._collect_query(session, source, collector_run, request)

        collector_run.finished_at = _to_utc(self.clock())
        collector_run.records_found = stats.records_found
        collector_run.records_written = stats.records_written
        if not stats.errors and stats.conflicts_count == 0:
            collector_run.status = "success"
        elif stats.records_found > 0 or stats.records_written > 0:
            collector_run.status = "partial_success"
        else:
            collector_run.status = "error"
        collector_run.error_message = "\n".join(stats.errors) if stats.errors else None
        session.flush()

        return GdeltNewsCollectorResult(
            run_id=collector_run.id,
            source_code=self.source_code,
            collector_name=self.collector_name,
            parser_version=self.parser_version,
            started_at=started_at,
            finished_at=collector_run.finished_at,
            status=collector_run.status,
            records_found=stats.records_found,
            records_written=stats.records_written,
            raw_response_ids=stats.raw_response_ids,
            error_message=collector_run.error_message,
            errors_count=len(stats.errors),
            query_key=request.query_key,
            query=request.query_string,
            from_date=request.from_date.isoformat(),
            to_date=request.to_date.isoformat(),
            maxrecords=request.maxrecords,
            skipped_existing=stats.skipped_existing,
            conflicts_count=stats.conflicts_count,
            skipped_malformed=stats.skipped_malformed,
        )

    def _collect_query(
        self,
        session: Session,
        source: Source,
        collector_run: CollectorRun,
        request: GdeltRequest,
    ) -> _NewsStats:
        stats = _NewsStats()
        params = gdelt_doc_params(
            query=request.query_string,
            from_date=request.from_date,
            to_date=request.to_date,
            maxrecords=request.maxrecords,
        )
        try:
            response = self.http_client.get(ENDPOINT, params=params, headers=HEADERS, timeout=self.timeout)
            fetched_at = _to_utc(self.clock())
        except httpx.TimeoutException as exc:
            stats.errors.append(f"GDELT request timeout: {exc}")
            return stats
        except httpx.RequestError as exc:
            stats.errors.append(f"GDELT connection error: {exc}")
            return stats

        raw_response = self._save_raw_response(session, source, collector_run, response, fetched_at)
        stats.raw_response_ids.append(raw_response.id)

        articles, malformed, checks = assess_gdelt_response(
            payload=response.content,
            content_type=response.headers.get("content-type"),
            status_code=response.status_code,
            request=request,
            fetched_at=fetched_at,
        )
        stats.skipped_malformed = len(malformed)
        _write_response_checks(
            session,
            source_id=source.id,
            raw_response_id=raw_response.id,
            request=request,
            checks=checks,
            checked_at=fetched_at,
        )
        _write_malformed_article_checks(
            session,
            source_id=source.id,
            raw_response_id=raw_response.id,
            request=request,
            malformed=malformed,
            checked_at=fetched_at,
        )
        if response.status_code != 200:
            stats.errors.append(f"GDELT HTTP status {response.status_code}; url={_response_url(response)}")
            return stats
        if not articles and _has_parser_error(checks):
            stats.errors.append("GDELT response parser produced no article rows")
            return stats

        request_url = _response_url(response)
        for article in articles:
            stats.records_found += 1
            article_hash = build_article_hash(article)
            source_record_hash = build_news_source_record_hash(source_code=self.source_code, article=article)
            _write_article_quality_checks(
                session,
                source_id=source.id,
                raw_response_id=raw_response.id,
                article=article,
                article_hash=article_hash,
                checked_at=fetched_at,
            )
            existing = _find_existing_article(
                session,
                source_id=source.id,
                external_id=article.external_id,
                article_hash=article_hash,
            )
            if existing is not None:
                if existing.source_record_hash == source_record_hash:
                    stats.skipped_existing += 1
                    continue
                stats.conflicts_count += 1
                _write_article_conflict_check(
                    session,
                    source_id=source.id,
                    raw_response_id=raw_response.id,
                    existing=existing,
                    incoming=article,
                    incoming_article_hash=article_hash,
                    incoming_source_record_hash=source_record_hash,
                    checked_at=fetched_at,
                )
                continue

            session.add(
                NewsArticle(
                    source_id=source.id,
                    raw_response_id=raw_response.id,
                    collector_run_id=collector_run.id,
                    external_id=article.external_id,
                    url=article.url,
                    canonical_url=article.canonical_url,
                    title=article.title,
                    summary=article.summary,
                    body_text=article.body_text,
                    language=article.language,
                    source_name=article.source_name,
                    country=article.country,
                    region=article.region,
                    published_at=article.published_at,
                    fetched_at=fetched_at,
                    article_hash=article_hash,
                    source_record_hash=source_record_hash,
                    source_payload_hash=raw_response.sha256,
                    metadata_json=_metadata_json(
                        article=article,
                        request=request,
                        raw_response=raw_response,
                        request_url=request_url,
                        identity_strategy="external_id" if article.external_id else "article_hash",
                    ),
                )
            )
            stats.records_written += 1
            session.flush()
        return stats

    def _save_raw_response(
        self,
        session: Session,
        source: Source,
        collector_run: CollectorRun,
        response: httpx.Response,
        fetched_at: datetime,
    ) -> RawResponse:
        content_type = response.headers.get("content-type")
        raw_result = self.raw_store.save_bytes(
            source_code=self.source_code,
            collector_run_id=collector_run.id,
            payload=response.content,
            fetched_at=fetched_at,
            extension="json",
            content_type=content_type,
        )
        raw_response = RawResponse(
            source_id=source.id,
            collector_run_id=collector_run.id,
            fetched_at=fetched_at,
            url=_response_url(response),
            method="GET",
            status_code=response.status_code,
            content_type=content_type,
            storage_path=raw_result.storage_path,
            sha256=raw_result.sha256,
            bytes_size=raw_result.bytes_size,
            parser_version=self.parser_version,
        )
        session.add(raw_response)
        session.flush()
        return raw_response


def build_gdelt_request(
    *,
    query_key: str | None,
    query: str | None,
    from_date: date | None,
    to_date: date | None,
    maxrecords: int | None,
) -> GdeltRequest:
    if (query_key is None or not query_key.strip()) and (query is None or not query.strip()):
        raise ValueError("either query_key or query is required for gdelt_news")
    if query_key and query and query_key.strip() and query.strip():
        raise ValueError("query_key and custom query cannot be combined for gdelt_news")
    if from_date is None or to_date is None:
        raise ValueError("from_date and to_date are required for gdelt_news")
    validate_gdelt_date_range(from_date=from_date, to_date=to_date)
    if query_key and query_key.strip():
        preset = get_query_preset(query_key.strip())
        resolved_maxrecords = maxrecords if maxrecords is not None else preset.maxrecords_default
        validate_maxrecords(resolved_maxrecords)
        return _request_from_preset(preset, from_date=from_date, to_date=to_date, maxrecords=resolved_maxrecords)

    resolved_query = (query or "").strip()
    resolved_maxrecords = maxrecords if maxrecords is not None else DEFAULT_MAXRECORDS
    validate_maxrecords(resolved_maxrecords)
    return GdeltRequest(
        query_key=None,
        query_string=resolved_query,
        commodity_family_hint=None,
        affected_products_hint=(),
        language=None,
        from_date=from_date,
        to_date=to_date,
        maxrecords=resolved_maxrecords,
    )


def validate_gdelt_date_range(*, from_date: date, to_date: date, max_days: int = MAX_DATE_RANGE_DAYS) -> None:
    if from_date > to_date:
        raise ValueError("from_date must be on or before to_date")
    days_count = (to_date - from_date).days + 1
    if days_count > max_days:
        raise ValueError(f"date range exceeds max allowed days: {days_count} > {max_days}")


def validate_maxrecords(value: int, *, maximum: int = MAX_MAXRECORDS) -> None:
    if value <= 0:
        raise ValueError("maxrecords must be positive")
    if value > maximum:
        raise ValueError(f"maxrecords must be <= {maximum}")


def assess_gdelt_response(
    *,
    payload: bytes,
    content_type: str | None,
    status_code: int | None,
    request: GdeltRequest,
    fetched_at: datetime,
) -> tuple[list[ParsedGdeltArticle], list[dict[str, Any]], list[GdeltResponseCheck]]:
    checks: list[GdeltResponseCheck] = [
        GdeltResponseCheck(
            check_name="news_raw_response_present",
            status="pass" if payload is not None else "fail",
            severity="error" if payload is None else "info",
            details={"status_code": status_code, "query_key": request.query_key},
        ),
        GdeltResponseCheck(
            check_name="news_raw_response_non_empty",
            status="pass" if payload else "fail",
            severity="error" if not payload else "info",
            details={"bytes_size": len(payload), "status_code": status_code, "query_key": request.query_key},
        ),
        _content_type_check(content_type, query_key=request.query_key),
    ]
    articles: list[ParsedGdeltArticle] = []
    malformed: list[dict[str, Any]] = []
    articles_array_present = False
    raw_rows_count = 0
    parse_error: str | None = None
    if payload:
        try:
            articles, malformed, articles_array_present, raw_rows_count = parse_gdelt_articles(payload, fetched_at=fetched_at)
        except GdeltNewsParseError as exc:
            parse_error = str(exc)
    else:
        parse_error = "empty response"
    checks.append(
        GdeltResponseCheck(
            check_name="news_articles_array_present",
            status="pass" if articles_array_present else "fail",
            severity="error" if not articles_array_present else "info",
            details={"query_key": request.query_key, "error": parse_error},
        )
    )
    checks.append(
        GdeltResponseCheck(
            check_name="news_articles_parsed_gt_zero",
            status="pass" if articles else "fail",
            severity="warning" if articles_array_present and not articles else "error" if not articles else "info",
            details={
                "query_key": request.query_key,
                "raw_rows_count": raw_rows_count,
                "parsed_rows_count": len(articles),
                "malformed_rows_count": len(malformed),
                "error": parse_error,
            },
        )
    )
    return articles, malformed, checks


def parse_gdelt_articles(
    payload: bytes | str | dict[str, Any],
    *,
    fetched_at: datetime,
) -> tuple[list[ParsedGdeltArticle], list[dict[str, Any]], bool, int]:
    data = _json_payload(payload)
    raw_articles = _raw_articles_array(data)
    articles_array_present = isinstance(raw_articles, list)
    if raw_articles is None:
        raise GdeltNewsParseError("missing articles array")
    articles: list[ParsedGdeltArticle] = []
    malformed: list[dict[str, Any]] = []
    for index, raw_article in enumerate(raw_articles):
        if not isinstance(raw_article, dict):
            malformed.append({"index": index, "error": "article row is not an object", "raw_type": type(raw_article).__name__})
            continue
        try:
            articles.append(_parse_article(raw_article))
        except GdeltNewsParseError as exc:
            malformed.append({"index": index, "error": str(exc), "raw_article_keys": sorted(str(key) for key in raw_article.keys())})
            continue
    return articles, malformed, articles_array_present, len(raw_articles)


def build_article_hash(article: ParsedGdeltArticle) -> str:
    identity_url = article.canonical_url or _normalize_url(article.url)
    if identity_url:
        return stable_json_hash({"identity_url": identity_url})
    return stable_json_hash(
        {
            "title": _normalize_text(article.title),
            "published_at": _to_utc(article.published_at).isoformat(),
            "source_name": _normalize_text(article.source_name),
        }
    )


def build_news_source_record_hash(*, source_code: str, article: ParsedGdeltArticle) -> str:
    return stable_json_hash(
        {
            "source_code": source_code,
            "external_id": article.external_id,
            "url": _normalize_url(article.url),
            "canonical_url": article.canonical_url,
            "title": _normalize_text(article.title),
            "summary": _normalize_text(article.summary),
            "published_at": _to_utc(article.published_at).isoformat(),
            "source_name": _normalize_text(article.source_name),
            "language": _normalize_text(article.language),
            "country": _normalize_text(article.country),
            "region": _normalize_text(article.region),
        }
    )


def query_presets() -> tuple[GdeltQueryPreset, ...]:
    return GDELT_QUERY_PRESETS


def _request_from_preset(
    preset: GdeltQueryPreset,
    *,
    from_date: date,
    to_date: date,
    maxrecords: int,
) -> GdeltRequest:
    return GdeltRequest(
        query_key=preset.query_key,
        query_string=preset.query_string,
        commodity_family_hint=preset.commodity_family,
        affected_products_hint=preset.affected_products,
        language=preset.language,
        from_date=from_date,
        to_date=to_date,
        maxrecords=maxrecords,
    )


def _json_payload(payload: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GdeltNewsParseError(f"invalid JSON response: {exc}") from exc
    if not isinstance(data, dict):
        raise GdeltNewsParseError("JSON response root is not an object")
    return data


def _raw_articles_array(data: dict[str, Any]) -> list[Any] | None:
    for key in ("articles", "documents", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return None


def _parse_article(raw: dict[str, Any]) -> ParsedGdeltArticle:
    url = _string_value(raw, "url", "URL")
    if not url:
        raise GdeltNewsParseError("missing article url")
    title = _string_value(raw, "title", "Title")
    if not title:
        raise GdeltNewsParseError("missing article title")
    published_at, source_field = _published_at(raw)
    if published_at is None:
        raise GdeltNewsParseError("missing article published_at/seendate")
    source_name = (
        _string_value(raw, "sourceCommonName", "source_name", "source", "domain")
        or _domain_from_url(url)
        or "unknown"
    )
    language = _string_value(raw, "language", "lang") or "unknown"
    return ParsedGdeltArticle(
        external_id=_stable_external_id(raw),
        url=url,
        canonical_url=_normalize_url(_string_value(raw, "canonical_url", "canonicalurl") or url),
        title=title,
        summary=_string_value(raw, "summary", "snippet", "description"),
        body_text=None,
        language=language,
        source_name=source_name,
        country=_string_value(raw, "sourceCountry", "sourcecountry", "country"),
        region=_string_value(raw, "region"),
        published_at=published_at,
        raw=raw,
        published_at_source_field=source_field,
    )


def _published_at(raw: dict[str, Any]) -> tuple[datetime | None, str]:
    for key in ("seendate", "date", "datetime", "published_at", "publishedAt"):
        value = _string_value(raw, key)
        if not value:
            continue
        parsed = _parse_datetime(value)
        if parsed is not None:
            return parsed, key
    return None, ""


def _parse_datetime(value: str) -> datetime | None:
    raw = value.strip()
    formats = ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y%m%d")
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone.utc)
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return _to_utc(parsed)


def _stable_external_id(raw: dict[str, Any]) -> str | None:
    for key in ("id", "article_id", "document_id", "documentIdentifier", "documentidentifier", "guid"):
        value = _string_value(raw, key)
        if value:
            return value
    return None


def _string_value(raw: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def _normalize_url(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, "", ""))


def _domain_from_url(value: str) -> str | None:
    netloc = urlsplit(value).netloc
    return netloc.lower() or None


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def _metadata_json(
    *,
    article: ParsedGdeltArticle,
    request: GdeltRequest,
    raw_response: RawResponse,
    request_url: str,
    identity_strategy: str,
) -> dict[str, Any]:
    return {
        "query_key": request.query_key,
        "query_string": request.query_string,
        "request_url": request_url,
        "source_mode": SOURCE_MODE,
        "maxrecords": request.maxrecords,
        "parser_version": PARSER_VERSION,
        "raw_article_keys": sorted(str(key) for key in article.raw.keys()),
        "commodity_family_hint": request.commodity_family_hint,
        "affected_products_hint": list(request.affected_products_hint),
        "language_hint": request.language,
        "collection_window": {
            "from_date": request.from_date.isoformat(),
            "to_date": request.to_date.isoformat(),
        },
        "published_at_source_field": article.published_at_source_field,
        "identity_strategy": identity_strategy,
        "raw_response_id": raw_response.id,
        "body_text_policy": "not_collected_in_phase_6_4d",
    }


def _find_existing_article(
    session: Session,
    *,
    source_id: int,
    external_id: str | None,
    article_hash: str,
) -> NewsArticle | None:
    if external_id:
        existing = session.scalar(
            select(NewsArticle)
            .where(NewsArticle.source_id == source_id, NewsArticle.external_id == external_id)
            .limit(1)
        )
        if existing is not None:
            return existing
    return session.scalar(
        select(NewsArticle)
        .where(NewsArticle.source_id == source_id, NewsArticle.article_hash == article_hash)
        .limit(1)
    )


def _write_request_quality_checks(session: Session, *, source: Source, request: GdeltRequest, checked_at: datetime) -> None:
    _write_quality_check(
        session,
        source_id=source.id,
        table_name="news_articles",
        check_name="news_query_valid",
        status="pass",
        severity="info",
        details={
            "source_code": SOURCE_CODE,
            "source_id": source.id,
            "query_key": request.query_key,
            "query": request.query_string,
            "maxrecords": request.maxrecords,
        },
        checked_at=checked_at,
    )
    _write_quality_check(
        session,
        source_id=source.id,
        table_name="news_articles",
        check_name="news_request_date_range_valid",
        status="pass",
        severity="info",
        details={
            "from_date": request.from_date.isoformat(),
            "to_date": request.to_date.isoformat(),
            "max_date_range_days": MAX_DATE_RANGE_DAYS,
        },
        checked_at=checked_at,
    )


def _write_response_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    request: GdeltRequest,
    checks: list[GdeltResponseCheck],
    checked_at: datetime,
) -> None:
    for check in checks:
        _write_quality_check(
            session,
            source_id=source_id,
            table_name="raw_responses",
            check_name=check.check_name,
            status=check.status,
            severity=check.severity,
            details={**check.details, "raw_response_id": raw_response_id, "query_key": request.query_key},
            checked_at=checked_at,
        )


def _write_malformed_article_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    request: GdeltRequest,
    malformed: list[dict[str, Any]],
    checked_at: datetime,
) -> None:
    for item in malformed:
        _write_quality_check(
            session,
            source_id=source_id,
            table_name="news_articles",
            check_name="news_article_parse_skipped",
            status="fail",
            severity="warning",
            details={**item, "raw_response_id": raw_response_id, "query_key": request.query_key},
            checked_at=checked_at,
        )


def _write_article_quality_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    article: ParsedGdeltArticle,
    article_hash: str,
    checked_at: datetime,
) -> None:
    details = {
        "raw_response_id": raw_response_id,
        "url": article.url,
        "title": article.title,
        "published_at": _to_utc(article.published_at).isoformat(),
        "article_hash": article_hash,
    }
    _write_quality_check(session, source_id=source_id, table_name="news_articles", check_name="news_article_url_present", status="pass", severity="info", details=details, checked_at=checked_at)
    _write_quality_check(session, source_id=source_id, table_name="news_articles", check_name="news_article_title_present", status="pass", severity="info", details=details, checked_at=checked_at)
    _write_quality_check(session, source_id=source_id, table_name="news_articles", check_name="news_article_published_at_present", status="pass", severity="info", details=details, checked_at=checked_at)
    _write_quality_check(session, source_id=source_id, table_name="news_articles", check_name="news_article_hash_present", status="pass" if article_hash else "fail", severity="error" if not article_hash else "info", details=details, checked_at=checked_at)
    _write_quality_check(session, source_id=source_id, table_name="news_articles", check_name="news_raw_linkage_present", status="pass", severity="info", details=details, checked_at=checked_at)


def _write_article_conflict_check(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    existing: NewsArticle,
    incoming: ParsedGdeltArticle,
    incoming_article_hash: str,
    incoming_source_record_hash: str,
    checked_at: datetime,
) -> None:
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="news_articles",
        check_name="news_existing_article_hash_changed",
        status="fail",
        severity="warning",
        details={
            "existing_id": existing.id,
            "existing_external_id": existing.external_id,
            "incoming_external_id": incoming.external_id,
            "existing_article_hash": existing.article_hash,
            "incoming_article_hash": incoming_article_hash,
            "existing_source_record_hash": existing.source_record_hash,
            "incoming_source_record_hash": incoming_source_record_hash,
            "existing_raw_response_id": existing.raw_response_id,
            "incoming_raw_response_id": raw_response_id,
            "existing_values": _article_values(existing),
            "incoming_values": _incoming_values(incoming),
            "policy_decision": "rejected_hash_conflict_no_overwrite",
        },
        checked_at=checked_at,
    )


def _article_values(existing: NewsArticle) -> dict[str, Any]:
    return {
        "url": existing.url,
        "canonical_url": existing.canonical_url,
        "title": existing.title,
        "summary": existing.summary,
        "language": existing.language,
        "source_name": existing.source_name,
        "country": existing.country,
        "region": existing.region,
        "published_at": _to_utc(existing.published_at).isoformat(),
    }


def _incoming_values(incoming: ParsedGdeltArticle) -> dict[str, Any]:
    return {
        "url": incoming.url,
        "canonical_url": incoming.canonical_url,
        "title": incoming.title,
        "summary": incoming.summary,
        "language": incoming.language,
        "source_name": incoming.source_name,
        "country": incoming.country,
        "region": incoming.region,
        "published_at": _to_utc(incoming.published_at).isoformat(),
    }


def _content_type_check(content_type: str | None, *, query_key: str | None) -> GdeltResponseCheck:
    if not content_type:
        return GdeltResponseCheck(
            check_name="news_content_type_expected",
            status="skip",
            severity="info",
            details={"content_type": None, "query_key": query_key},
        )
    normalized = content_type.split(";")[0].strip().lower()
    expected = {"application/json", "text/json", "text/plain"}
    return GdeltResponseCheck(
        check_name="news_content_type_expected",
        status="pass" if normalized in expected else "fail",
        severity="warning" if normalized not in expected else "info",
        details={"content_type": content_type, "query_key": query_key},
    )


def _has_parser_error(checks: list[GdeltResponseCheck]) -> bool:
    return any(check.check_name == "news_articles_array_present" and check.status == "fail" for check in checks)


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


def _response_url(response: httpx.Response) -> str:
    try:
        return str(response.url)
    except RuntimeError:
        return ENDPOINT


def _normalize_run_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized != "manual":
        raise ValueError("gdelt_news is manual-only in Phase 6.4D")
    return normalized


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _result_from_run(
    collector: GdeltNewsCollector,
    collector_run: CollectorRun,
    started_at: datetime,
    *,
    request: GdeltRequest,
    errors_count: int,
) -> GdeltNewsCollectorResult:
    return GdeltNewsCollectorResult(
        run_id=collector_run.id,
        source_code=collector.source_code,
        collector_name=collector.collector_name,
        parser_version=collector.parser_version,
        started_at=started_at,
        finished_at=collector_run.finished_at or _to_utc(datetime.now(timezone.utc)),
        status=collector_run.status,
        records_found=collector_run.records_found,
        records_written=collector_run.records_written,
        error_message=collector_run.error_message,
        errors_count=errors_count,
        query_key=request.query_key,
        query=request.query_string,
        from_date=request.from_date.isoformat(),
        to_date=request.to_date.isoformat(),
        maxrecords=request.maxrecords,
    )
