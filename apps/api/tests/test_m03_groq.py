"""Groq free tier as the AI provider: chosen from the key, one strict structured call, token budget, evidence trimmed
to fit the per-request limit, failures, and the HTTP client."""

from __future__ import annotations

import copy
import io
import json
import time
import urllib.error

import pytest
from fastapi.testclient import TestClient

from marketdesk.api.app import create_app
from marketdesk.config import Settings
from marketdesk.providers.groq import GroqClient
from marketdesk.providers.xai import XaiError
from marketdesk.services.analyst import AnalystService, Evidence, compact_evidence

from .conftest import Api, make_settings, migrated

KEY = "gsk_" + "t" * 52  # the shape of a Groq key: 56 characters


def answer_json(text="SX:AURORA last traded at 169.80 INR.", sources=("S1",)) -> str:
    return json.dumps(
        {
            "headline": "Summary",
            "sections": [{"title": "Findings", "points": [
                {"text": text, "kind": "fact", "sources": list(sources), "certainty": None}]}],
            "uncertainties": [],
            "gaps": [],
        }
    )  # fmt: skip


def completion(content: str, finish="stop", prompt=3100, completion_tokens=900) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt + completion_tokens,
        },
    }


class FakeGroq(GroqClient):
    def __init__(self, script, model="openai/gpt-oss-120b"):
        super().__init__(KEY, "https://api.groq.com/openai/v1", model)
        self.script = list(script)
        self.bodies: list[dict] = []

    def chat(self, body: dict) -> dict:
        self.bodies.append(copy.deepcopy(body))
        nxt = self.script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


@pytest.fixture
def groq(tmp_path):
    s = migrated(make_settings(tmp_path, marketdesk_env="development", dev_auth_bypass=True, grok_api=KEY))
    app = create_app(s)
    with TestClient(app) as c:
        api = Api(c)
        api.refresh_csrf()

        def install(script, **settings):
            fake = FakeGroq(script)
            app.state.analyst = AnalystService(s.model_copy(update=settings), client=fake)
            return fake

        yield api, app, install


def ask(api, question="What changed?"):
    r = api.post("/api/ai/answers", json={"kind": "ask", "symbols": ["SX:AURORA"], "question": question})
    assert r.status_code == 202, r.text
    end = time.time() + 10
    while time.time() < end:
        a = api.get(f"/api/ai/answers/{r.json()['id']}").json()
        if a["status"] != "running":
            return a
        time.sleep(0.05)
    raise AssertionError("answer did not finish")


def test_a_groq_key_in_grok_api_selects_groq_and_its_free_model(groq):
    api, app, _ = groq
    st = api.get("/api/ai/status").json()
    assert st["provider"] == "groq" and st["provider_label"] == "Groq (free tier)" and st["enabled"]
    assert st["model"] == "openai/gpt-oss-120b" and st["tools"] == []
    assert st["key_format"] == "starts with 'gsk_', 56 characters" and KEY not in json.dumps(st)
    assert st["budget"]["tokens_limit"] == 150_000 and st["budget"]["limit_usd"] is None
    assert Settings(grok_api="xai-abc").effective_ai_provider == "xai"
    assert Settings(grok_api="gsk_abc", ai_provider="xai").effective_ai_provider == "xai"
    assert Settings(groq_api_key="gsk_abc", ai_model="qwen/qwen3.8-27b").effective_ai_model == "qwen/qwen3.8-27b"


