"""Multilingual conversation helpers for STT, replies, and language switching.

Does not translate tool arguments. Language-switch phrases are stripped from
the user text; the remainder is returned unchanged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PREF_KEY = "conversation_language"

LANGUAGE_NAMES = {
    "en": "English",
    "ta": "Tamil",
    "hi": "Hindi",
}

LANGUAGE_ALIASES = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "en-gb": "en",
    "en-us": "en",
    "en_gb": "en",
    "en_us": "en",
    "ta": "ta",
    "tam": "ta",
    "tamil": "ta",
    "ta-in": "ta",
    "ta_in": "ta",
    "hi": "hi",
    "hin": "hi",
    "hindi": "hi",
    "hi-in": "hi",
    "hi_in": "hi",
}

ACK = {
    "en": "Speaking English, sir.",
    "ta": "தமிழில் பேசுகிறேன், ஐயா.",
    "hi": "हिंदी में बात करूँगा, सर।",
}

AUTO_ACK = {
    "en": "I'll match your language automatically, sir.",
    "ta": "நீங்கள் பேசும் மொழியிலேயே பதிலளிக்கிறேன், ஐயா.",
    "hi": "आप जिस भाषा में बोलेंगे, उसी में जवाब दूँगा, सर।",
}

_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Explicit switch commands. Group 1 is the language token or AUTO.
_SWITCH_PATTERNS = [
    re.compile(
        r"\b(?:speak|talk|reply|respond|answer|switch)\s+(?:to\s+|in\s+)?(english|tamil|hindi)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(english|tamil|hindi)\s+(?:mein|me)\s+baat\s+karo\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bhindi\s+mein\s+baat\s+karo\b", re.IGNORECASE),
    re.compile(r"தமிழில்\s+பேசு|தமிழ்ல\s+பேசு|தமிழில்\s+பதில்"),
    re.compile(r"ஆங்கிலத்தில்\s+பேசு|இங்கிலீஷ்(?:ல்|இல்)?\s+பேசு"),
    re.compile(r"हिंदी\s+में\s+बात\s+करो|हिन्दी\s+में\s+बात\s+करो|हिंदी\s+में\s+बोलो"),
    re.compile(
        r"\b(?:auto(?:matic)?(?:ally)?\s+(?:detect\s+)?language|detect\s+language|match\s+my\s+language)\b",
        re.IGNORECASE,
    ),
]


@dataclass(frozen=True)
class LanguageTurn:
    reply_language: str
    locked: bool
    remainder: str
    switched: bool
    detected: str | None
    confidence: float | None
    auto: bool
    ack: str | None = None


def normalize_language(code: str | None) -> str | None:
    if not code:
        return None
    key = str(code).strip().lower().replace("_", "-")
    if key in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[key]
    base = key.split("-", 1)[0]
    return LANGUAGE_ALIASES.get(base)


def enabled_languages(cfg) -> list[str]:
    langs = _languages_cfg(cfg)
    enabled = [normalize_language(x) for x in getattr(langs, "enabled", ["en", "ta", "hi"])]
    out = [x for x in enabled if x]
    return out or ["en"]


def default_language(cfg) -> str:
    langs = _languages_cfg(cfg)
    code = normalize_language(getattr(langs, "default", "en")) or "en"
    enabled = enabled_languages(cfg)
    return code if code in enabled else enabled[0]


def fallback_language(cfg) -> str:
    langs = _languages_cfg(cfg)
    code = normalize_language(getattr(langs, "fallback_language", "en")) or "en"
    enabled = enabled_languages(cfg)
    return code if code in enabled else enabled[0]


def auto_detect_enabled(cfg) -> bool:
    langs = _languages_cfg(cfg)
    return bool(getattr(langs, "auto_detect", True))


def persist_preference_enabled(cfg) -> bool:
    langs = _languages_cfg(cfg)
    return bool(getattr(langs, "persist_preference", True))


def detect_min_confidence(cfg) -> float:
    langs = _languages_cfg(cfg)
    try:
        return float(getattr(langs, "detect_min_confidence", 0.45))
    except (TypeError, ValueError):
        return 0.45


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def detect_script_language(text: str) -> tuple[str | None, float]:
    """Heuristic language from script. Mixed Tamil–English still returns ta."""
    if not text or not text.strip():
        return None, 0.0
    tamil = len(_TAMIL_RE.findall(text))
    hindi = len(_DEVANAGARI_RE.findall(text))
    latin = sum(1 for c in text if ("A" <= c <= "Z") or ("a" <= c <= "z"))
    total = tamil + hindi + latin
    if total == 0:
        return None, 0.0
    if tamil >= 2 and tamil >= hindi:
        # Mixed speech: a little Tamil script is enough to prefer Tamil.
        conf = min(0.99, 0.55 + tamil / max(total, 1) * 0.45)
        return "ta", conf
    if hindi >= 2 and hindi > tamil:
        conf = min(0.99, 0.55 + hindi / max(total, 1) * 0.45)
        return "hi", conf
    if latin >= 3:
        return "en", min(0.9, 0.4 + latin / max(total, 1) * 0.5)
    return None, 0.0


def merge_language_signals(
    cfg,
    stt_language: str | None,
    stt_confidence: float | None,
    text: str,
) -> tuple[str | None, float | None]:
    """Combine Whisper detection with script cues. Never force English."""
    script_lang, script_conf = detect_script_language(text)
    stt = normalize_language(stt_language)
    conf = stt_confidence
    enabled = enabled_languages(cfg)
    min_conf = detect_min_confidence(cfg)

    if script_lang in enabled and script_lang in {"ta", "hi"}:
        # Script evidence beats a low-confidence English STT guess (common
        # when the model was historically prompted in English).
        if stt in (None, "en") or (conf is not None and conf < 0.85):
            return script_lang, script_conf

    if stt in enabled and (conf is None or conf >= min_conf):
        return stt, conf
    if script_lang in enabled:
        return script_lang, script_conf
    if stt in enabled:
        return stt, conf
    return None, conf


def parse_language_command(text: str) -> tuple[str | None, bool, str]:
    """Return (language_or_AUTO, locked, remainder_untranslated).

    language is a normalized code, the string 'auto', or None if no command.
    Remainder keeps original wording/paths so tool args stay intact.
    """
    raw = text or ""
    if not raw.strip():
        return None, False, raw

    lowered = raw.lower()

    if re.search(r"தமிழில்\s+பேசு|தமிழ்ல\s+பேசு|தமிழில்\s+பதில்", raw):
        return "ta", True, _strip_span(raw, r"தமிழில்\s+பேசு|தமிழ்ல\s+பேசு|தமிழில்\s+பதில்")
    if re.search(r"ஆங்கிலத்தில்\s+பேசு|இங்கிலீஷ்(?:ல்|இல்)?\s+பேசு", raw):
        return "en", True, _strip_span(raw, r"ஆங்கிலத்தில்\s+பேசு|இங்கிலீஷ்(?:ல்|இல்)?\s+பேசு")
    if re.search(r"हिंदी\s+में\s+बात\s+करो|हिन्दी\s+में\s+बात\s+करो|हिंदी\s+में\s+बोलो", raw):
        return "hi", True, _strip_span(raw, r"हिंदी\s+में\s+बात\s+करो|हिन्दी\s+में\s+बात\s+करो|हिंदी\s+में\s+बोलो")

    if re.search(
        r"\b(?:auto(?:matic)?(?:ally)?\s+(?:detect\s+)?language|detect\s+language|match\s+my\s+language)\b",
        lowered,
    ):
        return "auto", False, _strip_span(
            raw,
            r"\b(?:auto(?:matic)?(?:ally)?\s+(?:detect\s+)?language|detect\s+language|match\s+my\s+language)\b",
        )

    m = re.search(
        r"\b(?:speak|talk|reply|respond|answer|switch)\s+(?:to\s+|in\s+)?(english|tamil|hindi)\b",
        lowered,
    )
    if m:
        return normalize_language(m.group(1)), True, _strip_span(
            raw,
            r"\b(?:speak|talk|reply|respond|answer|switch)\s+(?:to\s+|in\s+)?(?:english|tamil|hindi)\b",
        )

    m = re.search(r"\bhindi\s+mein\s+baat\s+karo\b", lowered)
    if m:
        return "hi", True, _strip_span(raw, r"\bhindi\s+mein\s+baat\s+karo\b")

    m = re.search(r"\b(english|tamil|hindi)\s+(?:mein|me)\s+baat\s+karo\b", lowered)
    if m:
        return normalize_language(m.group(1)), True, _strip_span(
            raw,
            r"\b(?:english|tamil|hindi)\s+(?:mein|me)\s+baat\s+karo\b",
        )

    return None, False, raw


def _strip_span(text: str, pattern: str) -> str:
    cleaned = re.sub(pattern, " ", text, count=1, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\s,;:]+and\s+", " ", cleaned, count=1, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:and|then|,)\s+", "", cleaned.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip(" ,;:-")


def load_preference(memory) -> dict[str, Any] | None:
    if memory is None:
        return None
    try:
        val = memory.get_pref(PREF_KEY, None)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(val, dict):
        return None
    code = normalize_language(val.get("code"))
    if not code:
        return None
    return {"code": code, "locked": bool(val.get("locked", False))}


def save_preference(memory, code: str | None, locked: bool) -> None:
    if memory is None:
        return
    if code is None:
        try:
            memory.set_pref(PREF_KEY, {"code": None, "locked": False})
        except Exception:  # noqa: BLE001
            pass
        return
    try:
        memory.set_pref(PREF_KEY, {"code": code, "locked": locked})
    except Exception:  # noqa: BLE001
        pass


def apply_language_turn(
    cfg,
    memory,
    user_text: str,
    stt_language: str | None = None,
    stt_confidence: float | None = None,
) -> LanguageTurn:
    enabled = enabled_languages(cfg)
    detected, det_conf = merge_language_signals(cfg, stt_language, stt_confidence, user_text)
    cmd, lock_cmd, remainder = parse_language_command(user_text)
    pref = load_preference(memory) if persist_preference_enabled(cfg) else None

    locked = bool(pref and pref.get("locked"))
    current = pref["code"] if pref and pref.get("code") in enabled else None
    switched = False
    auto = False
    ack = None

    if cmd == "auto":
        locked = False
        auto = True
        switched = True
        current = detected if detected in enabled else default_language(cfg)
        if persist_preference_enabled(cfg):
            save_preference(memory, None, False)
        ack = AUTO_ACK.get(current, AUTO_ACK["en"])
    elif cmd and cmd != "auto":
        if cmd in enabled:
            current = cmd
            locked = lock_cmd
            switched = True
            if persist_preference_enabled(cfg):
                save_preference(memory, current, locked)
            ack = ACK.get(current, ACK["en"])
        remainder = remainder  # already untranslated
    else:
        remainder = user_text

    if not locked:
        if auto_detect_enabled(cfg) and detected in enabled:
            current = detected
        elif current is None:
            current = default_language(cfg)

    if current not in enabled:
        current = default_language(cfg)

    work = remainder if switched else user_text
    return LanguageTurn(
        reply_language=current,
        locked=locked,
        remainder=work if work is not None else user_text,
        switched=switched,
        detected=detected,
        confidence=det_conf,
        auto=auto or (not locked),
        ack=ack,
    )


def language_system_block(code: str) -> str:
    name = language_name(code)
    script_note = {
        "en": "Reply in English.",
        "ta": "Reply in Tamil (தமிழ்) using Tamil script.",
        "hi": "Reply in Hindi (हिंदी) using Devanagari script.",
    }.get(code, f"Reply in {name}.")
    return (
        f"Reply language: {name} ({code}). {script_note} "
        "Keep the British JARVIS character. "
        "Do NOT translate or rewrite tool names, file paths, URLs, shell commands, "
        "or tool argument values — copy them exactly as the user stated. "
        "Spoken replies should be in the reply language; tool JSON stays verbatim."
    )


def stt_decode_options(cfg, explicit_language: str | None = None) -> dict[str, Any]:
    """faster-whisper kwargs. Never force English unless the user/config asked."""
    langs = _languages_cfg(cfg)
    requested = explicit_language
    if requested in (None, "", "auto"):
        requested = getattr(langs, "stt_language", "auto")
    requested = (requested or "auto").strip().lower()

    opts: dict[str, Any] = dict(
        task="transcribe",
        beam_size=1,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400, "threshold": 0.45},
        condition_on_previous_text=False,
        no_speech_threshold=0.7,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
        temperature=0.0,
    )
    code = normalize_language(requested) if requested not in ("auto", "", "none") else None
    if code and (not auto_detect_enabled(cfg) or requested != "auto"):
        opts["language"] = code
        if code == "en":
            opts["initial_prompt"] = (
                "JARVIS command. Search, generate image, open page, run code, "
                "show news, list videos, open the file."
            )
    # Auto-detect: omit `language` and omit the English initial_prompt so
    # Tamil / Hindi / mixed speech is not pulled toward English.
    return opts


def whisper_model_is_multilingual(name: str) -> bool:
    n = (name or "").lower()
    return not n.endswith(".en") and "distil-small.en" not in n and "distil-medium.en" not in n


def preserve_tool_args(args: dict[str, Any], _language: str | None = None) -> dict[str, Any]:
    """Identity helper — language routing must never rewrite tool arguments."""
    return args


def _languages_cfg(cfg):
    voice = getattr(cfg, "voice", None)
    langs = getattr(voice, "languages", None) if voice is not None else None
    if langs is not None:
        return langs

    class _Defaults:
        enabled = ["en", "ta", "hi"]
        auto_detect = True
        default = "en"
        stt_language = "auto"
        persist_preference = True
        detect_min_confidence = 0.45
        fallback_language = "en"
        online_tts_allowed = True
        tts_timeout_seconds = 45
        stt_timeout_seconds = 60
        fallback_on_tts_failure = True
        voices = {}

    return _Defaults()
