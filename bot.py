# -*- coding: utf-8 -*-
import asyncio
import logging
import tempfile
import json

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message

import db
import payments
import problembo
from config import API_TOKEN, BOT_TOKEN, FREE_GENERATIONS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()
dp.include_router(payments.router)  # /buy, /balance, оплата, админ-команды

user_photos = {}   # user_id -> bytes (фото ждёт описания)
busy_users = set() # кто сейчас обрабатывается (защита от двойного списания)


@dp.message(CommandStart())
async def start(message: Message):
    credits = await db.ensure_user(message.from_user.id)
    await message.answer(
        "Привет! Отправь фотографию, а затем подробно напиши, что нужно изменить.\n\n"
        f"Твой баланс: {credits} генераций\n"
        "/balance — баланс\n/buy — купить генерации\n/cancel — отменить"
    )


@dp.message(Command("cancel"))
async def cancel(message: Message):
    user_photos.pop(message.from_user.id, None)
    await message.answer("Отменено. Отправь новое фото, чтобы начать заново.")


@dp.message(F.photo)
async def receive_photo(message: Message):
    user_id = message.from_user.id
    await db.ensure_user(user_id)

    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    buffer = await bot.download_file(file_info.file_path)
    photo_bytes = buffer.read()

    if not photo_bytes:
        await message.answer("Не удалось загрузить фотографию.")
        return

    user_photos[user_id] = photo_bytes
    await message.answer("Фото получено! Теперь подробно напиши, что изменить (минимум 5 слов).")


# Команды (/buy и т.д.) сюда не попадают благодаря фильтру
@dp.message(F.text & ~F.text.startswith("/"))
async def receive_prompt(message: Message):
    user_id = message.from_user.id
    prompt = (message.text or "").strip()

    photo_bytes = user_photos.get(user_id)
    if not photo_bytes:
        await message.answer(
            "Сначала отправь фотографию, а затем напиши описание изменений."
        )
        return

    if user_id in busy_users:
        await message.answer("Предыдущее фото ещё обрабатывается, подожди.")
        return

    # 1) Списываем генерацию ДО запроса к API (атомарно в БД)
    await db.ensure_user(user_id)
    if not await db.spend_credit(user_id):
        await message.answer(
            "Генерации закончились. Выбери пакет — фото сохранено, "
            "после оплаты просто повтори описание:",
            reply_markup=payments.packs_keyboard(),
        )
        return

    busy_users.add(user_id)
    status_message = await message.answer("Обрабатываю изображение. Подожди...")
    timeout = aiohttp.ClientTimeout(total=300)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            file_id = await problembo.upload_photo(session, photo_bytes, "source.jpg")
            task_response = await problembo.create_task(session, file_id, prompt)

            payload = task_response.get("payload", task_response)
            task_id = payload.get("taskId")
            if not task_id:
                raise RuntimeError(
                    "API не вернул taskId: "
                    + json.dumps(task_response, ensure_ascii=False)[:1500]
                )

            await status_message.edit_text("Задача создана. Генерирую изображение...")
            result_url = await problembo.wait_result(session, task_id)

            with tempfile.TemporaryDirectory() as temp_dir:
                path = await problembo.download_result(session, result_url, temp_dir)
                credits = await db.get_balance(user_id)
                await message.answer_photo(
                    FSInputFile(path),
                    caption=f"Готово! Осталось генераций: {credits}",
                )

        user_photos.pop(user_id, None)
        await status_message.delete()

    except Exception as error:
        logger.exception("Ошибка редактирования")

        # 2) Ошибка — возвращаем генерацию
        await db.add_credits(user_id, 1)

        error_text = str(error)
        if API_TOKEN:
            error_text = error_text.replace(API_TOKEN, "[СКРЫТО]")

        await status_message.edit_text(
            "Не удалось обработать изображение. Генерация возвращена на баланс.\n\n"
            f"Причина: {error_text[:1200]}"
        )
    finally:
        busy_users.discard(user_id)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN в .env")
    if not API_TOKEN:
        raise RuntimeError("Не задан PROBLEMBO_API_TOKEN в .env")

    await db.init_db()
    logger.info("Бот запускается")
    try:
        # pre_checkout_query и message нужны для оплаты
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
