"""Инициализация и запуск бота."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from bot.config import load_config
from bot.routers.dance_router import router as dance_router
from bot.services.replicate_service import ReplicateService

logger = logging.getLogger(__name__)


async def main() -> None:
    """Точка входа: создание и запуск бота."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = load_config()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(),
    )

    replicate_service = ReplicateService(
        api_token=config.replicate_api_token,
        reference_video_path=config.reference_video_path,
    )

    dp = Dispatcher()
    dp.include_router(dance_router)
    dp["replicate_service"] = replicate_service

    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await replicate_service.close()
        await bot.session.close()
        logger.info("Бот остановлен")
