"""Роутер для обработки фото, оплаты и генерации танцевальных видео."""

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import (
    ContentType,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    URLInputFile,
)

from bot.services.replicate_service import ReplicateError, ReplicateService

router = Router()
logger = logging.getLogger(__name__)

# --- Цена ---
DANCE_VIDEO_PRICE_STARS = 200
DANCE_VIDEO_PRICE_LABEL = "Танцевальное видео"
INVOICE_TITLE = "Генерация танцевального видео"
INVOICE_DESCRIPTION = (
    "Нейросеть создаст танцевальное видео из вашего фото. "
    "Генерация займет 6-11 минут."
)
INVOICE_PAYLOAD = "dance_video"

# --- Сообщения ---
MSG_SEND_PHOTO = (
    "Отправьте мне фото, и я сделаю из него танцевальное видео!\n"
    f"Стоимость: {DANCE_VIDEO_PRICE_STARS} Stars (~199 руб.)"
)
MSG_PHOTO_RECEIVED = (
    "Фото получено! Для генерации видео необходимо оплатить "
    f"{DANCE_VIDEO_PRICE_STARS} Stars (~199 руб.)"
)
MSG_GENERATION_STARTED = (
    "Оплата прошла успешно! Запускаю генерацию танцевального видео.\n"
    "Это займет 6-11 минут, подождите..."
)
MSG_STILL_WORKING = "Генерация продолжается, пожалуйста подождите..."
MSG_SUCCESS = "Ваше танцевальное видео готово!"
MSG_DOCUMENT_CAPTION = "Видео в оригинальном качестве"
MSG_FAILED = (
    "К сожалению, генерация видео не удалась. "
    "Попробуйте отправить другое фото — мы вернем Stars."
)
MSG_NO_PHOTO = "Сначала отправьте мне фото, а затем оплатите генерацию."

PROGRESS_UPDATE_INTERVAL_SECONDS = 120

# Хранилище фото пользователей, ожидающих оплату.
# Ключ — user_id, значение — байты фото.
_pending_photos: dict[int, bytes] = {}


@router.message(Command("start"))
async def handle_start(message: Message) -> None:
    """Приветствие при /start."""
    await message.answer(MSG_SEND_PHOTO)


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot) -> None:
    """Принять фото и отправить инвойс на оплату."""
    user_id = message.from_user.id

    photo = message.photo[-1]
    file = await bot.download(photo.file_id)
    photo_bytes = file.read()
    _pending_photos[user_id] = photo_bytes

    await message.answer(MSG_PHOTO_RECEIVED)
    await bot.send_invoice(
        chat_id=message.chat.id,
        title=INVOICE_TITLE,
        description=INVOICE_DESCRIPTION,
        payload=INVOICE_PAYLOAD,
        currency="XTR",
        prices=[LabeledPrice(label=DANCE_VIDEO_PRICE_LABEL, amount=DANCE_VIDEO_PRICE_STARS)],
        provider_token="",
    )


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    """Подтвердить или отклонить платёж перед списанием."""
    user_id = pre_checkout_query.from_user.id

    if user_id not in _pending_photos:
        await pre_checkout_query.answer(ok=False, error_message=MSG_NO_PHOTO)
        return

    await pre_checkout_query.answer(ok=True)


@router.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def handle_successful_payment(
    message: Message,
    bot: Bot,
    replicate_service: ReplicateService,
) -> None:
    """Обработать успешную оплату и запустить генерацию."""
    user_id = message.from_user.id
    payment = message.successful_payment

    logger.info(
        "Оплата получена: user_id=%s, amount=%s %s, charge_id=%s",
        user_id,
        payment.total_amount,
        payment.currency,
        payment.telegram_payment_charge_id,
    )

    photo_bytes = _pending_photos.pop(user_id, None)
    if not photo_bytes:
        await message.answer(MSG_NO_PHOTO)
        return

    status_message = await message.answer(MSG_GENERATION_STARTED)

    asyncio.create_task(
        _process_dance_generation(
            message,
            bot,
            status_message,
            photo_bytes,
            replicate_service,
            payment.telegram_payment_charge_id,
        ),
    )


async def _process_dance_generation(
    original_message: Message,
    bot: Bot,
    status_message: Message,
    photo_bytes: bytes,
    replicate_service: ReplicateService,
    telegram_charge_id: str,
) -> None:
    """Фоновая задача: генерация видео и отправка результата."""
    chat_id = original_message.chat.id
    user_id = original_message.from_user.id

    progress_task = asyncio.create_task(
        _send_progress_updates(bot, chat_id, status_message),
    )

    try:
        result_url = await replicate_service.generate_dance_video(photo_bytes)
        progress_task.cancel()

        await bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
        video_file = URLInputFile(result_url, filename="dance.mp4")
        await bot.send_video(chat_id, video=video_file, caption=MSG_SUCCESS)

        document_file = URLInputFile(result_url, filename="dance.mp4")
        await bot.send_document(
            chat_id, document=document_file, caption=MSG_DOCUMENT_CAPTION,
        )

    except ReplicateError as exc:
        progress_task.cancel()
        logger.error("Ошибка генерации для user_id=%s: %s", user_id, exc)
        await _refund_and_notify(bot, chat_id, user_id, telegram_charge_id)

    except Exception:
        progress_task.cancel()
        logger.exception("Непредвиденная ошибка для user_id=%s", user_id)
        await _refund_and_notify(bot, chat_id, user_id, telegram_charge_id)


async def _refund_and_notify(
    bot: Bot,
    chat_id: int,
    user_id: int,
    telegram_charge_id: str,
) -> None:
    """Вернуть Stars и уведомить пользователя об ошибке."""
    try:
        await bot.refund_star_payment(
            user_id=user_id,
            telegram_payment_charge_id=telegram_charge_id,
        )
        logger.info("Возврат Stars выполнен: user_id=%s", user_id)
    except Exception:
        logger.exception("Ошибка возврата Stars для user_id=%s", user_id)

    await bot.send_message(chat_id, MSG_FAILED)


async def _send_progress_updates(
    bot: Bot,
    chat_id: int,
    status_message: Message,
) -> None:
    """Периодически обновлять статус-сообщение для пользователя."""
    try:
        minutes_passed = 2
        while True:
            await asyncio.sleep(PROGRESS_UPDATE_INTERVAL_SECONDS)
            await bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
            await status_message.edit_text(
                f"{MSG_STILL_WORKING} (прошло ~{minutes_passed} мин.)",
            )
            minutes_passed += 2
    except asyncio.CancelledError:
        pass
