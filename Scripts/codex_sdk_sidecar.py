#!/usr/bin/env python3
"""Run one Codex SDK turn through a strict JSON stdin/stdout contract."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any


MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_ERROR_CHARS = 2_000
ALLOWED_FIELDS = {
    "model",
    "prompt",
    "systemPrompt",
    "workingDirectory",
    "sandbox",
    "codexExecutable",
}
ALLOWED_SANDBOXES = {"read-only", "workspace-write"}
BASE_INSTRUCTIONS = (
    "Act as a stateless model provider. Answer the supplied conversation directly. "
    "Do not inspect files, run commands, or use tools. Return only the requested answer."
)


@dataclass(slots=True)
class RequestError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def load_request(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_INPUT_BYTES:
        raise RequestError("input_too_large", "Input exceeds the 16 MiB limit.")

    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RequestError("invalid_utf8", "Input must be UTF-8 JSON.") from exc

    try:
        request = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise RequestError("invalid_json", "Input must be one JSON object.") from exc

    if not isinstance(request, dict):
        raise RequestError("invalid_request", "Input must be one JSON object.")

    unknown = sorted(set(request) - ALLOWED_FIELDS)
    if unknown:
        raise RequestError(
            "unknown_field",
            f"Unsupported request field: {unknown[0]}",
        )

    _required_text(request, "model", max_chars=200)
    _required_text(request, "prompt", max_chars=MAX_INPUT_BYTES)
    working_directory = _required_text(
        request, "workingDirectory", max_chars=4_096
    )
    if not os.path.isabs(working_directory):
        raise RequestError(
            "invalid_working_directory",
            "workingDirectory must be an absolute path.",
        )
    if not os.path.isdir(working_directory):
        raise RequestError(
            "invalid_working_directory",
            "workingDirectory must reference an existing directory.",
        )

    system_prompt = request.get("systemPrompt")
    if system_prompt is not None and not isinstance(system_prompt, str):
        raise RequestError("invalid_field", "systemPrompt must be a string or null.")
    if isinstance(system_prompt, str) and len(system_prompt) > MAX_INPUT_BYTES:
        raise RequestError("input_too_large", "systemPrompt exceeds the 16 MiB limit.")

    sandbox = request.get("sandbox", "read-only")
    if sandbox not in ALLOWED_SANDBOXES:
        raise RequestError(
            "invalid_sandbox",
            "sandbox must be read-only or workspace-write.",
        )

    codex_executable = request.get("codexExecutable")
    if codex_executable is not None:
        if not isinstance(codex_executable, str) or not codex_executable.strip():
            raise RequestError(
                "invalid_field", "codexExecutable must be a non-empty string or null."
            )
        if len(codex_executable) > 4_096:
            raise RequestError("invalid_field", "codexExecutable is too long.")

    return request


def _required_text(
    request: dict[str, Any], field: str, *, max_chars: int
) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RequestError("missing_field", f"{field} must be a non-empty string.")
    if len(value) > max_chars:
        raise RequestError("input_too_large", f"{field} exceeds its size limit.")
    return value


def run_request(request: dict[str, Any]) -> dict[str, Any]:
    from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox

    sandbox = {
        "read-only": Sandbox.read_only,
        "workspace-write": Sandbox.workspace_write,
    }[request.get("sandbox", "read-only")]
    working_directory = request["workingDirectory"]
    config = CodexConfig(
        codex_bin=request.get("codexExecutable"),
        cwd=working_directory,
    )

    with Codex(config) as codex:
        thread = codex.thread_start(
            approval_mode=ApprovalMode.deny_all,
            base_instructions=BASE_INSTRUCTIONS,
            developer_instructions=request.get("systemPrompt") or None,
            cwd=working_directory,
            ephemeral=True,
            model=request["model"],
            sandbox=sandbox,
        )
        result = thread.run(
            request["prompt"],
            approval_mode=ApprovalMode.deny_all,
            cwd=working_directory,
            model=request["model"],
            sandbox=sandbox,
        )

    response = result.final_response
    if not isinstance(response, str) or not response.strip():
        raise RequestError(
            "empty_response", "Codex SDK completed without a final response."
        )

    status = getattr(result.status, "value", str(result.status))
    return {"ok": True, "text": response, "status": status}


def _safe_error_message(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    if not message:
        message = type(exc).__name__
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
    return message[:MAX_ERROR_CHARS]


def _write_response(payload: dict[str, Any]) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    sys.stdout.write(serialized)
    sys.stdout.write("\n")
    sys.stdout.flush()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        request = load_request(raw)
        _write_response(run_request(request))
        return 0
    except RequestError as exc:
        _write_response(
            {"ok": False, "error": {"code": exc.code, "message": exc.message}}
        )
        return 2
    except Exception as exc:  # SDK/runtime errors must remain structured.
        _write_response(
            {
                "ok": False,
                "error": {
                    "code": "codex_sdk_error",
                    "message": _safe_error_message(exc),
                },
            }
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
