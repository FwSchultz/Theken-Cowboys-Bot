import os
from openai import AsyncOpenAI
from .base import BaseTranslator


class OpenAITranslator(BaseTranslator):
    def __init__(self, config: dict):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = config["translation"]["openai"].get("model", "gpt-4.1-mini")
        self.source_lang = config["translation"].get("source_lang", "English")
        self.target_lang = config["translation"].get("target_lang", "German")

    async def translate(self, text: str) -> str:
        if not text or not text.strip():
            return ""

        prompt = f"""
Translate the following Discord message from {self.source_lang} to {self.target_lang}.

Rules:
- Keep the meaning.
- Keep Discord markdown where possible.
- Keep URLs unchanged.
- Keep mentions like @everyone, @here, <@123>, <#123>, <@&123> unchanged.
- Do not add explanations.
- Only return the translated message.

Message:
{text}
"""

        response = await self.client.responses.create(
            model=self.model,
            input=prompt,
        )

        return response.output_text.strip()