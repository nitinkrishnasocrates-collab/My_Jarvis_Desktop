"""Language → TTS engine/voice routing with explicit online vs local flags."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .language import default_language, enabled_languages, fallback_language, normalize_language


@dataclass(frozen=True)
class TtsHop:
    provider: str  # piper | edge | riva | sapi
    voice_id: str
    lang_tag: str
    online: bool
    language: str


@dataclass
class TtsPlan:
    language: str
    hops: list[TtsHop] = field(default_factory=list)
    online_allowed: bool = True


_DEFAULT_VOICES = {
    "en": {
        "local": "piper",
        "local_voice": "jarvis",
        "online": "edge",
        "online_voice": "en-GB-ThomasNeural",
        "lang_tag": "en-GB",
        "riva_voice": "Magpie-Multilingual.EN-US.Leo",
        "riva_language_code": "en-US",
    },
    "ta": {
        "local": "sapi",
        "local_voice": "",
        "online": "edge",
        "online_voice": "ta-IN-ValluvarNeural",
        "lang_tag": "ta-IN",
        "riva_voice": "",
        "riva_language_code": "ta-IN",
    },
    "hi": {
        "local": "sapi",
        "local_voice": "",
        "online": "edge",
        "online_voice": "hi-IN-MadhurNeural",
        "lang_tag": "hi-IN",
        "riva_voice": "",
        "riva_language_code": "hi-IN",
    },
}


def _voice_map(cfg, language: str) -> dict[str, Any]:
    base = dict(_DEFAULT_VOICES.get(language, _DEFAULT_VOICES["en"]))
    langs = getattr(getattr(cfg, "voice", None), "languages", None)
    voices = getattr(langs, "voices", None) if langs is not None else None
    entry = None
    if isinstance(voices, dict):
        entry = voices.get(language)
    elif voices is not None:
        entry = getattr(voices, language, None)
    if entry is None:
        return base
    if hasattr(entry, "model_dump"):
        data = entry.model_dump()
    elif isinstance(entry, dict):
        data = entry
    else:
        data = {
            k: getattr(entry, k)
            for k in (
                "local",
                "local_voice",
                "online",
                "online_voice",
                "lang_tag",
                "riva_voice",
                "riva_language_code",
            )
            if hasattr(entry, k)
        }
    for k, v in data.items():
        if v not in (None, ""):
            base[k] = v
    return base


def _online_allowed(cfg) -> bool:
    langs = getattr(getattr(cfg, "voice", None), "languages", None)
    if langs is None:
        return True
    return bool(getattr(langs, "online_tts_allowed", True))


def _piper_preferred(cfg) -> bool:
    voice = getattr(cfg, "voice", None)
    if voice is None:
        return False
    provider = (getattr(voice, "provider", "auto") or "auto").lower().strip()
    if provider == "piper":
        return True
    return provider == "auto" and bool(getattr(voice, "piper_enabled", False))


def _riva_preferred(cfg) -> bool:
    voice = getattr(cfg, "voice", None)
    if voice is None:
        return False
    provider = (getattr(voice, "provider", "auto") or "auto").lower().strip()
    return provider == "nvidia_riva" or (
        provider == "auto" and bool(getattr(voice, "riva_enabled", False))
    )


def _riva_is_cloud(cfg) -> bool:
    """True when synthesis would hit NVIDIA cloud, not a private local Riva."""
    server = str(getattr(getattr(cfg, "voice", None), "riva_server", "") or "")
    if "nvcf.nvidia.com" in server:
        return True
    # Default config uses the cloud URI when server is blank or the placeholder.
    return server.strip() in ("", "localhost:50051")


def _append_unique(hops: list[TtsHop], hop: TtsHop) -> None:
    key = (hop.provider, hop.voice_id, hop.language)
    if any((h.provider, h.voice_id, h.language) == key for h in hops):
        return
    hops.append(hop)


def build_tts_plan(cfg, language: str | None) -> TtsPlan:
    enabled = enabled_languages(cfg)
    lang = normalize_language(language) or default_language(cfg)
    if lang not in enabled:
        lang = default_language(cfg)
    mapping = _voice_map(cfg, lang)
    online_ok = _online_allowed(cfg)
    hops: list[TtsHop] = []
    lang_tag = mapping.get("lang_tag") or lang
    local_kind = (mapping.get("local") or "").lower()

    # English keeps the existing British JARVIS Piper voice as first hop.
    if lang == "en" and _piper_preferred(cfg) and local_kind in ("piper", "auto", ""):
        _append_unique(
            hops,
            TtsHop(
                provider="piper",
                voice_id=mapping.get("local_voice") or "jarvis",
                lang_tag="en-GB",
                online=False,
                language="en",
            ),
        )

    if _riva_preferred(cfg) and mapping.get("riva_voice"):
        cloud = _riva_is_cloud(cfg)
        if (not cloud) or online_ok:
            _append_unique(
                hops,
                TtsHop(
                    provider="riva",
                    voice_id=str(mapping.get("riva_voice")),
                    lang_tag=str(mapping.get("riva_language_code") or lang_tag),
                    online=cloud,
                    language=lang,
                ),
            )

    if local_kind == "sapi":
        _append_unique(
            hops,
            TtsHop(
                provider="sapi",
                voice_id=str(mapping.get("local_voice") or ""),
                lang_tag=str(lang_tag),
                online=False,
                language=lang,
            ),
        )

    online_kind = (mapping.get("online") or "edge").lower()
    if online_ok and online_kind in ("edge", "edge_tts", "auto"):
        voice_cfg = getattr(cfg, "voice", None)
        default_edge = getattr(voice_cfg, "edge_voice", None) if voice_cfg else None
        voice_id = mapping.get("online_voice") or default_edge or "en-GB-ThomasNeural"
        if lang == "en":
            voice_id = default_edge or voice_id
        _append_unique(
            hops,
            TtsHop(
                provider="edge",
                voice_id=str(voice_id),
                lang_tag=str(lang_tag),
                online=True,
                language=lang,
            ),
        )

    # English last-resort: keep today's Edge British voice even if mapping is empty.
    if not hops and lang == "en" and online_ok:
        voice_cfg = getattr(cfg, "voice", None)
        voice_id = getattr(voice_cfg, "edge_voice", None) if voice_cfg else None
        _append_unique(
            hops,
            TtsHop(
                provider="edge",
                voice_id=str(voice_id or "en-GB-ThomasNeural"),
                lang_tag="en-GB",
                online=True,
                language="en",
            ),
        )

    return TtsPlan(language=lang, hops=hops, online_allowed=online_ok)


def tts_response_headers(hop: TtsHop) -> dict[str, str]:
    return {
        "X-JARVIS-TTS": hop.provider,
        "X-JARVIS-TTS-ONLINE": "1" if hop.online else "0",
        "X-JARVIS-TTS-LANG": hop.language,
        "X-JARVIS-TTS-VOICE": hop.voice_id,
        "X-JARVIS-TTS-TAG": hop.lang_tag,
    }


def fallback_plan_if_needed(cfg, plan: TtsPlan) -> TtsPlan:
    """Optional extra hops in the configured fallback language (never silent)."""
    langs = getattr(getattr(cfg, "voice", None), "languages", None)
    if langs is not None and not bool(getattr(langs, "fallback_on_tts_failure", True)):
        return plan
    if plan.hops:
        return plan
    fb = fallback_language(cfg)
    if fb == plan.language:
        return plan
    extra = build_tts_plan(cfg, fb)
    return TtsPlan(
        language=plan.language,
        hops=list(extra.hops),
        online_allowed=plan.online_allowed and extra.online_allowed,
    )
