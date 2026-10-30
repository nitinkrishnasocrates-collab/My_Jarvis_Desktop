"""
New Edge TTS Speech Synthesizer Module for JARVIS.
"""

import asyncio
import logging
from jarvis.core.multilingual_engine import MultilingualEngine
import edge_tts

logger = logging.getLogger("JarvisEdgeSpeech")

class EdgeSpeechSynth:
    @staticmethod
    async def synthesize(text: str, output_path: str, lang_code: str = "en", gender: str = "female") -> bool:
        """Synthesizes text into speech audio using Microsoft Edge Neural voices."""
        if not text or not text.strip():
            return False

        voice = MultilingualEngine.get_voice(lang_code, gender)
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
            return True
        except Exception as e:
            logger.error(f"Primary TTS generation failed with {voice}: {e}. Falling back.")
            try:
                fallback_voice = "en-GB-ThomasNeural"
                communicate = edge_tts.Communicate(text, fallback_voice)
                await communicate.save(output_path)
                return True
            except Exception as err:
                logger.error(f"Fallback TTS failed: {err}")
                return False

    @staticmethod
    def synthesize_sync(text: str, output_path: str, lang_code: str = "en", gender: str = "female") -> bool:
        """Synchronous wrapper for synthesize."""
        try:
            return asyncio.run(EdgeSpeechSynth.synthesize(text, output_path, lang_code, gender))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(EdgeSpeechSynth.synthesize(text, output_path, lang_code, gender))