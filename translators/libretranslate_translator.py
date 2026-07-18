import os
import aiohttp
from .base import BaseTranslator


class LibreTranslateTranslator(BaseTranslator):
    def __init__(self, config: dict):
        self.url = os.getenv("LIBRETRANSLATE_URL", "http://localhost:5000").rstrip("/")
        self.api_key = os.getenv("LIBRETRANSLATE_API_KEY", "")
        self.source_lang = config["translation"]["libretranslate"].get("source_lang", "en")
        self.target_lang = config["translation"]["libretranslate"].get("target_lang", "de")

    async def translate(self, text: str) -> str:
        if not text or not text.strip():
            return ""

        payload = {
            "q": text,
            "source": self.source_lang,
            "target": self.target_lang,
            "format": "text",
        }

        if self.api_key:
            payload["api_key"] = self.api_key

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.url}/translate", json=payload) as response:
                response.raise_for_status()
                result = await response.json()

        return result["translatedText"].strip()