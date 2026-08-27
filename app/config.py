from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

SocialFormat = Literal[
    "ig_feed", "ig_portrait", "ig_story", "tiktok", "fb_post", "x_post"
]

DEFAULT_ANTHROPIC_MODEL = "anthropic/claude-sonnet-4-5"
DEFAULT_OPENAI_MODEL = "openai/gpt-4o"

SOCIAL_SIZES: dict[SocialFormat, tuple[int, int]] = {
    "ig_feed": (1080, 1080),
    "ig_portrait": (1080, 1350),
    "ig_story": (1080, 1920),
    "tiktok": (1080, 1920),
    "fb_post": (1080, 1080),
    "x_post": (1600, 900),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    fal_key: str = Field(default="", alias="FAL_KEY")
    # Prefer LLM_MODEL; CLAUDE_MODEL kept as legacy alias via validator below
    llm_model: str = Field(default="", alias="LLM_MODEL")
    claude_model: str = Field(default="", alias="CLAUDE_MODEL")
    locked_font_family: str = Field(default="DM Sans", alias="LOCKED_FONT_FAMILY")
    locked_font_url: str = Field(
        default=(
            "https://fonts.googleapis.com/css2?"
            "family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,700;"
            "1,9..40,400&display=swap"
        ),
        alias="LOCKED_FONT_URL",
    )
    recraft_model: str = Field(
        default="fal-ai/recraft/v3/text-to-image",
        alias="RECRAFT_MODEL",
    )

    database_url: str = Field(
        default="postgresql+psycopg://postner:postner@localhost:5434/postner",
        alias="DATABASE_URL",
    )
    jwt_secret: str = Field(default="dev-secret-change-me", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60 * 24 * 7, alias="JWT_EXPIRE_MINUTES")

    # Object storage (S3-compatible: R2, AWS S3, MinIO, …). Default local = no upload.
    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")
    storage_bucket: str = Field(default="", alias="STORAGE_BUCKET")
    storage_access_key_id: str = Field(default="", alias="STORAGE_ACCESS_KEY_ID")
    storage_secret_access_key: str = Field(default="", alias="STORAGE_SECRET_ACCESS_KEY")
    storage_endpoint_url: str = Field(default="", alias="STORAGE_ENDPOINT_URL")
    storage_region: str = Field(default="auto", alias="STORAGE_REGION")
    storage_public_base_url: str = Field(default="", alias="STORAGE_PUBLIC_BASE_URL")

    templates_dir: Path = REPO_ROOT / "templates"
    variants_dir: Path = REPO_ROOT / "variants"
    brands_dir: Path = REPO_ROOT / "brands"
    output_dir: Path = REPO_ROOT / "output"

    @model_validator(mode="after")
    def _merge_model_aliases(self) -> Settings:
        # If only CLAUDE_MODEL is set, treat it as the explicit model choice
        if not self.llm_model and self.claude_model:
            self.llm_model = self.claude_model
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_size(format_name: SocialFormat) -> tuple[int, int]:
    return SOCIAL_SIZES[format_name]


def has_llm_credentials(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(s.anthropic_api_key or s.openai_api_key)


def resolve_llm_model(settings: Settings | None = None) -> str:
    """Pick LiteLLM model id from env + available keys.

    - Explicit LLM_MODEL / CLAUDE_MODEL wins
    - Else OpenAI-only → openai/gpt-4o
    - Else (Anthropic present, or both) → anthropic/claude-sonnet-4-5
    """
    s = settings or get_settings()
    if s.llm_model.strip():
        return s.llm_model.strip()
    if s.openai_api_key and not s.anthropic_api_key:
        return DEFAULT_OPENAI_MODEL
    return DEFAULT_ANTHROPIC_MODEL
