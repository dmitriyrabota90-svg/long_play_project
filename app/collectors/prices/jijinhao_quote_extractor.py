"""Strict parser for the verified JO_165951 Jijinhao assignment format."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

EXPECTED_SYMBOL = "JO_165951"
EXPECTED_COLUMN_COUNT = 43
PRICE_INDEX = 3
PRIMARY_DATE_INDEX, PRIMARY_TIME_INDEX = 30, 31
SECONDARY_DATE_INDEX, SECONDARY_TIME_INDEX = 40, 41
_ASSIGNMENT = re.compile(r"^var\s+hq_str_([A-Za-z0-9_]+)\s*=\s*")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_MINUTE = re.compile(r"\d{2}:\d{2}\Z")
_SECOND = re.compile(r"\d{2}:\d{2}:\d{2}\Z")
_ESCAPES = {"\\": "\\", '"': '"', "'": "'", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class QuoteExtractionError(ValueError):
    """The response is not safe to interpret as the verified quote format."""


@dataclass(frozen=True)
class CivilTimePair:
    raw_date: str
    raw_time: str
    normalized_civil: str | None
    precision: str | None
    timezone: None
    status: str
    error: str | None


@dataclass(frozen=True)
class QuoteExtraction:
    source_symbol: str
    raw_sha256: str
    column_count: int
    price: Decimal
    price_index: int
    primary_time_indexes: tuple[int, int]
    primary_time_semantics: str
    primary_time_basis: str
    primary_time: CivilTimePair
    secondary_time_indexes: tuple[int, int]
    secondary_time_semantics: str
    secondary_time: CivilTimePair

    def as_json_dict(self) -> dict[str, Any]:
        item = asdict(self)
        item["price"] = str(self.price)
        item["primary_time_indexes"] = list(self.primary_time_indexes)
        item["secondary_time_indexes"] = list(self.secondary_time_indexes)
        return item


def _literal(source: str) -> str:
    if not source or source[0] not in {'"', "'"}:
        raise QuoteExtractionError("assignment value must be a quoted JavaScript string literal")
    quote, result, index = source[0], [], 1
    while index < len(source):
        char = source[index]
        if char == quote:
            if not re.fullmatch(r"\s*;\s*", source[index + 1 :]):
                raise QuoteExtractionError("only a semicolon and whitespace may follow the string literal")
            return "".join(result)
        if char != "\\":
            result.append(char); index += 1; continue
        if index + 1 >= len(source):
            raise QuoteExtractionError("dangling escape in JavaScript string literal")
        decoded = _ESCAPES.get(source[index + 1])
        if decoded is None:
            raise QuoteExtractionError(f"unsupported JavaScript string escape: \\{source[index + 1]}")
        result.append(decoded); index += 2
    raise QuoteExtractionError("unterminated JavaScript string literal")


def _fields(payload: str) -> tuple[str, list[str]]:
    match = _ASSIGNMENT.match(payload)
    if not match:
        raise QuoteExtractionError("expected a var hq_str_<symbol> assignment")
    try:
        rows = list(csv.reader(io.StringIO(_literal(payload[match.end() :]), newline=""), strict=True))
    except csv.Error as error:
        raise QuoteExtractionError("CSV body is malformed") from error
    if len(rows) != 1:
        raise QuoteExtractionError("CSV body must contain exactly one record")
    return match.group(1), [value.strip() for value in rows[0]]


def _civil(raw_date: str, raw_time: str) -> CivilTimePair:
    if not raw_date and not raw_time:
        return CivilTimePair(raw_date, raw_time, None, None, None, "MISSING", None)
    if not raw_date or not raw_time:
        return CivilTimePair(raw_date, raw_time, None, None, None, "INCOMPLETE", "both date and time are required for a civil timestamp")
    if not _DATE.fullmatch(raw_date):
        return CivilTimePair(raw_date, raw_time, None, None, None, "INVALID", "unsupported date format; expected YYYY-MM-DD")
    precision = "minute" if _MINUTE.fullmatch(raw_time) else "second" if _SECOND.fullmatch(raw_time) else None
    if precision is None:
        return CivilTimePair(raw_date, raw_time, None, None, None, "INVALID", "unsupported time format; expected HH:MM or HH:MM:SS")
    try:
        parsed_date = date.fromisoformat(raw_date)
    except ValueError:
        return CivilTimePair(raw_date, raw_time, None, None, None, "INVALID", "invalid calendar date")
    try:
        parts = [int(value) for value in raw_time.split(":")]
        hour, minute, second = parts[0], parts[1], parts[2] if precision == "second" else 0
        if hour > 23 or minute > 59 or second > 59:
            raise ValueError
        normalized = datetime.combine(parsed_date, time(hour, minute, second)).isoformat(timespec="seconds")
    except ValueError:
        return CivilTimePair(raw_date, raw_time, None, None, None, "INVALID", "invalid clock time")
    return CivilTimePair(raw_date, raw_time, normalized, precision, None, "PARSED", None)


def extract_quote(payload: bytes | str, *, expected_symbol: str = EXPECTED_SYMBOL) -> QuoteExtraction:
    raw = payload if isinstance(payload, bytes) else payload.encode("utf-8")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise QuoteExtractionError("payload is not UTF-8") from error
    symbol, fields = _fields(text)
    if symbol != expected_symbol:
        raise QuoteExtractionError(f"unexpected symbol: {symbol!r}; expected {expected_symbol!r}")
    if len(fields) != EXPECTED_COLUMN_COUNT:
        raise QuoteExtractionError(f"unexpected field count: {len(fields)}; expected {EXPECTED_COLUMN_COUNT} for {expected_symbol}")
    try:
        price = Decimal(fields[PRICE_INDEX])
    except InvalidOperation as error:
        raise QuoteExtractionError(f"price at index {PRICE_INDEX} is not decimal: {fields[PRICE_INDEX]!r}") from error
    if not price.is_finite():
        raise QuoteExtractionError(f"price at index {PRICE_INDEX} is not finite: {fields[PRICE_INDEX]!r}")
    return QuoteExtraction(symbol, hashlib.sha256(raw).hexdigest(), len(fields), price, PRICE_INDEX,
        (PRIMARY_DATE_INDEX, PRIMARY_TIME_INDEX), "site_client_update_time",
        "Provider client maps t[30]/t[31] to quote date/time; source timezone is not established.",
        _civil(fields[PRIMARY_DATE_INDEX], fields[PRIMARY_TIME_INDEX]),
        (SECONDARY_DATE_INDEX, SECONDARY_TIME_INDEX), "unknown_secondary_date_time_pair",
        _civil(fields[SECONDARY_DATE_INDEX], fields[SECONDARY_TIME_INDEX]))
