"""Shared environment-backed configuration for pipeline scripts.

Configuration sources:
1. `.env` file at repository root
2. Process environment variables (override `.env` values)

Consumers should apply CLI flags as the highest-precedence layer on top of these
settings. This module intentionally does not provide hardcoded defaults for the
pipeline keys that are expected to live in `.env` / `.env.example`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Errors and root resolution
# ---------------------------------------------------------------------------


class ConfigError(ValueError):
    """Raised when required configuration is missing or malformed."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# .env loading and environment merge
# ---------------------------------------------------------------------------


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()

    if not key:
        return None

    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]

    return key, value


def _load_dotenv(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        data[key] = value
    return data


def _merged_env() -> dict[str, str]:
    dotenv = _load_dotenv(_repo_root() / ".env")
    merged = dict(dotenv)
    for key, value in os.environ.items():
        merged[key] = value
    return merged


_ENV = _merged_env()


# ---------------------------------------------------------------------------
# Typed getters and parsers
# ---------------------------------------------------------------------------


def _missing_message(key: str) -> str:
    return (
        f"Missing required config key '{key}'. "
        "Copy .env.example to .env and set the value."
    )


def get_required_str(key: str) -> str:
    value = _ENV.get(key, "").strip()
    if not value:
        raise ConfigError(_missing_message(key))
    return value


def get_optional_str(key: str) -> str:
    return _ENV.get(key, "").strip()


def get_required_int(key: str) -> int:
    raw = get_required_str(key)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"Config key '{key}' must be an integer, got: {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"Config key '{key}' must be > 0, got: {value}")
    return value


def get_csv_list(key: str) -> list[str]:
    raw = get_optional_str(key)
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def get_json_str_map(key: str) -> dict[str, str]:
    raw = get_required_str(key)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config key '{key}' must be valid JSON object.") from exc

    if not isinstance(parsed, dict):
        raise ConfigError(f"Config key '{key}' must be a JSON object.")

    out: dict[str, str] = {}
    for k, v in parsed.items():
        out[str(k)] = str(v)
    return out


# ---------------------------------------------------------------------------
# Stage-specific configuration sections
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarkdownToQmdSettings:
    input_dir: str
    output_dir: str


@dataclass(frozen=True)
class QmdToSsmlSettings:
    input_dir: str
    output_dir: str
    extra_text_files: list[str]
    ssml_lang: str
    voice_name: str


@dataclass(frozen=True)
class SsmlToMp3Settings:
    input_dir: str
    output_dir: str
    album: str
    artist: str
    user_agent: str
    ssml_lang: str
    voice_name: str
    title_acronyms: dict[str, str]
    max_chunk_chars: int
    azure_tts_key: str
    azure_tts_region: str


def load_markdown_to_qmd_settings() -> MarkdownToQmdSettings:
    return MarkdownToQmdSettings(
        input_dir=get_required_str("MARKDOWN_TO_QMD_INPUT_DIR"),
        output_dir=get_required_str("MARKDOWN_TO_QMD_OUTPUT_DIR"),
    )


def load_qmd_to_ssml_settings() -> QmdToSsmlSettings:
    return QmdToSsmlSettings(
        input_dir=get_required_str("QMD_TO_SSML_INPUT_DIR"),
        output_dir=get_required_str("QMD_TO_SSML_OUTPUT_DIR"),
        extra_text_files=get_csv_list("QMD_TO_SSML_EXTRA_TEXT_FILES"),
        ssml_lang=get_required_str("SHARED_SSML_LANG"),
        voice_name=get_required_str("SHARED_VOICE_NAME"),
    )


def load_ssml_to_mp3_settings(require_azure: bool = True) -> SsmlToMp3Settings:
    key = get_required_str("AZURE_TTS_KEY") if require_azure else get_optional_str("AZURE_TTS_KEY")
    region = (
        get_required_str("AZURE_TTS_REGION") if require_azure else get_optional_str("AZURE_TTS_REGION")
    )

    return SsmlToMp3Settings(
        input_dir=get_required_str("SSML_TO_MP3_INPUT_DIR"),
        output_dir=get_required_str("SSML_TO_MP3_OUTPUT_DIR"),
        album=get_required_str("SSML_TO_MP3_ALBUM"),
        artist=get_required_str("SSML_TO_MP3_ARTIST"),
        user_agent=get_required_str("SSML_TO_MP3_USER_AGENT"),
        ssml_lang=get_required_str("SHARED_SSML_LANG"),
        voice_name=get_required_str("SHARED_VOICE_NAME"),
        title_acronyms=get_json_str_map("SSML_TO_MP3_TITLE_ACRONYMS"),
        max_chunk_chars=get_required_int("SSML_TO_MP3_MAX_CHUNK_CHARS"),
        azure_tts_key=key,
        azure_tts_region=region,
    )
