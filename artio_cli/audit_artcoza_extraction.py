from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
from typing import Any

from scraper.parsers.artcoza import artist_name_from_slug

ARTIST_NAME_DIAGNOSTIC_DENYLIST = {
    "artist statement",
    "about the artist",
    "selected works",
    "latest work",
    "artworks",
    "paintings",
    "prints",
    "drawing",
    "sculpture",
    "african queens: restoring history",
}


@dataclass
class ExtractionStats:
    label: str
    records_total: int
    unique_artists: int
    with_description: int
    with_artist_bio: int
    with_artist_statement: int
    with_medium: int
    with_dimensions: int
    with_price: int
    avg_description_length: float
    median_description_length: float
    quality_score: float


@dataclass
class MatchedMetrics:
    baseline_records_total: int
    recrawl_records_total: int
    matched_records_total: int
    recrawl_only_records_total: int
    baseline_only_records_total: int
    matched_quality_before: float
    matched_quality_after: float
    matched_quality_delta: float


@dataclass
class ArtistNameBackfillMetrics:
    changed_artist_name_count: int
    update_candidate_count: int
    skipped_missing_source_record_id_count: int
    skipped_source_record_id_mismatch_count: int
    skipped_empty_after_name_count: int
    applied: bool
    applied_updates_count: int
    applied_rows_affected: int


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _non_empty(value: Any) -> bool:
    return bool(_safe_text(value))


def _compute_quality_score(record: dict[str, Any]) -> float:
    checks = (
        _non_empty(record.get("artist_name")),
        _non_empty(record.get("artwork_title")),
        _non_empty(record.get("description")),
        _non_empty(record.get("medium_text")),
        _non_empty(record.get("dimensions_text")),
        _non_empty(record.get("price_text")),
        _non_empty((record.get("raw_payload") or {}).get("artist_bio")),
    )
    passed = sum(1 for check in checks if check)
    return round((passed / len(checks)) * 100, 2)


def build_stats(label: str, records: list[dict[str, Any]]) -> ExtractionStats:
    artists = set()
    description_lengths: list[int] = []

    with_description = 0
    with_artist_bio = 0
    with_artist_statement = 0
    with_medium = 0
    with_dimensions = 0
    with_price = 0
    quality_scores: list[float] = []

    for record in records:
        artist = _safe_text(record.get("artist_name"))
        if artist:
            artists.add(artist.casefold())

        description = _safe_text(record.get("description"))
        if description:
            with_description += 1
            description_lengths.append(len(description))

        raw_payload = record.get("raw_payload") or {}
        if _non_empty(raw_payload.get("artist_bio")):
            with_artist_bio += 1
        if _non_empty(raw_payload.get("artist_statement")):
            with_artist_statement += 1
        if _non_empty(record.get("medium_text")):
            with_medium += 1
        if _non_empty(record.get("dimensions_text")):
            with_dimensions += 1
        if _non_empty(record.get("price_text")):
            with_price += 1

        quality_scores.append(_compute_quality_score(record))

    if description_lengths:
        avg_description_length = round(statistics.fmean(description_lengths), 2)
        median_description_length = float(statistics.median(description_lengths))
    else:
        avg_description_length = 0.0
        median_description_length = 0.0

    avg_quality_score = round(statistics.fmean(quality_scores), 2) if quality_scores else 0.0

    return ExtractionStats(
        label=label,
        records_total=len(records),
        unique_artists=len(artists),
        with_description=with_description,
        with_artist_bio=with_artist_bio,
        with_artist_statement=with_artist_statement,
        with_medium=with_medium,
        with_dimensions=with_dimensions,
        with_price=with_price,
        avg_description_length=avg_description_length,
        median_description_length=median_description_length,
        quality_score=avg_quality_score,
    )


def _delta(before: ExtractionStats, after: ExtractionStats) -> dict[str, float]:
    keys = [
        "records_total",
        "unique_artists",
        "with_description",
        "with_artist_bio",
        "with_artist_statement",
        "with_medium",
        "with_dimensions",
        "with_price",
        "avg_description_length",
        "median_description_length",
        "quality_score",
    ]
    out: dict[str, float] = {}
    for key in keys:
        out[key] = round(float(getattr(after, key)) - float(getattr(before, key)), 2)
    return out


