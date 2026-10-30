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
from pathlib import Path
from typing import Any

try:
    from backend import common
except ImportError:  # pragma: no cover - direct execution
    import common  # type: ignore

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3-8b-instruct:free"

DEFAULT_VOICE = "en-US-AriaNeural"
ALT_VOICE = "en-US-GuyNeural"
# edge-tts reads English at roughly 2.6 words/second; a 59 s slot is ~150 words.
WORDS_PER_SECOND = 2.6
MAX_SCRIPT_WORDS = 140
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


class LLMError(RuntimeError):
    """Raised only when the caller asks for a strict LLM result."""


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


def _budget(script: str) -> str:
    words = script.split()
    if len(words) > MAX_SCRIPT_WORDS:
        words = words[:MAX_SCRIPT_WORDS]
    return " ".join(words)


def _prompt(transcript: str) -> str:
    body = transcript[:MAX_TRANSCRIPT_CHARS]
    return (
        f"{REWRITE_SYSTEM}\n\n{REWRITE_RULES.format(max_words=MAX_SCRIPT_WORDS)}"
        f"\nRaw transcript:\n\"\"\"\n{body}\n\"\"\"\n"
    )


def _call_gemini(prompt: str, key: str) -> str:
    import requests

    model = os.getenv("LLM_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
    url = GEMINI_ENDPOINT.format(model=model)
    response = requests.post(
        url,
        params={"key": key},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()
    parts = data["candidates"][0]["content"]["parts"]
    return _clean("".join(str(p.get("text", "")) for p in parts))


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


def template_script(transcript: str) -> str:
    """Deterministic no-LLM fallback: hook + cleaned excerpt + closer.

    Keeps every word of the budget and stays under a 59-second read at
    ``WORDS_PER_SECOND``. The hook rotates off a stable hash of the
    transcript so different videos get different openings.
    """
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
    body_budget = MAX_SCRIPT_WORDS - len(hook.split()) - len(closer.split())
    # Prefer whole sentences: cut at the last sentence end inside budget.
    body = " ".join(words[:body_budget])
    sentence_ends = [
        i for i, w in enumerate(words[:body_budget]) if w.rstrip('"').endswith((".", "!", "?"))
    ]
    if sentence_ends:
        body = " ".join(words[: sentence_ends[-1] + 1])
    body = body.strip().strip('"')

    script = f"{hook} {body} {closer}".strip()
    return _budget(script)


def rewrite_script(transcript: str) -> tuple[str, str]:
    """Rewrite the transcript. Returns (script, source).

    ``source`` is "gemini", "openrouter" or "template". Any provider error -
    missing key, network failure, bad response - falls back to the template
    generator instead of failing the job.
    """
    transcript = (transcript or "").strip()
    if not transcript:
        return "", "template"

    provider = _provider()
    key = _api_key()
    if provider not in ("gemini", "openrouter") or not key:
        common.info("LLM not configured (LLM_PROVIDER/LLM_API_KEY) - using template hook")
        return template_script(transcript), "template"

    prompt = _prompt(transcript)
    try:
        if provider == "gemini":
            script = _call_gemini(prompt, key)
            name = "gemini"
        else:
            script = _call_openrouter(prompt, key)
            name = "openrouter"
        script = _budget(script)
        if len(script.split()) < 8:
            raise LLMError(f"{provider} returned a script that is too short")
        common.info(f"Script rewritten via {provider} ({len(script.split())} words)")
        return script, name
    except Exception as exc:  # any failure: template keeps the job alive
        common.warn(f"LLM rewrite failed ({exc}) - falling back to template hook")
        return template_script(transcript), "template"


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
                text = _call_gemini(prompt, key)
            else:
                text = _call_openrouter(prompt, key)
            meta = _normalize_metadata(_extract_json(text), content, rng)
            source = provider
            common.info(f"Clip metadata generated via {provider}")
        except Exception as exc:
            common.warn(f"LLM metadata failed ({exc}) - template variations instead")
            meta = None

    if meta is None:
        meta = template_metadata(content, rng)
        source = "template"

    meta["descriptions"] = [with_attribution(d, channel) for d in meta["descriptions"]]
    return meta, source
