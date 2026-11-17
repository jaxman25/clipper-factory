"""Transform pipeline: free LLM script rewriting + edge-tts voiceover.

Two stages used by ``main.py --mode transform``:

1. ``rewrite_script`` turns the Whisper transcript into a transformative,
   copyright-safe narration script (3-second hook, payoff early, <59 s read).
   Providers are free-tier only: Google Gemini or OpenRouter, selected with
   LLM_PROVIDER / LLM_API_KEY. With no key - or on any provider error - it
   falls back to a deterministic template hook generator, so a paid OpenAI
   key is never required.

2. ``synthesize_voiceover`` reads the script with edge-tts (free neural
   voices) and captures the word-boundary timestamps the service streams
   alongside the audio. Those timestamps are saved next to the audio file as
   ``<name>.words.json`` so captions can sync perfectly to the voiceover.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Sequence

try:
    from backend import common
except ImportError:  # pragma: no cover - direct execution
    import common  # type: ignore

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
# Verified against the Gemini API catalogue on 2026-11-16.  2.5-flash is
# still listed globally but generation is closed to this project (HTTP 404),
# so it is filtered out of the effective chain even when .env still names it.
# The order is fastest/reliable first, then quality escalation.  LLM_MODEL
# still overrides the first attempt without editing .env.
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
DEFAULT_GEMINI_FALLBACKS = (
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
)
UNAVAILABLE_GEMINI_MODELS = frozenset({"gemini-2.5-flash"})
MAX_ATTEMPTS_PER_MODEL = 2
RETRY_BACKOFF_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 10.0
# Per-process trace read by the worker when it records job metadata.  The
# worker handles one job at a time, so this cannot mix two jobs' model ids.
LAST_MODEL = ""
LAST_FALLBACK_REASON = ""
LAST_ATTEMPTS: list[dict[str, Any]] = []
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3-8b-instruct:free"

DEFAULT_VOICE = "en-US-AriaNeural"
ALT_VOICE = "en-US-GuyNeural"
# edge-tts reads English at roughly 2.6 words/second; a 59 s slot is ~150 words.
WORDS_PER_SECOND = 2.6
MAX_SCRIPT_WORDS = 140
# A voiceover covering less than this share of the target is a mostly-silent
# output, not a valid 21/30/59 s variant. The variant is reported incomplete.
MIN_NARRATION_RATIO = 0.55
MAX_TRANSCRIPT_CHARS = 6000

REWRITE_SYSTEM = (
    "You are a short-form video scriptwriter who turns raw transcripts into "
    "original, transformative narration."
)

REWRITE_RULES = """\
Rules:
1. Open with a scroll-stopping hook that reads in 3 seconds (max 12 words).
2. Deliver the main payoff within the first 20 seconds.
3. The whole script must be readable in under 59 seconds: at most {max_words} words.
4. Add commentary and framing - never copy the transcript verbatim. This must
   be original transformative narration, not a reprint.
5. Plain text only: no emojis, no stage directions, no markdown, no quotes.

Return only the script text.
"""

REWRITE_TEMPERATURE = 0.6
REWRITE_MAX_OUTPUT_TOKENS = 2048
METADATA_TEMPERATURE = 0.3
METADATA_MAX_OUTPUT_TOKENS = 2048
METADATA_SYSTEM = (
    "You write metadata for short-form video clips (TikTok/Reels/Shorts)."
)
METADATA_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "titles": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
        "descriptions": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
        "hashtags": {
            "type": "ARRAY",
            "items": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
            },
        },
    },
    "required": ["titles", "descriptions", "hashtags"],
}


class LLMError(RuntimeError):
    """Raised only when the caller asks for a strict LLM result."""


class EmptyGeminiResponse(LLMError):
    """The provider returned HTTP 200 without usable candidate text."""


class BlockedGeminiResponse(LLMError):
    """The prompt or candidate was blocked before usable text was produced."""


class TruncatedGeminiResponse(LLMError):
    """The candidate hit the output limit before a complete answer."""


class InvalidGeminiResponse(LLMError):
    """The response shape or finish reason is not usable output."""


def _provider() -> str:
    return os.getenv("LLM_PROVIDER", "").strip().lower()


def _api_key() -> str:
    return os.getenv("LLM_API_KEY", "").strip()


def _clean(text: str) -> str:
    """Strip code fences and surrounding quotes from a model response."""
    out = (text or "").strip()
    if out.startswith("```"):
        out = out.split("\n", 1)[1] if "\n" in out else out
        out = out.rsplit("```", 1)[0]
    out = out.strip().strip('"').strip("'")
    return out.strip()


def _budget(script: str, max_words: int = MAX_SCRIPT_WORDS) -> str:
    words = script.split()
    if len(words) > max_words:
        words = words[:max_words]
    return " ".join(words)


def words_for_seconds(seconds: float) -> int:
    """Word budget for a platform target at edge-tts' ~2.6 words/second."""
    return max(8, int(max(1.0, float(seconds)) * WORDS_PER_SECOND))


