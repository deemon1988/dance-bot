"""Конфигурация бота. Загрузка переменных окружения."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(_ENV_PATH)


def _require_env(name: str) -> str:
    """Получить обязательную переменную окружения или вызвать ошибку."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Переменная окружения {name} не задана")
    return value


@dataclass(frozen=True)
class Config:
    """Неизменяемая конфигурация приложения."""

    bot_token: str
    replicate_api_token: str
    reference_video_path: Path


def load_config() -> Config:
    """Загрузить конфигурацию из переменных окружения."""
    return Config(
        bot_token=_require_env("BOT_TOKEN"),
        replicate_api_token=_require_env("REPLICATE_API_TOKEN"),
        reference_video_path=PROJECT_ROOT / "source7.mp4",
    )
