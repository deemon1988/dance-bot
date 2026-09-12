"""Тесты для платёжного флоу и обработки фото."""

import pytest

from bot.routers.dance_router import (
    DANCE_VIDEO_PRICE_STARS,
    INVOICE_PAYLOAD,
    _pending_photos,
)


class TestPendingPhotosStorage:
    """Тесты для хранилища фото, ожидающих оплату."""

    def test_store_and_retrieve(self, sample_photo_bytes: bytes) -> None:
        user_id = 12345
        _pending_photos[user_id] = sample_photo_bytes

        assert _pending_photos[user_id] == sample_photo_bytes

        retrieved = _pending_photos.pop(user_id)
        assert retrieved == sample_photo_bytes
        assert user_id not in _pending_photos

    def test_overwrite_on_new_photo(self, sample_photo_bytes: bytes) -> None:
        user_id = 12345
        old_photo = b"old-photo"
        new_photo = sample_photo_bytes

        _pending_photos[user_id] = old_photo
        _pending_photos[user_id] = new_photo

        assert _pending_photos.pop(user_id) == new_photo


class TestPaymentConstants:
    """Тесты для корректности констант оплаты."""

    def test_price_is_positive(self) -> None:
        assert DANCE_VIDEO_PRICE_STARS > 0

    def test_price_is_200_stars(self) -> None:
        assert DANCE_VIDEO_PRICE_STARS == 200

    def test_payload_is_not_empty(self) -> None:
        assert INVOICE_PAYLOAD
        assert len(INVOICE_PAYLOAD) <= 128