def fit_script(script: str, max_words: int) -> str:
    """Trim narration to ``max_words`` without cutting a sentence in half.

    The 21 s and 30 s platform edits are derived from the piece's 59 s script
    with this helper: whole sentences are kept, so a shorter version still
    reads as a complete thought instead of stopping mid-clause. The opening
    hook sentence is always kept when it fits the budget.
    """
    words = (script or "").split()
    if not words:
        return ""
    if len(words) <= max_words:
        return " ".join(words)
    kept = words[:max_words]
    sentence_ends = [
        index
        for index, word in enumerate(kept)
        if any(word.endswith(mark) for mark in (".", "!", "?", ".\"", "?\"", "!'"))
    ]
    if sentence_ends and sentence_ends[-1] + 1 >= max(6, max_words // 3):
        kept = kept[: sentence_ends[-1] + 1]
    return " ".join(kept).strip()


def extend_script(script: str, source_text: str, max_words: int) -> str:
    """Extend a short script from the source transcript, without inventing.

    Used when a provider/fallback returns fewer words than the target read
    needs. Whole source sentences are appended until the word budget is met;
    duplicate sentences already present in the script are skipped. If the
    source has no more usable speech, the caller's duration check reports the
    variant as incomplete rather than padding it with silence.
    """
    current = (script or "").strip()
    words = current.split()
    budget = max(8, int(max_words))
    if len(words) >= budget:
        return _budget(current, budget)

    existing = re.sub(r"\s+", " ", current.lower())
    chunks = [
        chunk.strip()
        for chunk in re.split(r"(?<=[.!?])\s+", (source_text or "").strip())
        if chunk.strip()
    ]
    for chunk in chunks:
        normalized = re.sub(r"\s+", " ", chunk.lower())
        if not normalized or normalized in existing:
            continue
        remaining = budget - len(words)
        if remaining <= 0:
            break
        addition = chunk.split()[:remaining]
        words.extend(addition)
        existing = f"{existing} {normalized}"
    return _budget(" ".join(words).strip(), budget)


def _prompt(transcript: str, max_words: int = MAX_SCRIPT_WORDS) -> str:
    body = transcript[:MAX_TRANSCRIPT_CHARS]
    return (
        f"{REWRITE_RULES.format(max_words=max_words)}"
        f"\nRaw transcript:\n\"\"\"\n{body}\n\"\"\"\n"
    )


def _gemini_model_candidates() -> list[str]:
    configured = os.getenv("LLM_MODEL", "").strip()
    configured_fallbacks = [
        item.strip()
        for item in os.getenv("LLM_MODEL_FALLBACKS", "").split(",")
        if item.strip()
    ]
    candidates = [configured] if configured else []
    candidates.extend(configured_fallbacks)
    candidates.extend(DEFAULT_GEMINI_FALLBACKS)
    out: list[str] = []
    skipped_unavailable = False
    for model in candidates:
        if not model:
            continue
        if model in UNAVAILABLE_GEMINI_MODELS:
            if not skipped_unavailable:
                common.warn(
                    "Skipping Gemini model unavailable to this project",
                    model=model,
                )
                skipped_unavailable = True
            continue
        if model not in out:
            out.append(model)
    return out


def _gemini_status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _gemini_error_payload(exc: Exception) -> dict:
    response = getattr(exc, "response", None)
    if response is None:
        return {}
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _gemini_retry_delay(exc: Exception) -> float | None:
    """Read RetryInfo.retryDelay (``75064s``) or a numeric Retry-After."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    raw: Any = None
    if isinstance(headers, dict):
        raw = headers.get("Retry-After") or headers.get("retry-after")

    if raw is None:
        error = _gemini_error_payload(exc).get("error")
        if isinstance(error, dict):
            for detail in error.get("details") or []:
                if not isinstance(detail, dict):
                    continue
                if str(detail.get("@type", "")).endswith("RetryInfo"):
                    raw = detail.get("retryDelay")
                    break

    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text.endswith("s"):
        text = text[:-1]
    try:
        return max(0.0, float(text))
    except (TypeError, ValueError):
        return None


def _gemini_quota_kind(exc: Exception) -> str:
    """Distinguish a per-minute burst from a per-day quota exhaustion."""
    error = _gemini_error_payload(exc).get("error")
    values: list[str] = []
    if isinstance(error, dict):
        values.append(str(error.get("message", "")))
        for detail in error.get("details") or []:
            if not isinstance(detail, dict):
                continue
            for violation in detail.get("violations") or []:
                if not isinstance(violation, dict):
                    continue
                values.append(str(violation.get("quotaId", "")))
                values.append(str(violation.get("quotaMetric", "")))
    text = " ".join(values).lower().replace("_", " ").replace("-", " ")
    compact = text.replace(" ", "")
    if "perday" in compact or "per day" in text or "daily" in text:
        return "per_day"
    if "perminute" in compact or "per minute" in text:
        return "per_minute"
    return "unknown"


def _classify_gemini_error(exc: Exception) -> str:
    import requests

    status = _gemini_status(exc)
    if status == 404:
        return "not_found"
    if status == 429:
        return "quota"
    if status in (500, 502, 503, 504):
        return "server_error"
    if status in (400, 401, 403):
        return "invalid_request"
    if isinstance(exc, BlockedGeminiResponse):
        return "blocked_response"
    if isinstance(exc, TruncatedGeminiResponse):
        return "truncated_response"
    if isinstance(exc, InvalidGeminiResponse):
        return "invalid_response"
    if isinstance(exc, EmptyGeminiResponse):
        return "empty_response"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "network"
    if isinstance(exc, (KeyError, IndexError, TypeError, ValueError)):
        return "invalid_response"

    # ``requests`` is not always the source in tests/embedded calls.  These
    # string fallbacks keep the same classification when only an HTTP status
    # is present in the exception text.
    text = str(exc).lower()
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "connection" in text:
        return "network"
    if "404" in text:
        return "not_found"
    if "429" in text:
        return "quota"
    if "503" in text or "502" in text or "504" in text or "500" in text:
        return "server_error"
    if "400" in text or "401" in text or "403" in text:
        return "invalid_request"
    return "unknown"


_BLOCKED_FINISH_REASONS = frozenset(
    {
        "SAFETY",
        "RECITATION",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "IMAGE_SAFETY",
        "LANGUAGE",
    }
)


def _candidate_text(data: Any) -> str:
    """Extract complete candidate text, rejecting blocked/truncated output."""
    if not isinstance(data, dict):
        raise InvalidGeminiResponse("Gemini response is not a JSON object")

    feedback = data.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        reason = str(feedback.get("blockReason"))
        raise BlockedGeminiResponse(f"Gemini blocked the prompt ({reason})")

    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise EmptyGeminiResponse("Gemini returned no candidates")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise InvalidGeminiResponse("Gemini candidate is not an object")

    finish_reason = str(candidate.get("finishReason") or "").upper()
    if finish_reason in _BLOCKED_FINISH_REASONS:
        raise BlockedGeminiResponse(
            f"Gemini candidate was blocked ({finish_reason})"
        )
    if finish_reason == "MAX_TOKENS":
        raise TruncatedGeminiResponse(
            "Gemini candidate hit MAX_TOKENS before completing"
        )
    if finish_reason and finish_reason not in (
        "STOP",
        "FINISH_REASON_UNSPECIFIED",
    ):
        raise InvalidGeminiResponse(
            f"Gemini candidate has unusable finish reason ({finish_reason})"
        )

    content = candidate.get("content")
    if not isinstance(content, dict):
        raise EmptyGeminiResponse("Gemini candidate has no content")
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise EmptyGeminiResponse("Gemini candidate has no parts")
    text = "".join(
        str(part.get("text", ""))
        for part in parts
        if isinstance(part, dict) and not part.get("thought")
    )
    if not text.strip():
        raise EmptyGeminiResponse("Gemini candidate has no usable text")
    return text


def _gemini_status_from_response(response: Any) -> int:
    status = getattr(response, "status_code", None)
    try:
        return int(status) if status is not None else 200
    except (TypeError, ValueError):
        return 200


def _record_gemini_attempt(record: dict[str, Any]) -> None:
    LAST_ATTEMPTS.append(record)
    fields = dict(record)
    if record.get("outcome") == "success":
        common.info("Gemini attempt", **fields)
    else:
        common.warn("Gemini attempt", **fields)


def _sleep(seconds: float) -> None:
    """Separated so tests can exercise retries without real delays."""
    time.sleep(max(0.0, seconds))


def _next_model_outcome(index: int, models: list[str]) -> str:
    return "next_model" if index + 1 < len(models) else "exhausted"


def _thinking_level(model: str) -> str:
    """Flash-Lite defaults to minimal; the larger Flash models use low."""
    return "minimal" if "flash-lite" in model.lower() else "low"


def _gemini_system_instruction(mode: str) -> str:
    return METADATA_SYSTEM if mode == "metadata" else REWRITE_SYSTEM


def _gemini_generation_config(mode: str, model: str) -> dict[str, Any]:
    config: dict[str, Any] = {
        "temperature": (
            METADATA_TEMPERATURE if mode == "metadata" else REWRITE_TEMPERATURE
        ),
        "maxOutputTokens": (
            METADATA_MAX_OUTPUT_TOKENS
            if mode == "metadata"
            else REWRITE_MAX_OUTPUT_TOKENS
        ),
        "responseMimeType": (
            "application/json" if mode == "metadata" else "text/plain"
        ),
        "thinkingConfig": {"thinkingLevel": _thinking_level(model)},
    }
    if mode == "metadata":
        config["responseSchema"] = METADATA_RESPONSE_SCHEMA
    return config


def _gemini_payload(prompt: str, mode: str, model: str) -> dict[str, Any]:
    return {
        "systemInstruction": {
            "parts": [{"text": _gemini_system_instruction(mode)}]
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": _gemini_generation_config(mode, model),
    }


def _call_gemini(prompt: str, key: str, *, mode: str = "script") -> str:
    global LAST_MODEL, LAST_FALLBACK_REASON, LAST_ATTEMPTS
    import requests

    models = _gemini_model_candidates()
    LAST_ATTEMPTS = []
    last_error: Exception | None = None
    if not models:
        raise LLMError("No usable Gemini models are configured")

    for index, model in enumerate(models):
        url = GEMINI_ENDPOINT.format(model=model)
        for attempt in range(1, MAX_ATTEMPTS_PER_MODEL + 1):
            started = time.monotonic()
            response_status: int | None = None
            try:
                # The API key travels in a header, never in the query string:
                # ``requests`` quotes the full URL in its HTTPError text, which
                # would otherwise write the key into the activity log.
                response = requests.post(
                    url,
                    headers={"x-goog-api-key": key},
                    json=_gemini_payload(prompt, mode, model),
                    timeout=45,
                )
                response_status = _gemini_status_from_response(response)
                response.raise_for_status()
                text = _clean(_candidate_text(response.json()))
                if not text:
                    empty = EmptyGeminiResponse(
                        "Gemini returned HTTP 200 without candidate text"
                    )
                    empty.response = response  # type: ignore[attr-defined]
                    raise empty
                elapsed_ms = int((time.monotonic() - started) * 1000)
                _record_gemini_attempt(
                    {
                        "model": model,
                        "attempt": attempt,
                        "status": _gemini_status_from_response(response),
                        "error_class": None,
                        "elapsed_ms": elapsed_ms,
                        "outcome": "success",
                        "retry_delay_s": None,
                    }
                )
                LAST_MODEL = model
                if index > 0 and not LAST_FALLBACK_REASON:
                    LAST_FALLBACK_REASON = f"fallback to {model}"
                return text
            except Exception as exc:
                last_error = exc
                elapsed_ms = int((time.monotonic() - started) * 1000)
                status = _gemini_status(exc)
                if status is None:
                    status = response_status
                error_class = _classify_gemini_error(exc)
                retry_delay = _gemini_retry_delay(exc)
                outcome = _next_model_outcome(index, models)

                if error_class == "invalid_request":
                    _record_gemini_attempt(
                        {
                            "model": model,
                            "attempt": attempt,
                            "status": status,
                            "error_class": error_class,
                            "elapsed_ms": elapsed_ms,
                            "outcome": "stop",
                            "retry_delay_s": retry_delay,
                        }
                    )
                    raise

                if error_class == "not_found":
                    _record_gemini_attempt(
                        {
                            "model": model,
                            "attempt": attempt,
                            "status": status,
                            "error_class": error_class,
                            "elapsed_ms": elapsed_ms,
                            "outcome": outcome,
                            "retry_delay_s": retry_delay,
                        }
                    )
                    if index + 1 < len(models):
                        LAST_FALLBACK_REASON = (
                            f"{model} HTTP 404; tried {models[index + 1]}"
                        )
                    break

                if error_class == "quota":
                    quota_kind = _gemini_quota_kind(exc)
                    can_retry = (
                        quota_kind == "per_minute"
                        and retry_delay is not None
                        and retry_delay <= MAX_RETRY_DELAY_SECONDS
                        and attempt < MAX_ATTEMPTS_PER_MODEL
                    )
                    if can_retry:
                        _record_gemini_attempt(
                            {
                                "model": model,
                                "attempt": attempt,
                                "status": status,
                                "error_class": error_class,
                                "elapsed_ms": elapsed_ms,
                                "outcome": "retry",
                                "retry_delay_s": retry_delay,
                            }
                        )
                        _sleep(float(retry_delay or 0.0))
                        continue
                    _record_gemini_attempt(
                        {
                            "model": model,
                            "attempt": attempt,
                            "status": status,
                            "error_class": error_class,
                            "elapsed_ms": elapsed_ms,
                            "outcome": outcome,
                            "retry_delay_s": retry_delay,
                        }
                    )
                    if index + 1 < len(models):
                        LAST_FALLBACK_REASON = (
                            f"{model} rate-limited; tried {models[index + 1]}"
                        )
                    break

                if attempt < MAX_ATTEMPTS_PER_MODEL:
                    _record_gemini_attempt(
                        {
                            "model": model,
                            "attempt": attempt,
                            "status": status,
                            "error_class": error_class,
                            "elapsed_ms": elapsed_ms,
                            "outcome": "retry",
                            "retry_delay_s": RETRY_BACKOFF_SECONDS,
                        }
                    )
                    _sleep(RETRY_BACKOFF_SECONDS)
                    continue

                _record_gemini_attempt(
                    {
                        "model": model,
                        "attempt": attempt,
                        "status": status,
                        "error_class": error_class,
                        "elapsed_ms": elapsed_ms,
                        "outcome": outcome,
                        "retry_delay_s": None,
                    }
                )
                if index + 1 < len(models):
                    LAST_FALLBACK_REASON = (
                        f"{model} {error_class}; tried {models[index + 1]}"
                    )
                break

    detail = common.redact_secrets(str(last_error))[:200] if last_error else ""
    raise LLMError(
        "Gemini returned no usable model response"
        + (f": {detail}" if detail else "")
    )


def _call_openrouter(prompt: str, key: str) -> str:
    import requests

    model = os.getenv("LLM_MODEL", "").strip() or DEFAULT_OPENROUTER_MODEL
    response = requests.post(
        OPENROUTER_ENDPOINT,
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": REWRITE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()
    return _clean(data["choices"][0]["message"]["content"])


def template_script(
    transcript: str, max_words: int = MAX_SCRIPT_WORDS
) -> str:
    """Deterministic no-LLM fallback: hook + cleaned excerpt + closer.

    Keeps every word of the budget and stays under the target read at
    ``WORDS_PER_SECOND``. The hook rotates off a stable hash of the
    transcript so different videos get different openings.
    """
    budget = max(12, int(max_words))
    hooks = (
        "Stop scrolling - this is the part nobody tells you.",
        "Nobody warned her about what happened next.",
        "Wait until you hear how this story ends.",
        "Most people never see this part coming.",
    )
    seed = sum(ord(c) for c in transcript[:128])
    hook = hooks[seed % len(hooks)]
    closer = "Here is the story, and why it matters."

    words = transcript.split()
    body_budget = max(1, budget - len(hook.split()) - len(closer.split()))
    # Prefer whole sentences: cut at the last sentence end inside budget.
    body = " ".join(words[:body_budget])
    sentence_ends = [
        i for i, w in enumerate(words[:body_budget]) if w.rstrip('"').endswith((".", "!", "?"))
    ]
    if sentence_ends:
        body = " ".join(words[: sentence_ends[-1] + 1])
    body = body.strip().strip('"')

    script = f"{hook} {body} {closer}".strip()
    return _budget(script, budget)


def rewrite_script(
    transcript: str, max_words: int | None = None
) -> tuple[str, str]:
    """Rewrite the transcript. Returns (script, source).

    ``max_words`` caps the narration for a platform target (21/30/59 s).
    ``source`` is "gemini", "openrouter" or "template". Any provider error -
    missing key, network failure, bad response - falls back to the template
    generator instead of failing the job.
    """
    global LAST_MODEL, LAST_FALLBACK_REASON, LAST_ATTEMPTS
    LAST_MODEL = ""
    LAST_FALLBACK_REASON = ""
    LAST_ATTEMPTS = []
    transcript = (transcript or "").strip()
    if not transcript:
        return "", "template"

    budget = int(max_words) if max_words else MAX_SCRIPT_WORDS
    budget = max(12, min(MAX_SCRIPT_WORDS, budget))

    provider = _provider()
    key = _api_key()
    if provider not in ("gemini", "openrouter") or not key:
        common.info("LLM not configured (LLM_PROVIDER/LLM_API_KEY) - using template hook")
        LAST_FALLBACK_REASON = "LLM not configured"
        return template_script(transcript, budget), "template"

    prompt = _prompt(transcript, budget)
    try:
        if provider == "gemini":
            script = _call_gemini(prompt, key)
            name = "gemini"
        else:
            script = _call_openrouter(prompt, key)
            name = "openrouter"
        script = _budget(script, budget)
        if len(script.split()) < 8:
            raise LLMError(f"{provider} returned a script that is too short")
        common.info(f"Script rewritten via {provider} ({len(script.split())} words)")
        return script, name
    except Exception as exc:  # any failure: template keeps the job alive
        common.warn(
            f"LLM rewrite failed ({common.redact_secrets(str(exc))}) "
            "- falling back to template hook"
        )
        detail = common.redact_secrets(str(exc))[:200]
        LAST_FALLBACK_REASON = LAST_FALLBACK_REASON or detail
        return template_script(transcript, budget), "template"


async def _stream_voiceover(script: str, voice: str, out_path: Path) -> list[dict]:
    import edge_tts

    # edge-tts >=7 defaults to SentenceBoundary; captions need word events.
    communicate = edge_tts.Communicate(script, voice, boundary="WordBoundary")
    words: list[dict[str, Any]] = []
    with open(out_path, "wb") as fh:
        async for chunk in communicate.stream():
            kind = str(chunk.get("type") or "")
            if kind == "audio":
                fh.write(chunk["data"])
            elif kind.lower().replace("_", "") == "wordboundary":
                # edge-tts offsets are 100-nanosecond ticks.
                start = float(chunk.get("offset", 0)) / 1e7
                duration = float(chunk.get("duration", 0)) / 1e7
                text = str(chunk.get("text") or "").strip()
                if text:
                    words.append(
                        {
                            "start": round(start, 3),
                            "end": round(start + max(duration, 0.01), 3),
                            "text": text,
                        }
                    )
    return words


def synthesize_voiceover(
    script: str,
    out_path: Path,
    voice: str | None = None,
) -> tuple[Path, list[dict]]:
    """Render ``script`` to audio with edge-tts and return (path, words).

    Word timestamps are written to ``<out_path>.words.json`` so captions can
    be regenerated later without re-synthesising.
    """
    try:
        import edge_tts  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "edge-tts is not installed - run: pip install edge-tts"
        ) from exc

    voice = (voice or os.getenv("EDGE_VOICE", "").strip() or DEFAULT_VOICE)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    words = asyncio.run(_stream_voiceover(script, voice, out_path))

    if not out_path.exists() or out_path.stat().st_size < 500:
        raise RuntimeError("edge-tts produced no audio (network blocked?)")
    if not words:
        raise RuntimeError("edge-tts returned no word timestamps")

    ts_path = out_path.with_suffix(".words.json")
    ts_path.write_text(json.dumps(words, indent=2), encoding="utf-8")
    common.info(f"Voiceover ready: {out_path.name} ({len(words)} word timestamps)")
    return out_path, words


# ---------------------------------------------------------------------------
# Anti-flag metadata: 3 titles / 3 descriptions / 3 hashtag sets per clip
# ---------------------------------------------------------------------------


def _meta_prompt(content: str) -> str:
    return (
        "You write metadata for short-form video clips (TikTok/Reels/Shorts). "
        "From the content below, return STRICT JSON and nothing else with "
        "exactly this shape:\n"
        '{"titles": ["...", "...", "..."], '
        '"descriptions": ["...", "...", "..."], '
        '"hashtags": [["#a"], ["#b"], ["#c"]]}\n'
        "Rules: exactly 3 titles (<=70 chars, no hashtags inside); exactly 3 "
        "descriptions (1-3 natural sentences, no hashtags inside); exactly 3 "
        "hashtag arrays of 5-8 tags each, every tag starting with #; all "
        "variations distinct from one another. JSON only - no markdown fences, "
        "no commentary.\n\n"
        f"Content:\n{content[:4000]}"
    )


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response (fences tolerated)."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    t = t.strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in LLM metadata response")
    parsed = json.loads(t[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM metadata is not a JSON object")
    return parsed


def template_metadata(content: str, rng: Any = None) -> dict:
    """Deterministic-shape fallback: randomized title/description/hashtag pools.

    No key, no network: three distinct variants come out of shuffled template
    pools seeded by the clip content, so every clip still gets anti-flag
    variety.
    """
    r = rng or random
    words = (content or "").strip().split()
    hook = " ".join(words[:10]).rstrip(",. ;:!?".replace(" ", "")) or (
        "an incredible true story"
    )

    title_pool = [
        hook[:70],
        f"Wait For What Happens Next - {hook[:45]}".strip(" -"),
        f"You Won't Believe This: {hook[:50]}".strip(" -"),
        f"The Part Nobody Talks About ({hook[:40]})",
        f"Story Time: {hook[:55]}".strip(" -"),
        f"Nobody Saw This Coming - {hook[:42]}".strip(" -"),
    ]
    title_pool = [t for t in title_pool if t and t != "-"]
    titles = r.sample(title_pool, min(3, len(title_pool)))
    while len(titles) < 3:
        titles.append(hook[:70])

    desc_pool = [
        f"{hook}. Watch till the end and tell us what you think.",
        f"A moment worth watching twice. {hook}.",
        f"Sit back and enjoy: {hook}. Follow for more like this.",
        f"The whole story in under a minute - {hook}.",
        f"Hit follow if this kept you watching. {hook}.",
        f"Some stories stay with you. This is one of them: {hook}.",
    ]
    descriptions = r.sample(desc_pool, min(3, len(desc_pool)))
    while len(descriptions) < 3:
        descriptions.append(f"{hook}. Watch till the end.")

    evergreen = [
        "#fyp", "#shorts", "#viral", "#trending",
        "#reels", "#storytime", "#foryou", "#mustwatch",
    ]
    topical: list[str] = []
    for w in words:
        clean = re.sub(r"[^A-Za-z0-9]", "", w)
        if len(clean) >= 5:
            tag = "#" + clean[:14]
            if tag not in topical:
                topical.append(tag)
        if len(topical) >= 8:
            break
    pool = evergreen + topical
    hashtags = [
        r.sample(pool, min(6, len(pool))) for _ in range(3)
    ]
    return {"titles": titles, "descriptions": descriptions, "hashtags": hashtags}


def _str_list(value: Any, cap: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip() if isinstance(item, (str, int, float)) else ""
        if text:
            out.append(text)
        if len(out) >= cap:
            break
    return out


def _normalize_metadata(raw: Any, content: str, rng: Any = None) -> dict:
    """Coerce an LLM payload to exactly 3 titles/descriptions/hashtag sets,
    padding any gaps from the template generator."""
    base = template_metadata(content, rng)
    if not isinstance(raw, dict):
        return base

    titles = _str_list(raw.get("titles"), 3)
    descriptions = _str_list(raw.get("descriptions"), 3)
    hashtags: list[list[str]] = []
    raw_sets = raw.get("hashtags")
    if isinstance(raw_sets, list):
        for entry in raw_sets:
            tags = _str_list(entry, 8)
            tags = ["#" + re.sub(r"^#+", "", t) for t in tags]
            tags = [t for t in tags if t.strip("#")]
            if tags:
                hashtags.append(tags)
            if len(hashtags) >= 3:
                break

    while len(titles) < 3:
        titles.append(base["titles"][len(titles) % 3])
    while len(descriptions) < 3:
        descriptions.append(base["descriptions"][len(descriptions) % 3])
    while len(hashtags) < 3:
        hashtags.append(base["hashtags"][len(hashtags) % 3])
    return {
        "titles": titles[:3],
        "descriptions": descriptions[:3],
        "hashtags": hashtags[:3],
    }


def _clean_handle(channel: str) -> str:
    handle = str(channel or "").strip().lstrip("@").strip()
    return re.sub(r"\s+", " ", handle)


def attribution_line(channel: str) -> str:
    """Return 'Inspired by @Handle' or '' when no channel is known."""
    handle = _clean_handle(channel)
    return f"Inspired by @{handle}" if handle else ""


BROLL_STOPWORDS = {
    "about", "after", "again", "also", "because", "before", "being", "could",
    "every", "from", "have", "into", "just", "like", "made", "make", "many",
    "more", "most", "never", "only", "other", "over", "said", "some", "story",
    "than", "that", "their", "them", "then", "there", "these", "they", "this",
    "those", "through", "under", "very", "want", "were", "what", "when",
    "where", "which", "while", "will", "with", "would", "your",
}


def broll_query(
    text: str, keywords: Sequence[str] | None = None, max_terms: int = 4
) -> str:
    """A Pixabay query derived from the narration, not one fixed term.

    Story keywords from config win (they describe the genre), then the most
    frequent content words; the fixed PIXABAY_QUERY is only the last resort.
    """
    body = (text or "").lower()
    terms: list[str] = []
    for keyword in keywords or []:
        key = str(keyword).strip().lower()
        if key and key in body and key not in terms:
            terms.append(key)
        if len(terms) >= 2:
            break
    for word in re.findall(r"[a-z]{4,}", body):
        if word in BROLL_STOPWORDS or word in terms:
            continue
        terms.append(word)
        if len(terms) >= max_terms:
            break
    query = " ".join(terms).strip()
    return query or os.getenv("PIXABAY_QUERY", "african village night")


def with_attribution(description: str, channel: str) -> str:
    """Append the copyright attribution to a description (guaranteed for every
    variant, LLM- or template-generated)."""
    line = attribution_line(channel)
    if not line:
        return description or ""
    text = (description or "").strip()
    return f"{text} {line}".strip() if text else line


def generate_metadata(
    content: str,
    channel: str = "",
    rng: Any = None,
) -> tuple[dict, str]:
    """3 titles, 3 descriptions and 3 hashtag sets for one clip.

    Uses the same free LLM provider as ``rewrite_script``; with no key - or on
    any provider/parse error - falls back to randomized template variants.
    ``Inspired by @channel`` is appended to every description here so the
    attribution can never be lost, whatever the source.
    """
    content = (content or "").strip()
    provider, key = _provider(), _api_key()

    meta: dict | None = None
    source = "template"
    if content and provider in ("gemini", "openrouter") and key:
        try:
            prompt = _meta_prompt(content)
            if provider == "gemini":
                text = _call_gemini(prompt, key, mode="metadata")
            else:
                text = _call_openrouter(prompt, key)
            try:
                meta = _normalize_metadata(_extract_json(text), content, rng)
            except (TypeError, ValueError):
                if provider != "gemini":
                    raise
                common.warn("Gemini metadata was not valid JSON; retrying once")
                text = _call_gemini(prompt, key, mode="metadata")
                meta = _normalize_metadata(_extract_json(text), content, rng)
            source = provider
            common.info(f"Clip metadata generated via {provider}")
        except Exception as exc:
            common.warn(
                f"LLM metadata failed ({common.redact_secrets(str(exc))}) "
                "- template variations instead"
            )
            meta = None

    if meta is None:
        meta = template_metadata(content, rng)
        source = "template"

    meta["descriptions"] = [with_attribution(d, channel) for d in meta["descriptions"]]
    return meta, source
