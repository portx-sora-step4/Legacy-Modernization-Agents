from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


AUTH_PATH = Path(__file__).resolve().parents[1] / "codex_sdk_auth.py"
SPEC = importlib.util.spec_from_file_location("codex_sdk_auth", AUTH_PATH)
assert SPEC is not None and SPEC.loader is not None
AUTH = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {"openai_codex": types.SimpleNamespace(Codex=object)}):
    SPEC.loader.exec_module(AUTH)


class _ContextCodex:
    def __init__(self, login) -> None:
        self.login = login

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def login_chatgpt_device_code(self):
        return self.login


class _Login:
    verification_url = "https://example.invalid/device"
    user_code = "ABCD-EFGH"

    def __init__(self, *, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def wait(self):
        if self.error is not None:
            raise self.error
        return self.result


class AuthContractTests(unittest.TestCase):
    def _run_login(self, codex_factory) -> tuple[int, list[str]]:
        output = io.StringIO()
        with patch.object(AUTH, "Codex", codex_factory), contextlib.redirect_stdout(output):
            exit_code = AUTH.login_device()
        return exit_code, output.getvalue().splitlines()

    def test_login_device_redacts_exception_from_wait(self) -> None:
        login = _Login(error=RuntimeError("access_token=must-not-leak"))

        exit_code, lines = self._run_login(lambda: _ContextCodex(login))

        payload = json.loads(lines[-1])
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["success"])
        self.assertNotIn("must-not-leak", payload["error"])
        self.assertIn("[REDACTED]", payload["error"])

    def test_login_device_redacts_result_error(self) -> None:
        result = types.SimpleNamespace(
            success=False,
            error="api_key:must-not-leak",
        )
        login = _Login(result=result)

        exit_code, lines = self._run_login(lambda: _ContextCodex(login))

        payload = json.loads(lines[-1])
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["success"])
        self.assertNotIn("must-not-leak", payload["error"])
        self.assertIn("[REDACTED]", payload["error"])


if __name__ == "__main__":
    unittest.main()
