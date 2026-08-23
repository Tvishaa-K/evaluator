import os

from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()

client = SarvamAI(api_subscription_key=os.getenv("SARVAM_API_KEY", ""))

# Languages sarvam-translate:v1 accepts as explicit source codes
SARVAM_SOURCE_LANGS = {
    "bn", "gu", "hi", "kn", "ml", "mr", "od", "pa", "ta", "te",
    "as", "brx", "doi", "kok", "ks", "mai", "mni", "ne", "sa", "sat", "sd", "ur",
}


def is_english(language_code: str | None) -> bool:
    if not language_code:
        return True
    return language_code.lower().split("-")[0] in ("en", "english")


def _sarvam_source_code(detected_language: str | None) -> str | None:
    """Maps a Deepgram-detected language ('hi', 'ta', ...) to Sarvam's
    'xx-IN' source code, or None if Sarvam has no explicit code for it."""
    if not detected_language:
        return None
    base = detected_language.lower().split("-")[0]
    if base == "or":  # Deepgram uses 'or' for Odia, Sarvam uses 'od'
        base = "od"
    return f"{base}-IN" if base in SARVAM_SOURCE_LANGS else None


def translate_segments(segments: list, source_language: str | None = None) -> list:
    """Translates each segment's text to English via Sarvam, preserving
    speaker labels and timestamps. Per-segment calls keep every request
    well under Sarvam's input character limit.

    The translate API rejects source_language_code='auto' for
    sarvam-translate:v1, so we pass the Deepgram-detected language when
    Sarvam supports it and fall back to mayura:v1 auto-detect otherwise."""
    source_code = _sarvam_source_code(source_language)

    translated = []
    for seg in segments:
        if source_code:
            response = client.text.translate(
                input=seg["text"],
                source_language_code=source_code,
                target_language_code="en-IN",
                model="sarvam-translate:v1",
            )
        else:
            response = client.text.translate(
                input=seg["text"],
                source_language_code="auto",
                target_language_code="en-IN",
                model="mayura:v1",
            )
        translated.append({**seg, "text": response.translated_text.strip()})
    return translated
