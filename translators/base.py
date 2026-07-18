from abc import ABC, abstractmethod


class BaseTranslator(ABC):
    @abstractmethod
    async def translate(self, text: str) -> str:
        pass