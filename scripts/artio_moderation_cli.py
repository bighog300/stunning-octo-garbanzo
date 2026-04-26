#!/usr/bin/env python3
"""Local CLI for Artio moderation workflow."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "http://localhost:8000"
WEB_URL = "http://localhost:5173"
SERVICES = ("postgres", "api", "web")


@dataclass
class HealthResult:
    name: str
    url: str
    ok: bool
    detail: str


def run_command(cmd: Sequence[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, text=True, capture_output=True, check=check)
    except FileNotFoundError:
        print("Error: docker command not found. Please install Docker and Docker Compose.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else ""
        stdout = exc.stdout.strip() if exc.stdout else ""
        message = stderr or stdout or str(exc)
        print(f"Command failed: {' '.join(cmd)}\n{message}", file=sys.stderr)
        sys.exit(exc.returncode)


def compose_status(_args: argparse.Namespace) -> int:
    result = run_command(["docker", "compose", "ps", *SERVICES])
    if result.returncode != 0:
        print(result.stderr.strip() or "Unable to get docker compose status.", file=sys.stderr)
        return result.returncode

    print(result.stdout.strip() or "No containers found.")
    return 0


def compose_start(_args: argparse.Namespace) -> int:
    result = run_command(["docker", "compose", "up", "-d", "api", "web"])
    if result.returncode != 0:
        print(result.stderr.strip() or "Unable to start services.", file=sys.stderr)
        return result.returncode

    print("Artio moderation services started.")
    print(f"API: {API_URL}")
    print(f"Web: {WEB_URL}")
    return 0


def compose_stop(_args: argparse.Namespace) -> int:
    result = run_command(["docker", "compose", "stop", "api", "web"])
    if result.returncode != 0:
        print(result.stderr.strip() or "Unable to stop services.", file=sys.stderr)
        return result.returncode

    print("Stopped api and web services.")
    return 0


def request_json(url: str, timeout: int = 5) -> tuple[bool, str, int | None]:
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as response:
            payload = response.read()
            return True, payload.decode("utf-8"), response.status
    except HTTPError as exc:
        return False, f"HTTP {exc.code}", exc.code
    except URLError as exc:
        return False, f"URL error: {exc.reason}", None
    except TimeoutError:
        return False, "request timed out", None


def _count_from_json(text: str) -> int | None:
    try:
        import json

        data = json.loads(text)
    except Exception:
        return None

    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return len(data)
    return None


def api_health(_args: argparse.Namespace) -> int:
    checks = [
        ("health", f"{API_URL}/health"),
        ("artworks", f"{API_URL}/api/artworks"),
        ("review_queue", f"{API_URL}/api/review-queue"),
    ]

    results: list[HealthResult] = []
    for name, url in checks:
        ok, body, status_code = request_json(url)
        if not ok:
            results.append(HealthResult(name=name, url=url, ok=False, detail=body))
            continue

        if name in {"artworks", "review_queue"}:
            count = _count_from_json(body)
            detail = f"status={status_code}, count={count if count is not None else 'unknown'}"
        else:
            detail = f"status={status_code}"

        results.append(HealthResult(name=name, url=url, ok=True, detail=detail))

    failed = False
    for result in results:
        prefix = "OK" if result.ok else "FAIL"
        print(f"[{prefix}] {result.name}: {result.detail} ({result.url})")
        if not result.ok:
            failed = True

    return 1 if failed else 0


def seed_review_queue(args: argparse.Namespace) -> int:
    try:
        import psycopg
    except ImportError:
        print(
            "Error: psycopg is required for seed-review-queue. Install it with 'pip install psycopg[binary]'.",
            file=sys.stderr,
        )
        return 1

    env = {
        "host": os.getenv("ARTIO_POSTGRES_HOST", "localhost"),
        "port": os.getenv("ARTIO_POSTGRES_PORT", "5432"),
        "dbname": os.getenv("ARTIO_POSTGRES_DB", "artio"),
        "user": os.getenv("ARTIO_POSTGRES_USER", "artio"),
        "password": os.getenv("ARTIO_POSTGRES_PASSWORD", "artio"),
    }

    conn_str = " ".join(f"{k}={v}" for k, v in env.items())
    query = """
    INSERT INTO app.review_queue (artwork_id, review_status, created_at)
    SELECT ar.artwork_id, 'pending', now()
    FROM app.artwork_records ar
    WHERE NOT EXISTS (
        SELECT 1
        FROM app.review_queue rq
        WHERE rq.artwork_id = ar.artwork_id
    )
    ORDER BY ar.created_at DESC
    LIMIT %s
    """

    try:
        with psycopg.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (args.limit,))
                inserted = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            conn.commit()
    except Exception as exc:
        print(f"Failed to seed review queue: {exc}", file=sys.stderr)
        return 1

    print(f"Inserted {inserted} pending review record(s) into app.review_queue.")
    return 0


def open_web(_args: argparse.Namespace) -> int:
    print(f"Web: {WEB_URL}")
    try:
        opened = webbrowser.open(WEB_URL)
        if opened:
            print("Opened browser.")
        else:
            print("Could not automatically open browser. Open the URL manually.")
    except Exception as exc:
        print(f"Could not open browser automatically: {exc}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Artio moderation local CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    cmd_status = subparsers.add_parser("status", help="Show docker compose status for api, web, postgres")
    cmd_status.set_defaults(func=compose_status)

    cmd_start = subparsers.add_parser("start", help="Start api + web services")
    cmd_start.set_defaults(func=compose_start)

    cmd_stop = subparsers.add_parser("stop", help="Stop api + web services")
    cmd_stop.set_defaults(func=compose_stop)

    cmd_health = subparsers.add_parser("health", help="Check API health and moderation endpoints")
    cmd_health.set_defaults(func=api_health)

    cmd_seed = subparsers.add_parser("seed-review-queue", help="Insert missing app.artwork_records into app.review_queue")
    cmd_seed.add_argument("--limit", type=int, default=50, help="Max records to seed (default: 50)")
    cmd_seed.set_defaults(func=seed_review_queue)

    cmd_open = subparsers.add_parser("open", help="Print and open moderation web URL")
    cmd_open.set_defaults(func=open_web)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
