#!/usr/bin/env python3
"""Authenticate or inspect Codex SDK without displaying credential material."""

from __future__ import annotations

import argparse
import json
import re

from openai_codex import Codex


def _value(value):
    return getattr(value, "value", value)


def _safe_error_message(exc: Exception) -> str:
    message = " ".join(str(exc).split()) or type(exc).__name__
    message = re.sub(
        r"(?i)(authorization:\s*bearer\s+)[^\s,;]+",
        r"\1[REDACTED]",
        message,
    )
    message = re.sub(
        r"(?i)\b(access_token|refresh_token|id_token|api[_-]?key)\b"
        r"(\s*[:=]\s*)[^\s,;]+",
        r"\1\2[REDACTED]",
        message,
    )
    message = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", message)
    return message[:500]


def show_status() -> int:
    try:
        with Codex() as codex:
            response = codex.account(refresh_token=True)
    except Exception as exc:
        message = _safe_error_message(exc)
        print(
            json.dumps(
                {
                    "authenticated": False,
                    "requiresOpenaiAuth": True,
                    "error": message,
                },
                ensure_ascii=False,
            )
        )
        return 1

    account = getattr(response.account, "root", None)
    payload = {
        "authenticated": account is not None,
        "requiresOpenaiAuth": response.requires_openai_auth,
        "accountType": getattr(account, "type", None),
        "planType": _value(getattr(account, "plan_type", None)),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if account is not None else 1


def login_device() -> int:
    with Codex() as codex:
        login = codex.login_chatgpt_device_code()
        print(f"Verification URL: {login.verification_url}", flush=True)
        print(f"User code: {login.user_code}", flush=True)
        result = login.wait()

    print(json.dumps({"success": result.success, "error": result.error}))
    return 0 if result.success else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "login-device"))
    args = parser.parse_args()
    return show_status() if args.command == "status" else login_device()


if __name__ == "__main__":
    raise SystemExit(main())
