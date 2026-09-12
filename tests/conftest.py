"""Общие фикстуры для тестов."""

import pytest


@pytest.fixture()
def sample_photo_bytes() -> bytes:
    """Минимальные байты для имитации JPEG-фото."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
