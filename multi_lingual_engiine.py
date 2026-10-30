"""
New Multilingual Detection and Voice Routing Engine for JARVIS.
"""

import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("JarvisMultilingualEngine")

MULTILINGUAL_VOICE_MAP = {
    "ta": {"male": "ta-IN-ValluvarNeural", "female": "ta-IN-PallaviNeural"},
    "en": {"male": "en-GB-ThomasNeural", "female": "en-GB-SoniaNeural", "in_male": "en-IN-PrabhatNeural", "in_female": "en-IN-NeerjaNeural"},
    "hi": {"male": "hi-IN-MadhurNeural", "female": "hi-IN-SwaraNeural"},
    "te": {"male": "te-IN-MohanNeural", "female": "te-IN-ShrutiNeural"},
    "ml": {"male": "ml-IN-MidhunNeural", "female": "ml-IN-SobhanaNeural"},
    "kn": {"male": "kn-IN-GaganNeural", "female": "kn-IN-SapnaNeural"},
    "bn": {"male": "bn-IN-BashkarNeural", "female": "bn-IN-TanishaaNeural"},
    "gu": {"male": "gu-IN-NiranjanNeural", "female": "gu-IN-DhwaniNeural"},
    "mr": {"male": "mr-IN-ManoharNeural", "female": "mr-IN-AarohiNeural"},
    "ur": {"male": "ur-IN-SalmanNeural", "female": "ur-IN-GulNeural"}
}

class MultilingualEngine:
    @staticmethod
    def normalize_code(lang_code: Optional[str]) -> str:
        """Normalizes language tags to ISO 639-1 standards."""
        if not lang_code:
            return "en"
        clean = lang_code.lower().strip().split("-")[0]
        supported = set(MULTILINGUAL_VOICE_MAP.keys())
        return clean if clean in supported else "en"

    @staticmethod
    def detect_text_language(text: str) -> str:
        """Detects language script from user text input."""
        if not text or not text.strip():
            return "en"
        
        if re.search(r'[\u0B80-\u0BFF]', text):  # Tamil
            return "ta"
        if re.search(r'[\u0900-\u097F]', text):  # Hindi / Marathi
            return "hi"
        if re.search(r'[\u0C00-\u0C7F]', text):  # Telugu
            return "te"
        if re.search(r'[\u0D00-\u0D7F]', text):  # Malayalam
            return "ml"
        if re.search(r'[\u0C80-\u0CFF]', text):  # Kannada
            return "kn"
        if re.search(r'[\u0980-\u09FF]', text):  # Bengali
            return "bn"
        if re.search(r'[\u0A80-\u0AFF]', text):  # Gujarati
            return "gu"

        return "en"

    @staticmethod
    def get_voice(lang_code: str, gender: str = "female") -> str:
        """Returns the appropriate Edge TTS voice string."""
        norm = MultilingualEngine.normalize_code(lang_code)
        voices = MULTILINGUAL_VOICE_MAP.get(norm, MULTILINGUAL_VOICE_MAP["en"])
        return voices.get(gender, list(voices.values())[0])

    @staticmethod
    def get_prompt_instruction(lang_code: str) -> str:
        """Generates LLM prompt enforcement for language consistency."""
        norm = MultilingualEngine.normalize_code(lang_code)
        names = {
            "ta": "Tamil", "hi": "Hindi", "te": "Telugu", 
            "ml": "Malayalam", "kn": "Kannada", "bn": "Bengali", 
            "gu": "Gujarati", "mr": "Marathi", "ur": "Urdu", "en": "English"
        }
        lang_name = names.get(norm, "English")
        return f"Respond strictly in natural {lang_name}. If the user mixes languages (Code-switching like Tanglish/Hinglish), adapt naturally without translating technical code structures."