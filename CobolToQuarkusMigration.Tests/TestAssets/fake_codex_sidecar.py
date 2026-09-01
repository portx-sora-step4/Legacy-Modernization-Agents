#!/usr/bin/env python3
import json
import sys
import time


request = json.load(sys.stdin)
prompt = request.get("prompt", "")

if "sleep" in prompt:
    time.sleep(5)

if "fail" in prompt:
    print(
        json.dumps(
            {
                "ok": False,
                "error": {"code": "fake_failure", "message": "expected failure"},
            }
        )
    )
    raise SystemExit(2)

print(
    json.dumps(
        {
            "ok": True,
            "text": (
                f"model={request['model']};sandbox={request['sandbox']};"
                f"prompt={prompt};hasApiKey={'apiKey' in request}"
            ),
            "status": "completed",
        }
    )
)
