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
class AuditReport:
    generated_at: str
    source: str
    baseline: ExtractionStats
    recrawl: ExtractionStats
    delta: dict[str, float]
    metadata: dict[str, Any]


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


def load_records_from_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if "artwork_title" not in payload:
            continue
        records.append(payload)
    return records


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
        help="Optional pre-generated dry-run crawl JSONL. When set, skip invoking scrapy.",
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

        baseline_stats = build_stats("before", baseline_records)
        recrawl_stats = build_stats("after", recrawl_records)

        report = AuditReport(
            generated_at=datetime.now(UTC).isoformat(),
            source="art.co.za",
            baseline=baseline_stats,
            recrawl=recrawl_stats,
            delta=_delta(baseline_stats, recrawl_stats),
            metadata={
                "baseline_limit": args.baseline_limit,
                "max_artists": args.max_artists,
                "max_records": args.max_records,
                "baseline_records_sampled": len(baseline_records),
                "recrawl_records_sampled": len(recrawl_records),
                "recrawl": recrawl_meta,
                "non_destructive": True,
            },
        )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

        print(f"Wrote audit report: {args.output}")
        print(
            "Summary: "
            f"baseline quality={baseline_stats.quality_score}, "
            f"recrawl quality={recrawl_stats.quality_score}, "
            f"delta={report.delta['quality_score']}"
        )
        if args.print_json:
            print(json.dumps(asdict(report), indent=2))
    except Exception as exc:  # noqa: BLE001
        print(f"Audit failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
