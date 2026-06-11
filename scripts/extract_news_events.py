from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.logging import setup_logging
from app.features.news_events import extract_news_events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract deterministic commodity events from news_articles.")
    parser.add_argument("--from-date", required=True, help="Inclusive article published_at start date as YYYY-MM-DD.")
    parser.add_argument("--to-date", required=True, help="Inclusive article published_at end date as YYYY-MM-DD.")
    parser.add_argument("--source", help="Optional source code filter, for example gdelt_2_1.")
    parser.add_argument("--limit", type=int, help="Optional maximum number of articles to scan.")
    parser.add_argument("--article-id", type=int, help="Optional news_articles.id for debugging one article.")
    parser.add_argument("--dry-run", action="store_true", help="Scan and report candidates without writing commodity_events.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    setup_logging()

    from_date = _parse_date_arg(parser, "--from-date", args.from_date)
    to_date = _parse_date_arg(parser, "--to-date", args.to_date)
    if from_date > to_date:
        parser.error("--from-date must be on or before --to-date")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")

    result = extract_news_events(
        from_date=from_date,
        to_date=to_date,
        source_code=args.source,
        limit=args.limit,
        article_id=args.article_id,
        dry_run=args.dry_run,
    )
    print(f"articles_scanned={result.articles_scanned}")
    print(f"articles_with_events={result.articles_with_events}")
    print(f"events_found={result.events_found}")
    print(f"events_written={result.events_written}")
    print(f"skipped_existing={result.skipped_existing}")
    print(f"conflicts_count={result.conflicts_count}")
    print(f"errors_count={result.errors_count}")
    print(f"from_date={result.from_date}")
    print(f"to_date={result.to_date}")
    print(f"source_code={result.source_code}")
    print(f"limit={result.limit}")
    print(f"article_id={result.article_id}")
    print(f"extraction_version={result.extraction_version}")
    print(f"dry_run={result.dry_run}")


def _parse_date_arg(parser: argparse.ArgumentParser, name: str, value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        parser.error(f"{name} must use YYYY-MM-DD format")


if __name__ == "__main__":
    main()

