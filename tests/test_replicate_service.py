"""Тесты для ReplicateService."""

import asyncio
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bot.services.replicate_service import (
    FILES_ENDPOINT,
    MODEL_ENDPOINT,
    POLL_INTERVAL_SECONDS,
    ReplicateError,
    ReplicateService,
)


@pytest.fixture()
def tmp_video(tmp_path: Path) -> Path:
    """Создать временный файл-заглушку для референсного видео."""
    video = tmp_path / "test_video.mp4"
    video.write_bytes(b"fake-video-content")
    return video


@pytest.fixture()
def service(tmp_video: Path) -> ReplicateService:
    """Создать экземпляр сервиса с тестовым токеном."""
    return ReplicateService(
        api_token="test-token",
        reference_video_path=tmp_video,
    )


class TestBuildPhotoDataUri:
    """Тесты для конвертации фото в base64 data URI."""

    def test_returns_valid_data_uri(
        self, service: ReplicateService, sample_photo_bytes: bytes,
    ) -> None:
        result = service._build_photo_data_uri(sample_photo_bytes)
        assert result.startswith("data:image/jpeg;base64,")

    def test_roundtrip_decode(
        self, service: ReplicateService, sample_photo_bytes: bytes,
    ) -> None:
        result = service._build_photo_data_uri(sample_photo_bytes)
        encoded_part = result.split(",", maxsplit=1)[1]
        decoded = base64.b64decode(encoded_part)
        assert decoded == sample_photo_bytes


class TestUploadReferenceVideo:
    """Тесты для загрузки референсного видео."""

    @pytest.mark.asyncio()
    async def test_uploads_and_caches(self, service: ReplicateService) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {
            "urls": {"get": "https://replicate.delivery/test/video.mp4"},
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        service._client = mock_client

        url1 = await service._upload_reference_video()
        url2 = await service._upload_reference_video()

        assert url1 == "https://replicate.delivery/test/video.mp4"
        assert url2 == url1
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio()
    async def test_raises_on_http_error(self, service: ReplicateService) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = False
        mock_response.status_code = 500
        mock_response.json.return_value = {"detail": "server error"}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        service._client = mock_client

        with pytest.raises(ReplicateError, match="HTTP 500"):
            await service._upload_reference_video()


class TestCreatePrediction:
    """Тесты для создания предикшна."""

    @pytest.mark.asyncio()
    async def test_returns_prediction_id(self, service: ReplicateService) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"id": "pred-123"}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        service._client = mock_client

        result = await service._create_prediction(
            "data:image/jpeg;base64,abc",
            "https://replicate.delivery/test/video.mp4",
        )

        assert result == "pred-123"
        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["input"]["image"] == "data:image/jpeg;base64,abc"
        assert payload["input"]["video"] == "https://replicate.delivery/test/video.mp4"

    @pytest.mark.asyncio()
    async def test_sends_correct_endpoint(self, service: ReplicateService) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"id": "pred-456"}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        service._client = mock_client

        await service._create_prediction("img", "vid")

        call_args = mock_client.post.call_args
        endpoint = call_args[0][0] if call_args[0] else call_args.kwargs.get("url")
        assert endpoint == MODEL_ENDPOINT


class TestPollPrediction:
    """Тесты для поллинга статуса предикшна."""

    @pytest.mark.asyncio()
    async def test_immediate_success(self, service: ReplicateService) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {
            "status": "succeeded",
            "output": "https://result.com/video.mp4",
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.get = AsyncMock(return_value=mock_response)
        service._client = mock_client

        result = await service._poll_prediction("pred-123")
        assert result == "https://result.com/video.mp4"
        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio()
    async def test_transitions_to_success(self, service: ReplicateService) -> None:
        responses = []
        for status in ("starting", "processing", "succeeded"):
            resp = MagicMock(spec=httpx.Response)
            resp.is_success = True
            resp.json.return_value = {
                "status": status,
                "output": "https://result.com/video.mp4" if status == "succeeded" else None,
            }
            responses.append(resp)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=responses)
        service._client = mock_client

        with patch("bot.services.replicate_service.asyncio.sleep", new_callable=AsyncMock):
            result = await service._poll_prediction("pred-123")

        assert result == "https://result.com/video.mp4"
        assert mock_client.get.call_count == 3

    @pytest.mark.asyncio()
    async def test_raises_on_failed(self, service: ReplicateService) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {
            "status": "failed",
            "error": "model crashed",
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.get = AsyncMock(return_value=mock_response)
        service._client = mock_client

        with pytest.raises(ReplicateError, match="model crashed"):
            await service._poll_prediction("pred-123")

    @pytest.mark.asyncio()
    async def test_raises_on_timeout(self, service: ReplicateService) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"status": "processing"}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.get = AsyncMock(return_value=mock_response)
        service._client = mock_client

        with (
            patch("bot.services.replicate_service.POLL_TIMEOUT_SECONDS", 0),
            patch("bot.services.replicate_service.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(ReplicateError, match="Превышено время ожидания"),
        ):
            await service._poll_prediction("pred-123")


class TestGenerateDanceVideo:
    """Интеграционный тест полного флоу генерации."""

    @pytest.mark.asyncio()
    async def test_full_flow(
        self, service: ReplicateService, sample_photo_bytes: bytes,
    ) -> None:
        upload_response = MagicMock(spec=httpx.Response)
        upload_response.is_success = True
        upload_response.json.return_value = {
            "urls": {"get": "https://replicate.delivery/video.mp4"},
        }

        prediction_response = MagicMock(spec=httpx.Response)
        prediction_response.is_success = True
        prediction_response.json.return_value = {"id": "pred-789"}

        poll_response = MagicMock(spec=httpx.Response)
        poll_response.is_success = True
        poll_response.json.return_value = {
            "status": "succeeded",
            "output": "https://result.com/dance.mp4",
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=[upload_response, prediction_response])
        mock_client.get = AsyncMock(return_value=poll_response)
        service._client = mock_client

        result = await service.generate_dance_video(sample_photo_bytes)

        assert result == "https://result.com/dance.mp4"
        assert mock_client.post.call_count == 2
        assert mock_client.get.call_count == 1
