"""Safely add SMTP delivery to an existing product-staging runtime file."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlsplit


DEFAULT_CONFIG_PATH = Path("/etc/socialpilot-staging/runtime.json")
DEFAULT_PUBLIC_ORIGIN = "https://staging.47.242.222.177.nip.io"
HOST_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def build_email_update(
    existing: dict[str, object],
    *,
    public_origin: str,
    from_address: str,
    smtp_host: str,
    smtp_port: int,
    smtp_username: str | None,
    smtp_password: str | None,
    security: str,
) -> dict[str, object]:
    parsed_origin = urlsplit(public_origin.strip())
    if (
        parsed_origin.scheme != "https"
        or not parsed_origin.netloc
        or parsed_origin.username is not None
        or parsed_origin.password is not None
        or parsed_origin.query
        or parsed_origin.fragment
    ):
        raise ValueError("Public origin must be a clean HTTPS origin")
    normalized_from = from_address.strip()
    if not normalized_from or "\r" in normalized_from or "\n" in normalized_from:
        raise ValueError("From address is invalid")
    normalized_host = smtp_host.strip().lower().rstrip(".")
    if not HOST_PATTERN.fullmatch(normalized_host):
        raise ValueError("SMTP host is invalid")
    if not 1 <= smtp_port <= 65_535:
        raise ValueError("SMTP port is invalid")
    if security not in {"starttls", "tls", "none"}:
        raise ValueError("SMTP security is invalid")
    normalized_username = (smtp_username or "").strip()
    normalized_password = (smtp_password or "").strip()
    if bool(normalized_username) != bool(normalized_password):
        raise ValueError("SMTP username and authorization code are required together")

    updated = dict(existing)
    updated.update(
        {
            "ACCOUNT_PUBLIC_WEB_ORIGIN": public_origin.strip().rstrip("/"),
            "ACCOUNT_EMAIL_FROM": normalized_from,
            "ACCOUNT_SMTP_HOST": normalized_host,
            "ACCOUNT_SMTP_PORT": str(smtp_port),
            "ACCOUNT_SMTP_SECURITY": security,
            "ACCOUNT_SMTP_TIMEOUT_SECONDS": "15",
        }
    )
    if normalized_username:
        updated["ACCOUNT_SMTP_USERNAME"] = normalized_username
        updated["ACCOUNT_SMTP_PASSWORD"] = normalized_password
    else:
        updated.pop("ACCOUNT_SMTP_USERNAME", None)
        updated.pop("ACCOUNT_SMTP_PASSWORD", None)
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Configure SocialPilot account email. The SMTP authorization code "
            "is requested interactively and never accepted as a command argument."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--public-origin", default=DEFAULT_PUBLIC_ORIGIN)
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--smtp-host", required=True)
    parser.add_argument("--smtp-port", type=int, default=587)
    parser.add_argument("--smtp-username")
    parser.add_argument(
        "--security",
        choices=("starttls", "tls", "none"),
        default="starttls",
    )
    return parser.parse_args()


def main() -> None:
    import grp

    if os.geteuid() != 0:
        raise SystemExit("Run this configurator as root")
    args = parse_args()
    if not args.config.is_file():
        raise SystemExit(f"Runtime configuration does not exist: {args.config}")
    loaded = json.loads(args.config.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise SystemExit("Runtime configuration must be a JSON object")
    password = None
    if args.smtp_username:
        password = getpass.getpass("SMTP authorization code (input hidden): ")
    updated = build_email_update(
        loaded,
        public_origin=args.public_origin,
        from_address=args.from_address,
        smtp_host=args.smtp_host,
        smtp_port=args.smtp_port,
        smtp_username=args.smtp_username,
        smtp_password=password,
        security=args.security,
    )

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = args.config.with_name(f"{args.config.name}.pre-email-{stamp}")
    shutil.copy2(args.config, backup)
    temporary = args.config.with_suffix(".json.new")
    temporary.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    socialpilot_gid = grp.getgrnam("socialpilot").gr_gid
    os.chown(temporary, 0, socialpilot_gid)
    os.chmod(temporary, 0o640)
    temporary.replace(args.config)
    os.chmod(args.config, 0o640)
    print(
        "Account email configuration saved. Restart only the staging API and "
        "verify /api/v1/system/readiness. The authorization code was not printed."
    )
    print(f"Rollback copy: {backup}")


if __name__ == "__main__":
    main()
