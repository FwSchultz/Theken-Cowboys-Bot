import os
import aiohttp
from .base import BaseTranslator


class DeepLTranslator(BaseTranslator):
    def __init__(self, config: dict):
        self.api_key = os.getenv("DEEPL_API_KEY")
        self.target_lang = config["translation"]["deepl"].get("target_lang", "DE")
        self.url = "https://api-free.deepl.com/v2/translate"

    async def translate(self, text: str) -> str:
        if not text or not text.strip():
            return ""

        if not self.api_key:
            raise RuntimeError("DEEPL_API_KEY fehlt in der .env")

        data = {
            "auth_key": self.api_key,
            "text": text,
            "target_lang": self.target_lang,
            "preserve_formatting": "1",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.url, data=data) as response:
                response.raise_for_status()
                result = await response.json()

        return result["translations"][0]["text"].strip()