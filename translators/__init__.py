from .openai_translator import OpenAITranslator
from .deepl_translator import DeepLTranslator
from .libretranslate_translator import LibreTranslateTranslator


def create_translator(provider: str, config: dict):
    provider = provider.lower().strip()

    if provider == "openai":
        return OpenAITranslator(config)

    if provider == "deepl":
        return DeepLTranslator(config)

    if provider == "libretranslate":
        return LibreTranslateTranslator(config)

    raise ValueError(f"Unbekannter Übersetzungs-Provider: {provider}")


def get_translator(config: dict):
    provider = config["translation"].get("provider", "openai")
    return create_translator(provider, config)


def get_fallback_translator(config: dict):
    fallback_provider = config["translation"].get("fallback_provider")

    if not fallback_provider:
        return None

    main_provider = config["translation"].get("provider", "openai")

    if fallback_provider.lower().strip() == main_provider.lower().strip():
        return None

    return create_translator(fallback_provider, config)