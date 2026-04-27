#!/usr/bin/env python3
"""CLI for reproducible Superset assets."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_ASSET_PATH = Path("superset/assets/artio_dashboards.zip")
DEFAULT_SUPERSET_URL = "http://localhost:8088"
DEFAULT_SUPERSET_USERNAME = "admin"
DEFAULT_SUPERSET_PASSWORD = "admin"
DEFAULT_BOOTSTRAP_SCRIPT = Path("superset/bootstrap_artio_dashboard.py")
DEFAULT_ARTIST_PROFILE_BOOTSTRAP_SCRIPT = Path("superset/bootstrap_artist_profile_dashboard.py")


class CliError(RuntimeError):
    """Raised for expected CLI errors."""


def run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise CliError("docker is not installed or not available on PATH.") from exc


def ensure_superset_running() -> None:
    result = run_command(["docker", "compose", "ps", "--status", "running", "superset"])
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "docker compose ps failed"
        raise CliError(f"Unable to inspect Superset container status: {detail}")

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        raise CliError(
            "Superset container is not running. Start it with 'docker compose up -d superset' and retry."
        )


def run_superset_shell(script: str) -> None:
    ensure_superset_running()
    result = run_command(["docker", "compose", "exec", "-T", "superset", "sh", "-lc", script])
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise CliError(f"Superset command failed:\n{detail}")


def copy_file_to_superset(local_path: Path, remote_path: Path) -> None:
    if not local_path.exists():
        raise CliError(f"Local file not found: {local_path}")

    ensure_superset_running()
    copy_result = run_command(["docker", "compose", "cp", str(local_path), f"superset:{remote_path}"])
    if copy_result.returncode != 0:
        detail = copy_result.stderr.strip() or copy_result.stdout.strip() or "unknown copy error"
        raise CliError(f"Could not copy file into Superset container:\n{detail}")


def _quoted(path: Path) -> str:
    return shlex.quote(str(path))


def export_assets(args: argparse.Namespace) -> int:
    export_path = Path(args.path)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    inside_path = Path("/app/superset_home") / export_path

    script = "\n".join(
        [
            "set -e",
            f"mkdir -p {_quoted(inside_path.parent)}",
            "if superset export-dashboards --help >/dev/null 2>&1; then",
            f"  superset export-dashboards -f {_quoted(inside_path)}",
            "elif superset import-export export-dashboards --help >/dev/null 2>&1; then",
            f"  superset import-export export-dashboards -f {_quoted(inside_path)}",
            "else",
            '  echo "No supported Superset export command found." >&2',
            "  exit 1",
            "fi",
        ]
    )

    run_superset_shell(script)

    copy_result = run_command(["docker", "compose", "cp", f"superset:{inside_path}", str(export_path)])
    if copy_result.returncode != 0:
        detail = copy_result.stderr.strip() or copy_result.stdout.strip() or "unknown copy error"
        raise CliError(f"Export succeeded in container, but copying zip failed:\n{detail}")

    print(f"Exported Superset assets to {export_path}")
    return 0


def import_assets(args: argparse.Namespace) -> int:
    import_path = Path(args.path)
    if not import_path.exists():
        raise CliError(f"Asset zip not found: {import_path}")

    ensure_superset_running()
    inside_path = Path("/app/superset_home") / import_path
    copy_result = run_command(["docker", "compose", "cp", str(import_path), f"superset:{inside_path}"])
    if copy_result.returncode != 0:
        detail = copy_result.stderr.strip() or copy_result.stdout.strip() or "unknown copy error"
        raise CliError(f"Could not copy asset zip into Superset container:\n{detail}")

    overwrite_flag = " --overwrite" if args.overwrite else ""
    script = "\n".join(
        [
            "set -e",
            "if superset import-dashboards --help >/dev/null 2>&1; then",
            f"  superset import-dashboards -p {_quoted(inside_path)}{overwrite_flag}",
            "elif superset import-export import-dashboards --help >/dev/null 2>&1; then",
            f"  superset import-export import-dashboards -p {_quoted(inside_path)}{overwrite_flag}",
            "else",
            '  echo "No supported Superset import command found." >&2',
            "  exit 1",
            "fi",
        ]
    )

    run_superset_shell(script)
    print(f"Imported Superset assets from {import_path}")
    return 0


def api_request(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    *,
    base_url_hint: str | None = None,
) -> Any:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(url, method=method, data=data, headers=headers)
    try:
        with urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise CliError(f"Superset API error {exc.code} for {url}: {body or exc.reason}") from exc
    except URLError as exc:
        hint = base_url_hint or DEFAULT_SUPERSET_URL
        raise CliError(
            f"Cannot reach Superset API at {url}. Is Superset running at {hint}? ({exc.reason})"
        ) from exc


def list_assets(_args: argparse.Namespace) -> int:
    base_url = os.getenv("SUPERSET_URL", DEFAULT_SUPERSET_URL).rstrip("/")
    username = os.getenv("SUPERSET_USERNAME", DEFAULT_SUPERSET_USERNAME)
    password = os.getenv("SUPERSET_PASSWORD", DEFAULT_SUPERSET_PASSWORD)

    login = api_request(
        f"{base_url}/api/v1/security/login",
        method="POST",
        payload={
            "username": username,
            "password": password,
            "provider": "db",
            "refresh": False,
        },
        base_url_hint=base_url,
    )
    token = login.get("access_token")
    if not token:
        raise CliError("Login succeeded but no access token was returned by Superset.")

    endpoints = {
        "dashboards": "/api/v1/dashboard/?q=(page:0,page_size:100)",
        "charts": "/api/v1/chart/?q=(page:0,page_size:100)",
        "datasets": "/api/v1/dataset/?q=(page:0,page_size:100)",
    }

    for label, endpoint in endpoints.items():
        payload = api_request(f"{base_url}{endpoint}", token=token)
        results = payload.get("result", [])
        print(f"{label.title()} ({len(results)}):")
        for item in results:
            name = item.get("dashboard_title") or item.get("slice_name") or item.get("table_name") or "<unnamed>"
            print(f"  - {item.get('id')}: {name}")
        if not results:
            print("  (none)")

    return 0


def bootstrap_assets(args: argparse.Namespace) -> int:
    copy_file_to_superset(DEFAULT_BOOTSTRAP_SCRIPT, Path("/app/superset_home/bootstrap_artio_dashboard.py"))
    run_superset_shell("python /app/superset_home/bootstrap_artio_dashboard.py")
    print("Bootstrap script completed: /app/superset_home/bootstrap_artio_dashboard.py")

    path = Path(args.path)
    if path.exists():
        print(f"Found asset archive at {path}; importing it now.")
        import_args = argparse.Namespace(path=str(path), overwrite=args.overwrite)
        return import_assets(import_args)

    print(f"No asset archive found at {path}; skipping import.")
    return 0


def bootstrap_artist_profile_assets(_args: argparse.Namespace) -> int:
    copy_file_to_superset(
        DEFAULT_ARTIST_PROFILE_BOOTSTRAP_SCRIPT,
        Path("/app/superset_home/bootstrap_artist_profile_dashboard.py"),
    )
    run_superset_shell("python /app/superset_home/bootstrap_artist_profile_dashboard.py")
    print("Bootstrap script completed: /app/superset_home/bootstrap_artist_profile_dashboard.py")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI for reproducible Superset dashboards/charts/datasets")
    subparsers = parser.add_subparsers(dest="command", required=True)

    cmd_export = subparsers.add_parser("export", help="Export Superset dashboards/charts/datasets")
    cmd_export.add_argument("--path", default=str(DEFAULT_ASSET_PATH), help=f"Output zip path (default: {DEFAULT_ASSET_PATH})")
    cmd_export.set_defaults(func=export_assets)

    cmd_import = subparsers.add_parser("import", help="Import Superset dashboards/charts/datasets")
    cmd_import.add_argument("--path", default=str(DEFAULT_ASSET_PATH), help=f"Input zip path (default: {DEFAULT_ASSET_PATH})")
    cmd_import.add_argument("--overwrite", action="store_true", help="Pass --overwrite to Superset import command if supported")
    cmd_import.set_defaults(func=import_assets)

    cmd_list = subparsers.add_parser("list", help="List dashboards/charts/datasets via Superset API")
    cmd_list.set_defaults(func=list_assets)

    cmd_bootstrap = subparsers.add_parser(
        "bootstrap",
        help="Run dashboard bootstrap script then import saved assets when present",
    )
    cmd_bootstrap.add_argument("--path", default=str(DEFAULT_ASSET_PATH), help=f"Input zip path (default: {DEFAULT_ASSET_PATH})")
    cmd_bootstrap.add_argument("--overwrite", action="store_true", help="Pass --overwrite to import step if supported")
    cmd_bootstrap.set_defaults(func=bootstrap_assets)

    cmd_bootstrap_artist_profile = subparsers.add_parser(
        "bootstrap-artist-profile",
        help="Run artist profile dashboard bootstrap script",
    )
    cmd_bootstrap_artist_profile.set_defaults(func=bootstrap_artist_profile_assets)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except CliError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
