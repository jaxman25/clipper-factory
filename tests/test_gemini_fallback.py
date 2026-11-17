"""Stage 1/2: mocked Gemini fallback, request, and parsing tests.

No live provider calls are made here.  The tests assert the fallback contract,
request configuration, finish-reason handling, and key-free diagnostics.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

import requests

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend import transform  # noqa: E402

TEXT = (
    "In the village the elders gathered at midnight and told the children "
    "a story about the river that never sleeps."
)


def _response(payload: dict):
    response = mock.Mock()
    response.status_code = 200
    response.headers = {}
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def _ok(text: str = TEXT, finish_reason: str | None = None):
    candidate = {"content": {"parts": [{"text": text}]}}
    if finish_reason:
        candidate["finishReason"] = finish_reason
    return _response({"candidates": [candidate]})


def _parts(parts: list[dict], finish_reason: str = "STOP"):
    return _response(
        {
            "candidates": [
                {"content": {"parts": parts}, "finishReason": finish_reason}
            ]
        }
    )


def _blocked(reason: str = "SAFETY"):
    return _response({"promptFeedback": {"blockReason": reason}})


def _empty():
    response = mock.Mock()
    response.status_code = 200
    response.headers = {}
    response.raise_for_status.return_value = None
    response.json.return_value = {"candidates": []}
    return response


def _failure(status: int, payload: dict | None = None, headers: dict | None = None):
    response = mock.Mock()
    response.status_code = status
    response.headers = headers or {}
    response.json.return_value = payload or {
        "error": {"code": status, "status": "ERROR", "message": f"{status} error"}
    }
    error = requests.HTTPError(f"{status} error", response=response)
    response.raise_for_status.side_effect = error
    return response


def _quota_payload(kind: str, delay: str) -> dict:
    return {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "message": "quota exceeded",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "quotaId": (
                                "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
                                if kind == "day"
                                else "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
                            ),
                            "quotaMetric": (
                                "generativelanguage.googleapis.com/"
                                "generate_content_free_tier_requests"
                            ),
                        }
                    ],
                },
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": delay,
                },
            ],
        }
    }


class GeminiFallbackStage1Tests(unittest.TestCase):
    def setUp(self):
        self.sleep = mock.patch.object(transform, "_sleep").start()
        self.addCleanup(mock.patch.stopall)

    def _env(self, primary: str = "gemini-test-model", fallbacks: str = "gemini-next-model"):
        return mock.patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "gemini",
                "LLM_API_KEY": "fake-key",
                "LLM_MODEL": primary,
                "LLM_MODEL_FALLBACKS": fallbacks,
            },
        )

    def _run(self, side_effect):
        with self._env(), mock.patch.object(
            transform, "DEFAULT_GEMINI_FALLBACKS", ()
        ), mock.patch("requests.post", side_effect=side_effect) as post:
            script, source = transform.rewrite_script(
                "The village waited for dawn. " * 6
            )
        return script, source, post

    def test_default_order_is_lite_then_36_then_38(self):
        with mock.patch.dict(
            os.environ,
            {"LLM_MODEL": "", "LLM_MODEL_FALLBACKS": ""},
        ):
            self.assertEqual(
                transform._gemini_model_candidates(),
                [
                    "gemini-3.5-flash-lite",
                    "gemini-3.6-flash",
                    "gemini-3.8-flash",
                ],
            )

    def test_404_advances_to_the_next_model(self):
        script, source, post = self._run([_failure(404), _ok()])

        self.assertEqual(source, "gemini")
        self.assertIn("elders", script)
        self.assertEqual(post.call_count, 2)
        self.assertIn("gemini-test-model", post.call_args_list[0].args[0])
        self.assertIn("gemini-next-model", post.call_args_list[1].args[0])
        self.assertFalse(self.sleep.called)
        self.assertEqual(transform.LAST_ATTEMPTS[0]["error_class"], "not_found")
        self.assertEqual(transform.LAST_ATTEMPTS[0]["outcome"], "next_model")
        self.assertEqual(transform.LAST_ATTEMPTS[1]["outcome"], "success")

    def test_daily_quota_skips_without_waiting(self):
        script, source, post = self._run(
            [_failure(429, _quota_payload("day", "75064s")), _ok()]
        )

        self.assertEqual(source, "gemini")
        self.assertEqual(post.call_count, 2)
        self.assertFalse(self.sleep.called)
        self.assertEqual(transform.LAST_ATTEMPTS[0]["status"], 429)
        self.assertEqual(transform.LAST_ATTEMPTS[0]["outcome"], "next_model")
        self.assertEqual(transform.LAST_ATTEMPTS[1]["outcome"], "success")

    def test_short_per_minute_quota_retries_once(self):
        script, source, post = self._run(
            [_failure(429, _quota_payload("minute", "2s")), _ok()]
        )

        self.assertEqual(source, "gemini")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].args[0], post.call_args_list[1].args[0])
        self.sleep.assert_called_once_with(2.0)
        self.assertEqual(transform.LAST_ATTEMPTS[0]["outcome"], "retry")
        self.assertEqual(transform.LAST_ATTEMPTS[1]["outcome"], "success")

    def test_504_retries_once_then_advances(self):
        script, source, post = self._run(
            [_failure(504), _failure(504), _ok()]
        )

        self.assertEqual(source, "gemini")
        self.assertEqual(post.call_count, 3)
        self.sleep.assert_called_once_with(transform.RETRY_BACKOFF_SECONDS)
        self.assertEqual(transform.LAST_ATTEMPTS[0]["outcome"], "retry")
        self.assertEqual(transform.LAST_ATTEMPTS[1]["outcome"], "next_model")
        self.assertEqual(transform.LAST_ATTEMPTS[2]["outcome"], "success")

    def test_timeout_retries_once_then_advances(self):
        timeout = requests.exceptions.Timeout("read timed out")
        script, source, post = self._run([timeout, timeout, _ok()])

        self.assertEqual(source, "gemini")
        self.assertEqual(post.call_count, 3)
        self.sleep.assert_called_once_with(transform.RETRY_BACKOFF_SECONDS)
        self.assertEqual(transform.LAST_ATTEMPTS[1]["error_class"], "timeout")
        self.assertEqual(transform.LAST_ATTEMPTS[1]["outcome"], "next_model")
        self.assertEqual(transform.LAST_ATTEMPTS[2]["outcome"], "success")

    def test_400_401_403_stop_without_retrying(self):
        for status in (400, 401, 403):
            with self.subTest(status=status):
                self.sleep.reset_mock()
                script, source, post = self._run([_failure(status), _ok()])

                self.assertEqual(source, "template")
                self.assertTrue(script)
                self.assertEqual(post.call_count, 1)
                self.assertFalse(self.sleep.called)
                self.assertEqual(transform.LAST_ATTEMPTS[0]["status"], status)
                self.assertEqual(transform.LAST_ATTEMPTS[0]["outcome"], "stop")

    def test_all_models_failing_never_reports_gemini_success(self):
        script, source, post = self._run([_failure(404), _failure(404)])

        self.assertEqual(source, "template")
        self.assertTrue(script)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(transform.LAST_MODEL, "")
        self.assertTrue(
            all(attempt["outcome"] != "success" for attempt in transform.LAST_ATTEMPTS)
        )

    def test_empty_response_is_not_a_gemini_success(self):
        script, source, post = self._run([_empty(), _ok()])

        self.assertEqual(source, "gemini")
        self.assertEqual(post.call_count, 2)
        self.sleep.assert_called_once_with(transform.RETRY_BACKOFF_SECONDS)
        self.assertEqual(transform.LAST_ATTEMPTS[0]["status"], 200)
        self.assertEqual(transform.LAST_ATTEMPTS[0]["error_class"], "empty_response")
        self.assertEqual(transform.LAST_ATTEMPTS[0]["outcome"], "retry")
        self.assertEqual(transform.LAST_ATTEMPTS[1]["outcome"], "success")

    def test_structured_attempts_have_required_fields(self):
        self._run([_failure(404), _ok()])

        required = {
            "model",
            "attempt",
            "status",
            "error_class",
            "elapsed_ms",
            "outcome",
            "retry_delay_s",
        }
        for attempt in transform.LAST_ATTEMPTS:
            self.assertEqual(set(attempt), required)
            self.assertIsInstance(attempt["elapsed_ms"], int)
            self.assertGreaterEqual(attempt["elapsed_ms"], 0)

    def test_script_request_has_system_instruction_and_generation_config(self):
        script, source, post = self._run([_ok()])

        self.assertEqual(source, "gemini")
        body = post.call_args.kwargs["json"]
        self.assertEqual(
            body["systemInstruction"]["parts"][0]["text"],
            transform.REWRITE_SYSTEM,
        )
        self.assertEqual(body["contents"][0]["role"], "user")
        self.assertIn("Raw transcript", body["contents"][0]["parts"][0]["text"])
        config = body["generationConfig"]
        self.assertEqual(config["temperature"], transform.REWRITE_TEMPERATURE)
        self.assertEqual(
            config["maxOutputTokens"], transform.REWRITE_MAX_OUTPUT_TOKENS
        )
        self.assertEqual(config["responseMimeType"], "text/plain")
        self.assertEqual(config["thinkingConfig"]["thinkingLevel"], "low")

    def test_flash_lite_request_uses_minimal_thinking(self):
        with self._env(primary="gemini-3.5-flash-lite", fallbacks=""), mock.patch.object(
            transform, "DEFAULT_GEMINI_FALLBACKS", ()
        ), mock.patch("requests.post", return_value=_ok()) as post:
            script, source = transform.rewrite_script(
                "The village waited for dawn. " * 6
            )

        self.assertEqual(source, "gemini")
        body = post.call_args.kwargs["json"]
        self.assertEqual(
            body["generationConfig"]["thinkingConfig"]["thinkingLevel"],
            "minimal",
        )

    def test_metadata_request_uses_json_mime_and_schema(self):
        payload = {
            "titles": ["Title one", "Title two", "Title three"],
            "descriptions": ["One sentence.", "Two sentence.", "Three sentence."],
            "hashtags": [["#a", "#b", "#c", "#d", "#e"]] * 3,
        }
        with self._env(primary="gemini-test-model", fallbacks=""), mock.patch.object(
            transform, "DEFAULT_GEMINI_FALLBACKS", ()
        ), mock.patch(
            "requests.post", return_value=_ok(json.dumps(payload))
        ) as post:
            meta, source = transform.generate_metadata("A village story.")

        self.assertEqual(source, "gemini")
        self.assertEqual(len(meta["titles"]), 3)
        body = post.call_args.kwargs["json"]
        self.assertEqual(
            body["systemInstruction"]["parts"][0]["text"],
            transform.METADATA_SYSTEM,
        )
        config = body["generationConfig"]
        self.assertEqual(config["temperature"], transform.METADATA_TEMPERATURE)
        self.assertEqual(
            config["maxOutputTokens"], transform.METADATA_MAX_OUTPUT_TOKENS
        )
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(
            config["responseSchema"], transform.METADATA_RESPONSE_SCHEMA
        )

    def test_blocked_prompt_retries_once_then_advances(self):
        script, source, post = self._run([_blocked("SAFETY"), _ok()])

        self.assertEqual(source, "gemini")
        self.assertEqual(post.call_count, 2)
        self.sleep.assert_called_once_with(transform.RETRY_BACKOFF_SECONDS)
        self.assertEqual(transform.LAST_ATTEMPTS[0]["error_class"], "blocked_response")
        self.assertEqual(transform.LAST_ATTEMPTS[0]["outcome"], "retry")
        self.assertEqual(transform.LAST_ATTEMPTS[1]["outcome"], "success")

    def test_safety_finish_reason_is_blocked_not_success(self):
        script, source, post = self._run([_ok(TEXT, "SAFETY"), _ok()])

        self.assertEqual(source, "gemini")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(transform.LAST_ATTEMPTS[0]["error_class"], "blocked_response")
        self.assertEqual(transform.LAST_ATTEMPTS[0]["outcome"], "retry")

    def test_max_tokens_finish_reason_is_truncated_not_success(self):
        script, source, post = self._run([_ok(TEXT, "MAX_TOKENS"), _ok()])

        self.assertEqual(source, "gemini")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(
            transform.LAST_ATTEMPTS[0]["error_class"], "truncated_response"
        )
        self.assertEqual(transform.LAST_ATTEMPTS[0]["outcome"], "retry")

    def test_unknown_finish_reason_is_invalid_not_success(self):
        script, source, post = self._run([_ok(TEXT, "OTHER"), _ok()])

        self.assertEqual(source, "gemini")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(transform.LAST_ATTEMPTS[0]["error_class"], "invalid_response")
        self.assertEqual(transform.LAST_ATTEMPTS[0]["outcome"], "retry")

    def test_thought_parts_are_not_used_as_script_text(self):
        response = _parts(
            [
                {"text": "internal reasoning that must not be spoken", "thought": True},
                {"text": TEXT},
            ]
        )
        script, source, post = self._run([response])

        self.assertEqual(source, "gemini")
        self.assertNotIn("internal reasoning", script)
        self.assertIn("elders", script)

    def test_invalid_metadata_json_retries_once_then_succeeds(self):
        payload = {
            "titles": ["Title one", "Title two", "Title three"],
            "descriptions": ["One sentence.", "Two sentence.", "Three sentence."],
            "hashtags": [["#a", "#b", "#c", "#d", "#e"]] * 3,
        }
        with self._env(primary="gemini-test-model", fallbacks=""), mock.patch.object(
            transform, "DEFAULT_GEMINI_FALLBACKS", ()
        ), mock.patch(
            "requests.post",
            side_effect=[_ok("not json"), _ok(json.dumps(payload))],
        ) as post:
            meta, source = transform.generate_metadata("A village story.")

        self.assertEqual(source, "gemini")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(len(meta["titles"]), 3)

    def test_invalid_metadata_json_twice_falls_back_to_template(self):
        with self._env(primary="gemini-test-model", fallbacks=""), mock.patch.object(
            transform, "DEFAULT_GEMINI_FALLBACKS", ()
        ), mock.patch(
            "requests.post",
            side_effect=[_ok("not json"), _ok("still not json")],
        ) as post:
            meta, source = transform.generate_metadata("A village story.")

        self.assertEqual(source, "template")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(len(meta["titles"]), 3)

    def test_api_key_never_appears_in_logs_or_diagnostics(self):
        key = "FAKE-GEMINI-KEY-0123456789"
        logged: list[tuple[str, str, dict]] = []

        def record(level: str):
            def _record(message: str, **fields):
                logged.append((level, message, fields))

            return _record

        def fake_post(url, **kwargs):
            raise RuntimeError(f"404 Client Error for {url}?key={key}")

        with mock.patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "gemini",
                "LLM_API_KEY": key,
                "LLM_MODEL": "gemini-test-model",
                "LLM_MODEL_FALLBACKS": "",
            },
        ), mock.patch.object(
            transform, "DEFAULT_GEMINI_FALLBACKS", ()
        ), mock.patch.object(
            transform.common, "warn", side_effect=record("warn")
        ), mock.patch.object(
            transform.common, "info", side_effect=record("info")
        ), mock.patch(
            "requests.post", side_effect=fake_post
        ):
            script, source = transform.rewrite_script(
                "The village waited for dawn. " * 6
            )

        self.assertEqual(source, "template")
        self.assertTrue(script)
        rendered = repr(logged) + repr(transform.LAST_ATTEMPTS)
        self.assertNotIn(key, rendered)
        self.assertIn("LLM rewrite failed", " ".join(item[1] for item in logged))
        self.assertNotIn(key, transform.LAST_FALLBACK_REASON)


if __name__ == "__main__":
    unittest.main(verbosity=2)
