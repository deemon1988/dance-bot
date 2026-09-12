"""Сервис для взаимодействия с Replicate API.

Генерация танцевального видео с помощью модели Kling v2.6 Motion Control.
Не зависит от aiogram — принимает байты, возвращает URL.
"""

import asyncio
import base64
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

REPLICATE_API_BASE = "https://api.replicate.com"
MODEL_ENDPOINT = "/v1/models/kwaivgi/kling-v2.6-motion-control/predictions"
FILES_ENDPOINT = "/v1/files"

POLL_INTERVAL_SECONDS = 15
POLL_TIMEOUT_SECONDS = 900  # 15 минут

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "canceled"})


class ReplicateError(Exception):
    """Ошибка при работе с Replicate API."""


class ReplicateService:
    """Сервис генерации танцевальных видео через Replicate."""

    def __init__(self, api_token: str, reference_video_path: Path) -> None:
        self._api_token = api_token
        self._reference_video_path = reference_video_path
        self._reference_video_url: str | None = None
        self._upload_lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Получить или создать HTTP-клиент."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=REPLICATE_API_BASE,
                headers={"Authorization": f"Bearer {self._api_token}"},
                timeout=httpx.Timeout(30.0, read=60.0),
            )
        return self._client

    async def generate_dance_video(self, photo_bytes: bytes) -> str:
        """Сгенерировать танцевальное видео из фото пользователя.

        Args:
            photo_bytes: JPEG/PNG фото пользователя в байтах.

        Returns:
            URL сгенерированного видео.

        Raises:
            ReplicateError: при ошибке API или таймауте.
        """
        video_url = await self._upload_reference_video()
        image_uri = self._build_photo_data_uri(photo_bytes)
        prediction_id = await self._create_prediction(image_uri, video_url)
        logger.info("Предикшн создан: %s", prediction_id)
        result_url = await self._poll_prediction(prediction_id)
        return result_url

    async def _upload_reference_video(self) -> str:
        """Загрузить референсное видео на Replicate (с кэшированием)."""
        if self._reference_video_url is not None:
            return self._reference_video_url

        async with self._upload_lock:
            if self._reference_video_url is not None:
                return self._reference_video_url

            logger.info("Загрузка референсного видео: %s", self._reference_video_path)
            video_data = self._reference_video_path.read_bytes()
            client = self._get_client()

            response = await client.post(
                FILES_ENDPOINT,
                files={"content": ("source.mp4", video_data, "video/mp4")},
            )
            self._check_response(response, "загрузка видео")

            data = response.json()
            url = data.get("urls", {}).get("get")
            if not url:
                raise ReplicateError(
                    f"Replicate не вернул URL файла: {data}"
                )

            self._reference_video_url = url
            logger.info("Референсное видео загружено: %s", url)
            return url

    @staticmethod
    def _build_photo_data_uri(photo_bytes: bytes) -> str:
        """Конвертировать байты фото в base64 data URI."""
        encoded = base64.b64encode(photo_bytes).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    async def _create_prediction(self, image_uri: str, video_url: str) -> str:
        """Создать предикшн на Replicate."""
        client = self._get_client()
        payload = {
            "input": {
                "image": image_uri,
                "video": video_url,
                "character_orientation": "image",
                "mode": "std",
                "keep_original_sound": True,
            },
        }

        response = await client.post(MODEL_ENDPOINT, json=payload)
        self._check_response(response, "создание предикшна")

        data = response.json()
        prediction_id = data.get("id")
        if not prediction_id:
            raise ReplicateError(f"Replicate не вернул ID предикшна: {data}")
        return prediction_id

    async def _poll_prediction(self, prediction_id: str) -> str:
        """Опрашивать статус предикшна до завершения."""
        client = self._get_client()
        url = f"/v1/predictions/{prediction_id}"
        start_time = time.monotonic()

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > POLL_TIMEOUT_SECONDS:
                raise ReplicateError(
                    f"Превышено время ожидания генерации ({POLL_TIMEOUT_SECONDS} сек)"
                )

            response = await client.get(url)
            self._check_response(response, "проверка статуса")

            data = response.json()
            status = data.get("status")
            logger.debug("Предикшн %s: статус=%s", prediction_id, status)

            if status == "succeeded":
                output = data.get("output")
                if not output:
                    raise ReplicateError(
                        f"Предикшн завершён, но нет результата: {data}"
                    )
                return output

            if status in ("failed", "canceled"):
                error = data.get("error", "нет деталей")
                raise ReplicateError(
                    f"Генерация не удалась (статус={status}): {error}"
                )

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    @staticmethod
    def _check_response(response: httpx.Response, context: str) -> None:
        """Проверить HTTP-ответ и выбросить ошибку при неуспехе."""
        if response.is_success:
            return
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise ReplicateError(
            f"Ошибка Replicate API при {context}: "
            f"HTTP {response.status_code}, ответ: {detail}"
        )

    async def close(self) -> None:
        """Закрыть HTTP-клиент."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
