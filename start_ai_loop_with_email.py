from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ENVIRONMENT_KEYS = {
    "AI_LOOP_NOTIFY_EMAIL",
    "AI_LOOP_SMTP_HOST",
    "AI_LOOP_SMTP_PORT",
    "AI_LOOP_SMTP_USER",
    "AI_LOOP_SMTP_FROM",
    "AI_LOOP_SMTP_STARTTLS",
    "AI_LOOP_SMTP_SSL",
    "AI_LOOP_IMAP_HOST",
    "AI_LOOP_IMAP_PORT",
    "AI_LOOP_IMAP_USER",
    "AI_LOOP_IMAP_MAILBOX",
    "AI_LOOP_IMAP_STARTTLS",
    "AI_LOOP_IMAP_SSL",
    "AI_LOOP_EMAIL_POLL_SECONDS",
    "REDIS_URL",
    "CODEX_BYPASS_SANDBOX",
}

PASSWORD_KEYS = {
    "AI_LOOP_SMTP_PASSWORD",
    "AI_LOOP_IMAP_PASSWORD",
}


class ConfigError(RuntimeError):
    pass


def environment_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    raise ConfigError(
        "environment values must be strings, numbers, or booleans, "
        f"got {type(value).__name__}"
    )


def load_config(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(
            f"email configuration file not found: {path}\n"
            "Copy start-ai-loop-with-email.example.json to the parent directory as "
            "start-ai-loop-with-email.json and adapt it."
        ) from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"could not parse {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return raw


def apply_config(config: dict[str, Any], env: dict[str, str]) -> str:
    for key in PASSWORD_KEYS:
        if key in config:
            raise ConfigError(
                f"do not store {key} in the JSON file; set it in the "
                "environment or let the launcher prompt"
            )

    for key in ENVIRONMENT_KEYS:
        if key in config and config[key] is not None:
            env[key] = environment_value(config[key])

    environment = config.get("environment")
    if environment is not None:
        if not isinstance(environment, dict):
            raise ConfigError("'environment' must be a JSON object when present")
        for key, value in environment.items():
            if key in PASSWORD_KEYS:
                raise ConfigError(f"do not store {key} in the JSON file")
            if not isinstance(key, str):
                raise ConfigError("'environment' keys must be strings")
            if not key.startswith(
                ("AI_LOOP_", "CODEX_", "CLAUDE_", "GEMINI_")
            ) and key not in {"REDIS_URL"}:
                raise ConfigError(f"refusing unsupported environment key: {key}")
            if value is not None:
                env[key] = environment_value(value)

    prompt = config.get("password_prompt", "Mail password: ")
    if not isinstance(prompt, str):
        raise ConfigError("'password_prompt' must be a string")
    return prompt


def ensure_passwords(env: dict[str, str], prompt: str) -> None:
    if not env.get("AI_LOOP_SMTP_HOST"):
        return

    smtp_password = env.get("AI_LOOP_SMTP_PASSWORD")
    if not smtp_password:
        smtp_password = getpass.getpass(prompt)
        if not smtp_password:
            raise ConfigError("SMTP password is required")
        env["AI_LOOP_SMTP_PASSWORD"] = smtp_password

    if env.get("AI_LOOP_IMAP_HOST") and not env.get("AI_LOOP_IMAP_PASSWORD"):
        env["AI_LOOP_IMAP_PASSWORD"] = smtp_password


def main(argv: list[str]) -> int:
    repo_dir = Path(__file__).resolve().parent
    default_config = repo_dir.parent / "start-ai-loop-with-email.json"

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--email-config", type=Path, default=None)
    known, gui_args = parser.parse_known_args(argv)

    config_path = known.email_config or Path(
        os.environ.get("AI_LOOP_EMAIL_CONFIG", default_config)
    )
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()

    try:
        config = load_config(config_path)
        env = os.environ.copy()
        prompt = apply_config(config, env)
        ensure_passwords(env, prompt)
    except ConfigError as exc:
        print(f"ai-loop email launcher: {exc}", file=sys.stderr)
        return 1

    env["AI_LOOP_PARENT_LAUNCHER_ACTIVE"] = "1"
    launcher = repo_dir / ("ai_gui.cmd" if os.name == "nt" else "ai_gui.bash")
    if not launcher.exists():
        print(f"AI-Loop launcher not found at {launcher}", file=sys.stderr)
        return 1

    return subprocess.call([str(launcher), *gui_args], cwd=repo_dir, env=env)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
