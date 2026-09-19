"""Minimal LLM API connectivity probe.

Reads credentials from testAPI.txt (never printed, never committed).
Prints ONLY status codes and sanitized response metadata - no key material.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def load_credentials() -> tuple[str, str]:
    text = (ROOT / "testAPI.txt").read_text(encoding="utf-8")
    url_m = re.search(r"URL[：:]\s*(\S+)", text)
    key_m = re.search(r"Key[：:]\s*(\S+)", text)
    if not url_m or not key_m:
        print("FATAL: could not parse credentials file", file=sys.stderr)
        sys.exit(1)
    return url_m.group(1).rstrip("/"), key_m.group(1)


def sanitize(obj: object, key: str) -> str:
    s = json.dumps(obj, ensure_ascii=False)[:2000]
    return s.replace(key, "***REDACTED***")


def main() -> None:
    base_url, key = load_credentials()
    headers_variants = [
        {"Authorization": f"Bearer {key}"},
        {"api-key": key},
        {"Ocp-Apim-Subscription-Key": key},
    ]
    paths = ["/responses", "/v1/responses"]
    payload = {
        "model": sys.argv[1] if len(sys.argv) > 1 else "gpt-5.6-luna",
        "input": "Reply with exactly: PONG",
        "max_output_tokens": 512,
    }
    client = httpx.Client(timeout=60)
    for path in paths:
        for i, headers in enumerate(headers_variants):
            try:
                r = client.post(base_url + path, json=payload,
                                headers={**headers, "Content-Type": "application/json"})
                print(f"[{path}] header-variant#{i} -> HTTP {r.status_code}")
                if r.status_code == 200:
                    data = r.json()
                    print("SUCCESS. Sanitized response excerpt:")
                    print(sanitize(data, key))
                    return
                else:
                    print("  body:", sanitize(r.text[:300], key))
            except Exception as e:  # noqa: BLE001
                msg = str(e).replace(key, "***")
                print(f"[{path}] header-variant#{i} -> EXC {type(e).__name__}: {msg[:200]}")
    print("No variant succeeded.")


if __name__ == "__main__":
    main()