def _parse_records_content(content: str) -> list[dict[str, Any]]:
    text = content.lstrip()
    if not text:
        return []

    records: list[dict[str, Any]] = []
    if text.startswith("["):
        payload = json.loads(content)
        if not isinstance(payload, list):
            raise ValueError("JSON input must be an array of records.")
        iterable = payload
    else:
        iterable = [json.loads(line) for line in content.splitlines() if line.strip()]

    for item in iterable:
        if isinstance(item, dict) and "artwork_title" in item:
            records.append(item)
    return records


def load_records_from_jsonl(path: Path) -> list[dict[str, Any]]:
    return _parse_records_content(path.read_text(encoding="utf-8"))


def _stable_match_key(record: dict[str, Any]) -> tuple[Any, ...] | None:
    source_record_id = _safe_text(record.get("source_record_id"))
    if source_record_id:
        return ("source_record_id", source_record_id)

    source_url = _safe_text(record.get("source_url"))
    image_url = _safe_text(record.get("image_url"))
    artwork_title = _safe_text(record.get("artwork_title"))
    if source_url and image_url:
        return ("source_url_image_url", source_url, image_url)
    if source_url and artwork_title:
        return ("source_url_artwork_title", source_url, artwork_title.casefold())
    return None


def match_records(
    baseline_records: list[dict[str, Any]],
    recrawl_records: list[dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    recrawl_by_key: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    recrawl_unmatched: list[dict[str, Any]] = []

    for record in recrawl_records:
        key = _stable_match_key(record)
        if key is None:
            recrawl_unmatched.append(record)
            continue
        recrawl_by_key.setdefault(key, []).append(record)

    matched: list[tuple[dict[str, Any], dict[str, Any]]] = []
    baseline_only: list[dict[str, Any]] = []

    for before in baseline_records:
        key = _stable_match_key(before)
        if key is None:
            baseline_only.append(before)
            continue
        bucket = recrawl_by_key.get(key)
        if bucket:
            after = bucket.pop(0)
            matched.append((before, after))
            if not bucket:
                recrawl_by_key.pop(key, None)
        else:
            baseline_only.append(before)

    recrawl_only: list[dict[str, Any]] = recrawl_unmatched[:]
    for bucket in recrawl_by_key.values():
        recrawl_only.extend(bucket)

    return matched, baseline_only, recrawl_only


def _avg_quality(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.0
    return round(statistics.fmean(_compute_quality_score(record) for record in records), 2)


def build_matched_metrics(
    baseline_records: list[dict[str, Any]],
    recrawl_records: list[dict[str, Any]],
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    baseline_only: list[dict[str, Any]],
    recrawl_only: list[dict[str, Any]],
) -> MatchedMetrics:
    matched_before = [before for before, _ in matched_pairs]
    matched_after = [after for _, after in matched_pairs]
    quality_before = _avg_quality(matched_before)
    quality_after = _avg_quality(matched_after)

    return MatchedMetrics(
        baseline_records_total=len(baseline_records),
        recrawl_records_total=len(recrawl_records),
        matched_records_total=len(matched_pairs),
        recrawl_only_records_total=len(recrawl_only),
        baseline_only_records_total=len(baseline_only),
        matched_quality_before=quality_before,
        matched_quality_after=quality_after,
        matched_quality_delta=round(quality_after - quality_before, 2),
    )


def _preview(text: Any, max_len: int = 140) -> str:
    clean = _safe_text(text)
    if len(clean) <= max_len:
        return clean
    return f"{clean[:max_len - 1]}…"


def build_changed_records(
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    show_changes: int,
) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    for before, after in matched_pairs:
        quality_before = _compute_quality_score(before)
        quality_after = _compute_quality_score(after)
        quality_delta = round(quality_after - quality_before, 2)

        artist_before = _safe_text(before.get("artist_name"))
        artist_after = _safe_text(after.get("artist_name"))
        artist_name_changed = artist_before != artist_after
        description_before = _safe_text(before.get("description"))
        description_after = _safe_text(after.get("description"))

        if (
            not artist_name_changed
            and description_before == description_after
            and quality_delta == 0
        ):
            continue

        changed.append(
            {
                "source_record_id": _safe_text(after.get("source_record_id") or before.get("source_record_id")),
                "artist_name_before": artist_before,
                "artist_name_after": artist_after,
                "artist_name_changed": artist_name_changed,
                "description_before_preview": _preview(description_before),
                "description_after_preview": _preview(description_after),
                "quality_before": quality_before,
                "quality_after": quality_after,
                "quality_delta": quality_delta,
            }
        )

    def sort_key(record: dict[str, Any]) -> tuple[int, float]:
        delta = float(record["quality_delta"])
        if delta > 0:
            return (0, -delta)
        if delta < 0:
            return (1, delta)
        return (2, 0.0)

    changed.sort(key=sort_key)
    if show_changes < 0:
        return changed
    return changed[:show_changes]


def build_artist_name_backfill_plan(
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    show_updates: int,
) -> tuple[ArtistNameBackfillMetrics, list[dict[str, str]]]:
    updates: list[dict[str, str]] = []
    changed_artist_name_count = 0
    skipped_missing_source_record_id_count = 0
    skipped_source_record_id_mismatch_count = 0
    skipped_empty_after_name_count = 0

    for before, after in matched_pairs:
        artist_before = _safe_text(before.get("artist_name"))
        artist_after = _safe_text(after.get("artist_name"))
        if artist_before == artist_after:
            continue

        changed_artist_name_count += 1
        source_record_id_before = _safe_text(before.get("source_record_id"))
        source_record_id_after = _safe_text(after.get("source_record_id"))
        if not source_record_id_before or not source_record_id_after:
            skipped_missing_source_record_id_count += 1
            continue
        if source_record_id_before != source_record_id_after:
            skipped_source_record_id_mismatch_count += 1
            continue
        if not artist_after:
            skipped_empty_after_name_count += 1
            continue

        updates.append(
            {
                "source_record_id": source_record_id_after,
                "artist_name_before": artist_before,
                "artist_name_after": artist_after,
            }
        )

    metrics = ArtistNameBackfillMetrics(
        changed_artist_name_count=changed_artist_name_count,
        update_candidate_count=len(updates),
        skipped_missing_source_record_id_count=skipped_missing_source_record_id_count,
        skipped_source_record_id_mismatch_count=skipped_source_record_id_mismatch_count,
        skipped_empty_after_name_count=skipped_empty_after_name_count,
        applied=False,
        applied_updates_count=0,
        applied_rows_affected=0,
    )

    if show_updates >= 0:
        return metrics, updates[:show_updates]
    return metrics, updates


def apply_artist_name_backfill_updates(updates: list[dict[str, str]]) -> tuple[int, int]:
    if not updates:
        return 0, 0

    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for applying artist-name backfills. Install psycopg[binary].") from exc

    conn_str = " ".join(
        f"{k}={v}"
        for k, v in {
            "host": os.getenv("ARTIO_POSTGRES_HOST", "localhost"),
            "port": os.getenv("ARTIO_POSTGRES_PORT", "5432"),
            "dbname": os.getenv("ARTIO_POSTGRES_DB", "artio"),
            "user": os.getenv("ARTIO_POSTGRES_USER", "artio"),
            "password": os.getenv("ARTIO_POSTGRES_PASSWORD", "artio"),
        }.items()
    )

    rows_affected = 0
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            for update in updates:
                cur.execute(
                    """
                    UPDATE raw.artworks
                    SET artist_name = %s
                    WHERE source_domain = 'art.co.za'
                      AND source_record_id = %s
                      AND COALESCE(artist_name, '') = %s
                    """,
                    (
                        update["artist_name_after"],
                        update["source_record_id"],
                        update["artist_name_before"],
                    ),
                )
                rows_affected += cur.rowcount
        conn.commit()

    return len(updates), rows_affected


def _is_single_token(name: str) -> bool:
    return len([token for token in name.split() if token]) == 1


def build_suspect_artist_names(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    suspects: list[dict[str, str]] = []
    for record in records:
        extracted = _safe_text(record.get("artist_name"))
        if not extracted:
            continue

        source_url = _safe_text(record.get("source_url"))
        lowered = extracted.casefold()
        suggested = artist_name_from_slug(source_url) if source_url else None
        reason: str | None = None

        if lowered in ARTIST_NAME_DIAGNOSTIC_DENYLIST:
            reason = "section_label_denylist"
        elif ":" in extracted:
            reason = "contains_colon_exhibition_like"
        elif len(extracted) > 60:
            reason = "name_too_long"
        elif _is_single_token(extracted) and suggested:
            reason = "single_token_with_known_slug_override"

        if reason:
            suspects.append(
                {
                    "extracted_artist_name": extracted,
                    "source_url": source_url,
                    "suggested_artist_name": suggested or "",
                    "reason": reason,
                }
            )

    return suspects


def load_baseline_from_db(limit: int) -> list[dict[str, Any]]:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for baseline DB audit. Install psycopg[binary].") from exc

    conn_str = " ".join(
        f"{k}={v}"
        for k, v in {
            "host": os.getenv("ARTIO_POSTGRES_HOST", "localhost"),
            "port": os.getenv("ARTIO_POSTGRES_PORT", "5432"),
            "dbname": os.getenv("ARTIO_POSTGRES_DB", "artio"),
            "user": os.getenv("ARTIO_POSTGRES_USER", "artio"),
            "password": os.getenv("ARTIO_POSTGRES_PASSWORD", "artio"),
        }.items()
    )

    query = """
        SELECT
            source_record_id,
            source_url,
            image_url,
            artist_name,
            artwork_title,
            description,
            medium_text,
            dimensions_text,
            price_text,
            raw_payload
        FROM raw.artworks
        WHERE source_domain = 'art.co.za'
        ORDER BY crawl_timestamp DESC NULLS LAST, created_at DESC
        LIMIT %s
    """
    with psycopg.connect(conn_str, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (limit,))
            return [dict(row) for row in cur.fetchall()]


def run_non_destructive_recrawl(max_artists: int, max_records: int, scrapy_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="artcoza_audit_") as tmp_dir:
        output_path = Path(tmp_dir) / "artcoza_audit.jsonl"
        cmd = [
            "scrapy",
            "crawl",
            "artcoza_artworks",
            "-a",
            f"max_artists={max_artists}",
            "-a",
            f"max_records={max_records}",
            "-a",
            "dry_run=true",
            "-O",
            str(output_path),
        ]
        completed = subprocess.run(cmd, cwd=scrapy_dir, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"Recrawl failed: {stderr}")

        records = load_records_from_jsonl(output_path)
        metadata = {
            "command": " ".join(cmd),
            "scrapy_cwd": str(scrapy_dir),
            "stdout_tail": "\n".join(completed.stdout.splitlines()[-20:]),
            "stderr_tail": "\n".join(completed.stderr.splitlines()[-20:]),
            "dry_run": True,
        }
    return records, metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recrawl art.co.za in dry-run mode and produce before/after extraction quality audit report."
    )
    parser.add_argument("--baseline-limit", type=int, default=1000, help="Baseline sample size from raw.artworks.")
    parser.add_argument("--max-artists", type=int, default=50, help="Artist cap for dry-run recrawl sample.")
    parser.add_argument("--max-records", type=int, default=500, help="Record cap for dry-run recrawl sample.")
    parser.add_argument(
        "--scrapy-dir",
        type=Path,
        default=Path("crawlers"),
        help="Path containing scrapy.cfg for running recrawl.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("app/reports/artcoza_extraction_audit.json"),
        help="Report output path.",
    )
    parser.add_argument(
        "--recrawl-jsonl",
        type=Path,
        default=None,
        help="Optional pre-generated dry-run crawl JSON/JSONL. When set, skip invoking scrapy.",
    )
    parser.add_argument("--matched-only", action="store_true", help="Compute baseline/recrawl stats on matched records only.")
    parser.add_argument("--show-changes", type=int, default=10, help="Number of changed matched records to show; -1 means all.")
    parser.add_argument(
        "--show-artist-backfill-updates",
        type=int,
        default=20,
        help="Number of source_record_id-based artist-name update candidates to include; -1 means all.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply source_record_id-based artist-name backfill updates to raw.artworks. Defaults to dry-run report only.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print full JSON report to stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        baseline_records = load_baseline_from_db(limit=args.baseline_limit)
        if args.recrawl_jsonl:
            recrawl_records = load_records_from_jsonl(args.recrawl_jsonl)
            recrawl_meta = {
                "dry_run": True,
                "source": str(args.recrawl_jsonl),
                "command": None,
            }
        else:
            recrawl_records, recrawl_meta = run_non_destructive_recrawl(
                max_artists=args.max_artists,
                max_records=args.max_records,
                scrapy_dir=args.scrapy_dir,
            )

        matched_pairs, baseline_only, recrawl_only = match_records(baseline_records, recrawl_records)
        matched_metrics = build_matched_metrics(
            baseline_records=baseline_records,
            recrawl_records=recrawl_records,
            matched_pairs=matched_pairs,
            baseline_only=baseline_only,
            recrawl_only=recrawl_only,
        )

        if args.matched_only:
            baseline_stats = build_stats("before", [before for before, _ in matched_pairs])
            recrawl_stats = build_stats("after", [after for _, after in matched_pairs])
        else:
            baseline_stats = build_stats("before", baseline_records)
            recrawl_stats = build_stats("after", recrawl_records)

        changed_records = build_changed_records(matched_pairs, show_changes=args.show_changes)
        backfill_metrics, backfill_updates = build_artist_name_backfill_plan(
            matched_pairs,
            show_updates=args.show_artist_backfill_updates,
        )
        if args.apply:
            applied_updates_count, rows_affected = apply_artist_name_backfill_updates(backfill_updates)
            backfill_metrics.applied = True
            backfill_metrics.applied_updates_count = applied_updates_count
            backfill_metrics.applied_rows_affected = rows_affected
        suspect_artist_names = build_suspect_artist_names(recrawl_records)

        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "source": "art.co.za",
            "baseline": asdict(baseline_stats),
            "recrawl": asdict(recrawl_stats),
            "matched": asdict(matched_metrics),
            "delta": _delta(baseline_stats, recrawl_stats),
            "changed_records": changed_records,
            "artist_name_backfill": {
                **asdict(backfill_metrics),
                "updates": backfill_updates,
            },
            "suspect_artist_name_count": len(suspect_artist_names),
            "suspect_artist_names": suspect_artist_names,
            "metadata": {
                "baseline_limit": args.baseline_limit,
                "max_artists": args.max_artists,
                "max_records": args.max_records,
                "baseline_records_sampled": len(baseline_records),
                "recrawl_records_sampled": len(recrawl_records),
                "matched_only": args.matched_only,
                "show_changes": args.show_changes,
                "show_artist_backfill_updates": args.show_artist_backfill_updates,
                "recrawl": recrawl_meta,
                "non_destructive": not args.apply,
                "apply": args.apply,
            },
        }

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

        print(f"Wrote audit report: {args.output}")
        print(
            "Summary: "
            f"matched={matched_metrics.matched_records_total}, "
            f"matched_quality_before={matched_metrics.matched_quality_before}, "
            f"matched_quality_after={matched_metrics.matched_quality_after}, "
            f"matched_quality_delta={matched_metrics.matched_quality_delta}, "
            f"artist_name_changed={backfill_metrics.changed_artist_name_count}, "
            f"artist_backfill_candidates={backfill_metrics.update_candidate_count}, "
            f"apply={args.apply}, "
            f"rows_affected={backfill_metrics.applied_rows_affected}"
        )
        if args.print_json:
            print(json.dumps(report, indent=2))
    except Exception as exc:  # noqa: BLE001
        print(f"Audit failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