def test_one_strict_structured_call_without_tools(groq):
    api, _, install = groq
    fake = install([completion(answer_json())])
    a = ask(api)
    assert a["status"] == "done" and a["flag_count"] == 0 and a["model"] == "openai/gpt-oss-120b"
    (body,) = fake.bodies
    rf = body["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert "pattern" not in json.dumps(rf) and "maxLength" not in json.dumps(rf)  # lean schema for Groq
    assert "tools" not in body and body["reasoning_effort"] == "low" and body["include_reasoning"] is False
    assert body["max_completion_tokens"] == 2800 and body["messages"][0]["role"] == "system"
    assert a["usage"]["input_tokens"] == 3100 and a["usage"]["output_tokens"] == 900
    assert a["usage"]["cost_source"] == "Groq free tier: not billed" and a["cost_usd"] == "0"
    budget = api.get("/api/ai/status").json()["budget"]
    assert budget["tokens_used"] == 4000 and budget["requests_used"] == 1 and budget["spent_usd"] == "0"


def test_daily_token_allowance_refuses_before_calling(groq):
    api, _, install = groq
    fake = install([], ai_daily_tokens=1000)
    a = ask(api)
    assert a["status"] == "refused" and "Daily token allowance" in a["error"] and fake.bodies == []


@pytest.mark.parametrize(
    "script,error,counted",
    [
        ([completion('{"headline": "x"', finish="length")], "ran out of output tokens", 4000),
        ([XaiError("rate_limited", "Groq free-tier rate limit reached (HTTP 429).", 429)],
         "rate limit", 0),
        ([XaiError("too_large", "The request is larger than Groq allows for this model: limit 8000")], "larger", 0),
    ],
)  # fmt: skip
def test_failures_are_explained_and_count_only_real_usage(groq, script, error, counted):
    api, _, install = groq
    install(script)
    a = ask(api)
    assert a["status"] == "failed" and error in a["error"]
    assert api.get("/api/ai/status").json()["budget"]["tokens_used"] == counted


def test_rejected_optional_settings_are_dropped_once(groq):
    api, _, install = groq
    fake = install(
        [
            XaiError("bad_request", "Groq refused the request (HTTP 400): include_reasoning is not supported", 400),
            completion(answer_json()),
        ]
    )
    assert ask(api)["status"] == "done"
    assert "include_reasoning" in fake.bodies[0] and "include_reasoning" not in fake.bodies[1]
    fake = install(
        [
            XaiError(
                "bad_request", "Groq refused the request (HTTP 400): json_schema is not supported for this model", 400
            ),
            completion(answer_json()),
        ]
    )
    assert ask(api, question="other")["status"] == "done"
    assert fake.bodies[1]["response_format"] == {"type": "json_object"}
    assert "Return only a JSON object" in fake.bodies[1]["messages"][0]["content"]


def test_evidence_is_trimmed_to_fit_with_stable_source_ids():
    ev = Evidence()
    ev.add("quote", "q", {"price": "1"})
    ev.add("statements", "a", {"period": "annual", "period_ends": ["4", "3", "2"],
           "lines": {"revenue": [{"period_end": p, "value": "1" * 12, "form": "10-K", "accession": "a" * 20}
                                 for p in "432"]}})  # fmt: skip
    ev.add("statements", "q", {"period": "quarterly", "period_ends": list("4321"),
           "lines": {f"l{i}": [{"period_end": p, "value": "2" * 12, "form": "10-Q", "accession": "b" * 20}
                               for p in "4321"] for i in range(12)}})  # fmt: skip
    ev.add("filings", "f", [{"form": "8-K", "filing_date": "2026-01-01", "report_date": None, "accession": "c" * 20,
                             "description": "d" * 80, "items": ["2.02"]} for _ in range(15)])  # fmt: skip
    ev.add("filing_text", "t", {"form": "8-K", "filing_date": "2026-01-01", "text": "x" * 12_000})
    before = [s["id"] for s in ev.sources]
    trims = compact_evidence(ev, 6000, 0)
    assert [s["id"] for s in ev.sources] == before
    assert len(json.dumps(ev.sources)) <= 6000 and trims[0] == "filing excerpts shortened"
    assert ev.sources[0]["data"] == {"price": "1"}  # the quote is never trimmed
    assert compact_evidence(ev, 10**6, 0) == []  # nothing to do when it already fits


def test_groq_client_http_behaviour(monkeypatch):
    client = GroqClient(f' "{KEY}" ', "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", retries=0)

    class Resp(io.BytesIO):
        headers = {"x-ratelimit-remaining-requests": "998", "x-ratelimit-remaining-tokens": "7100"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def ok(req, timeout):
        assert req.get_header("Authorization") == f"Bearer {KEY}"  # quotes stripped
        assert json.loads(req.data)["model"] == "openai/gpt-oss-120b"
        return Resp(json.dumps(completion(answer_json())).encode())

    monkeypatch.setattr("urllib.request.urlopen", ok)
    assert client.chat({"messages": []})["choices"][0]["finish_reason"] == "stop"
    assert client.last_limits["remaining_requests_today"] == "998"

    def fail(code, message, headers=None):
        def raiser(req, timeout):
            body = io.BytesIO(json.dumps({"error": {"message": message}}).encode())
            raise urllib.error.HTTPError(req.full_url, code, "x", headers or {}, body)

        return raiser

    monkeypatch.setattr("urllib.request.urlopen", fail(401, "Invalid API Key"))
    with pytest.raises(XaiError) as err:
        client.chat({"messages": []})
    assert err.value.kind == "auth" and "console.groq.com" in err.value.message and KEY not in err.value.message
    monkeypatch.setattr("urllib.request.urlopen", fail(413, "Request too large: limit 8000, requested 9100"))
    with pytest.raises(XaiError) as err:
        client.chat({"messages": []})
    assert err.value.kind == "too_large" and "8000" in err.value.message
    monkeypatch.setattr("urllib.request.urlopen", fail(429, "Rate limit reached", {"retry-after": "45"}))
    with pytest.raises(XaiError) as err:
        client.chat({"messages": []})
    assert err.value.kind == "rate_limited" and "about 45 seconds" in err.value.message


def test_over_long_answers_are_clipped_and_flagged_not_discarded(groq):
    api, _, install = groq
    long = json.dumps(
        {
            "headline": "H" * 400,
            "sections": [{"title": "T", "points": [
                {"text": "SX:AURORA last traded at 169.80 INR. " + "x" * 700, "kind": "fact", "sources": ["S1"],
                 "certainty": None}] * 9}],
            "uncertainties": ["u"] * 10,
            "gaps": [],
        }
    )  # fmt: skip
    install([completion(long)])
    a = ask(api)
    assert a["status"] == "done"
    assert len(a["output"]["headline"]) == 300 and len(a["output"]["sections"][0]["points"]) == 8
    issues = [f["issue"] for f in a["flags"]]
    assert "1 extra point(s) dropped." in issues and "Long point shortened to 600 characters." in issues
