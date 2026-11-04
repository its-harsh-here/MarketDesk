#!/usr/bin/env python3
"""A local stand-in for the AI providers (Groq chat completions and the xAI Responses API), for browser tests only.

Answers POST /v1/responses with a structured answer that cites the first source it was given, quoting that source's
price so MarketDesk's figure check can verify it. Usage reports a fixed cost so budgets can be exercised.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        path = self.path.rstrip("/")
        if path not in ("/v1/responses", "/openai/v1/chat/completions") or not self.headers.get(
            "Authorization", ""
        ).startswith("Bearer "):
            self.send_response(404)
            self.end_headers()
            return
        chat = path.endswith("/chat/completions")
        payload = json.loads(body["messages"][1]["content"] if chat else body["input"][0]["content"])
        src = payload["sources"][0]
        price = (src.get("data") or {}).get("price")
        answer = {
            "headline": f"Test-harness answer for {payload['listings'][0]['symbol']} (fake AI endpoint)",
            "sections": [
                {
                    "title": "What the evidence shows",
                    "points": [
                        {"text": f"The last observed price was {price} {src['data'].get('currency')}.",
                         "kind": "fact", "sources": [src["id"]], "certainty": None},
                        {"text": "This is sample data from the test harness, so no conclusion should be drawn.",
                         "kind": "interpretation", "sources": [src["id"]], "certainty": "possible"},
                    ],
                }
            ],
            "uncertainties": ["The test harness uses fictitious companies."],
            "gaps": ["No filings exist for sample listings."],
        }  # fmt: skip
        if chat:
            out = {
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": json.dumps(answer)}}],
                "usage": {"prompt_tokens": 2600, "completion_tokens": 640, "total_tokens": 3240},
            }  # fmt: skip
            return self._send(out, {"x-ratelimit-remaining-requests": "999", "x-ratelimit-remaining-tokens": "4760"})
        out = {
            "id": "resp_fake",
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}],
            "usage": {"input_tokens": 3200, "output_tokens": 420, "cost_in_usd_ticks": 50_000_000},
        }
        self._send(out, {})

    def _send(self, out: dict, headers: dict) -> None:
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
