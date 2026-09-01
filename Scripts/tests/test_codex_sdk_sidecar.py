from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SIDECAR_PATH = Path(__file__).resolve().parents[1] / "codex_sdk_sidecar.py"
SPEC = importlib.util.spec_from_file_location("codex_sdk_sidecar", SIDECAR_PATH)
assert SPEC is not None and SPEC.loader is not None
SIDECAR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SIDECAR
SPEC.loader.exec_module(SIDECAR)


class _EnumValue:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeResult:
    final_response = "converted result"
    status = _EnumValue("completed")


class _FakeThread:
    def __init__(self, calls: dict) -> None:
        self.calls = calls

    def run(self, prompt: str, **kwargs):
        self.calls["run"] = {"prompt": prompt, **kwargs}
        return _FakeResult()


class _FakeCodex:
    def __init__(self, config, calls: dict) -> None:
        calls["config"] = config
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def thread_start(self, **kwargs):
        self.calls["thread_start"] = kwargs
        return _FakeThread(self.calls)


class SidecarContractTests(unittest.TestCase):
    def valid_request(self, working_directory: str) -> dict:
        return {
            "model": "gpt-5.4",
            "prompt": "Convert this program.",
            "systemPrompt": "Return Java only.",
            "workingDirectory": working_directory,
            "sandbox": "read-only",
            "codexExecutable": None,
        }

    def test_load_request_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as working_directory:
            request = self.valid_request(working_directory)
            request["apiKey"] = "must-not-be-accepted"

            with self.assertRaises(SIDECAR.RequestError) as caught:
                SIDECAR.load_request(json.dumps(request).encode("utf-8"))

        self.assertEqual("unknown_field", caught.exception.code)

    def test_load_request_requires_absolute_existing_working_directory(self) -> None:
        request = self.valid_request("relative/path")

        with self.assertRaises(SIDECAR.RequestError) as caught:
            SIDECAR.load_request(json.dumps(request).encode("utf-8"))

        self.assertEqual("invalid_working_directory", caught.exception.code)

    def test_load_request_rejects_full_access(self) -> None:
        with tempfile.TemporaryDirectory() as working_directory:
            request = self.valid_request(working_directory)
            request["sandbox"] = "full-access"

            with self.assertRaises(SIDECAR.RequestError) as caught:
                SIDECAR.load_request(json.dumps(request).encode("utf-8"))

        self.assertEqual("invalid_sandbox", caught.exception.code)

    def test_run_request_uses_ephemeral_deny_all_thread(self) -> None:
        calls: dict = {}

        class FakeConfig:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        fake_module = types.SimpleNamespace(
            ApprovalMode=types.SimpleNamespace(deny_all="deny-all"),
            Codex=lambda config: _FakeCodex(config, calls),
            CodexConfig=FakeConfig,
            Sandbox=types.SimpleNamespace(
                read_only="read-only", workspace_write="workspace-write"
            ),
        )

        with tempfile.TemporaryDirectory() as working_directory:
            request = self.valid_request(os.path.abspath(working_directory))
            with patch.dict(sys.modules, {"openai_codex": fake_module}):
                response = SIDECAR.run_request(request)

        self.assertEqual({"ok": True, "text": "converted result", "status": "completed"}, response)
        self.assertTrue(calls["thread_start"]["ephemeral"])
        self.assertEqual("deny-all", calls["thread_start"]["approval_mode"])
        self.assertEqual("read-only", calls["thread_start"]["sandbox"])
        self.assertEqual("Return Java only.", calls["thread_start"]["developer_instructions"])
        self.assertEqual("Convert this program.", calls["run"]["prompt"])

    def test_safe_error_message_redacts_common_credential_shapes(self) -> None:
        message = SIDECAR._safe_error_message(
            RuntimeError(
                "Authorization: Bearer secret-token "
                "access_token=access-secret api_key:api-secret sk-secretvalue"
            )
        )

        self.assertNotIn("secret-token", message)
        self.assertNotIn("access-secret", message)
        self.assertNotIn("api-secret", message)
        self.assertNotIn("sk-secretvalue", message)
        self.assertGreaterEqual(message.count("[REDACTED]"), 4)


if __name__ == "__main__":
    unittest.main()
