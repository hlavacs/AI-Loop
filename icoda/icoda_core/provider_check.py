"""Inspect configured provider CLIs locally without sending an LLM request."""

from __future__ import annotations

import argparse
import json
import platform
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from icoda_core import agent, persistence


def _report(checks: list[agent.ProviderCheck]) -> dict[str, object]:
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "configured_on": agent.providers_checked_on(),
        "providers": [asdict(check) for check in checks],
    }


def report(cwd: Path) -> dict[str, object]:
    return _report(agent.check_providers(agent.load_providers(), cwd))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    checks = agent.check_providers(agent.load_providers(), args.cwd.resolve())
    data = _report(checks)
    text = json.dumps(data, indent=2) + "\n"
    if args.output:
        persistence._atomic_write_text(args.output, text)
    print(text, end="")
    incompatible = [check for check in checks
                    if check.configured_enabled and check.installed and not check.compatible]
    return int(bool(incompatible))


if __name__ == "__main__":
    raise SystemExit(main())
