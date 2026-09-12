# Dance Bot

Telegram-бот, который генерирует танцевальные видео из фотографий с помощью нейросети [Kling v2.6 Motion Control](https://replicate.com/kwaivgi/kling-v2.6-motion-control).

## Как работает

1. Пользователь отправляет фото в Telegram
2. Бот выставляет счёт на 200 Telegram Stars (~199 руб.)
3. После оплаты — берёт референсное видео с танцем (`source7.mp4`) и фото пользователя
4. Отправляет их в нейросеть Kling v2.6 Motion Control через Replicate API
5. Через 6-11 минут возвращает результат — видео с танцем и документ в оригинальном качестве
6. При ошибке генерации — автоматический возврат Stars

## Требования

- Python 3.12+
- Telegram Bot Token (через [@BotFather](https://t.me/BotFather))
- Replicate API Token (https://replicate.com/account/api-tokens)
- Референсное видео `source7.mp4` в корне проекта

## Установка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Переменные окружения

Создайте файл `.env` на основе `.env.example`:

```
BOT_TOKEN=ваш_токен_telegram_бота
REPLICATE_API_TOKEN=ваш_токен_replicate
```

## Запуск

```bash
source .venv/bin/activate
PYTHONPATH=src python -m bot
```

## Тесты

```bash
PYTHONPATH=src pytest tests/ -v
```

## Структура проекта

```
src/bot/
├── __main__.py              # точка входа
├── main.py                  # инициализация и запуск polling
├── config.py                # загрузка конфигурации из .env
├── routers/
│   └── dance_router.py      # обработчик фото, оплата Stars, генерация
└── services/
    └── replicate_service.py # взаимодействие с Replicate API
```

## Деплой / откат

- Для запуска достаточно настроить `.env` и запустить бота
- При откате — остановить процесс (`Ctrl+C`), бот корректно завершит работу
- Референсное видео кэшируется на Replicate — при перезапуске загрузится заново
