# -*- coding: utf-8 -*-
"""Оплата через Telegram Stars (валюта XTR)."""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

import db
from config import ADMIN_IDS, PACKS

logger = logging.getLogger(__name__)
router = Router()


def packs_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{p.credits} генераций — {p.stars} ⭐",
                callback_data=f"buy:{p.id}",
            )
        ]
        for p in PACKS.values()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("balance"))
async def balance(message: Message):
    credits = await db.ensure_user(message.from_user.id)
    await message.answer(f"Твой баланс: {credits} генераций.\n/buy — пополнить")


@router.message(Command("buy"))
async def buy(message: Message):
    await message.answer(
        "Выбери пакет генераций (оплата в Telegram Stars):",
        reply_markup=packs_keyboard(),
    )


@router.callback_query(F.data.startswith("buy:"))
async def send_invoice(callback: CallbackQuery):
    pack = PACKS.get(callback.data.split(":", 1)[1])
    if pack is None:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    await callback.message.answer_invoice(
        title=f"{pack.credits} генераций",
        description=f"Пакет из {pack.credits} редактирований фото",
        payload=f"pack:{pack.id}",       # вернётся нам в pre_checkout и payment
        currency="XTR",                  # XTR = Telegram Stars
        prices=[LabeledPrice(label=f"{pack.credits} генераций",
                             amount=pack.stars)],
        provider_token="",               # для Stars токен провайдера пустой
    )
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    """Telegram спрашивает 'можно списывать?'. Нужно ответить за 10 секунд."""
    pack_id = (query.invoice_payload or "").removeprefix("pack:")
    pack = PACKS.get(pack_id)

    if pack is None or query.total_amount != pack.stars or query.currency != "XTR":
        await query.answer(ok=False, error_message="Тариф недоступен, попробуй /buy")
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def paid(message: Message):
    """Деньги списаны — начисляем генерации."""
    sp = message.successful_payment
    pack = PACKS.get(sp.invoice_payload.removeprefix("pack:"))

    if pack is None:
        # Деньги получены, а пакет неизвестен — сообщаем админам, не теряем charge_id
        logger.error("Оплата неизвестного пакета: %s", sp)
        await message.answer(
            "Платёж получен, но возникла ошибка. Напиши /paysupport"
        )
        return

    added = await db.record_payment(
        sp.telegram_payment_charge_id,
        message.from_user.id,
        pack.id,
        sp.total_amount,
        pack.credits,
    )
    if not added:
        return  # дубликат события

    credits = await db.get_balance(message.from_user.id)
    await message.answer(
        f"Оплата прошла ✅ Начислено: {pack.credits} генераций.\n"
        f"Баланс: {credits}. Отправь фото!"
    )


@router.message(Command("paysupport"))
async def pay_support(message: Message):
    # Telegram требует, чтобы бот с платежами отвечал на эту команду
    await message.answer(
        "Проблемы с оплатой? Напиши администратору и приложи ID платежа "
        "(он есть в чеке Telegram). Возврат Stars возможен, если "
        "генерации не использованы."
    )


@router.message(Command("terms"))
async def terms(message: Message):
    await message.answer(
        "Условия: оплата в Telegram Stars, 1 генерация = 1 обработка фото. "
        "Если обработка не удалась, генерация возвращается на баланс. "
        "Неиспользованные генерации можно вернуть через /paysupport."
    )


# ---------- Админ-команды ----------

@router.message(Command("refund"))
async def refund(message: Message, command: CommandObject, bot: Bot):
    """/refund <charge_id> — вернуть Stars пользователю."""
    if message.from_user.id not in ADMIN_IDS:
        return
    charge_id = (command.args or "").strip()
    if not charge_id:
        await message.answer("Использование: /refund <charge_id>")
        return

    payment = await db.get_payment(charge_id)
    if payment is None:
        await message.answer("Платёж не найден в базе.")
        return
    if payment["refunded"]:
        await message.answer("Этот платёж уже возвращён.")
        return

    try:
        await bot.refund_star_payment(
            user_id=payment["user_id"],
            telegram_payment_charge_id=charge_id,
        )
    except Exception as e:
        await message.answer(f"Telegram отклонил возврат: {e}")
        return

    await db.mark_refunded(charge_id, payment["user_id"], payment["credits"])
    await message.answer("Возврат выполнен, генерации списаны с баланса.")


@router.message(Command("grant"))
async def grant(message: Message, command: CommandObject):
    """/grant <user_id> <кол-во> — выдать генерации вручную."""
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        user_id, amount = (int(x) for x in (command.args or "").split())
    except ValueError:
        await message.answer("Использование: /grant <user_id> <кол-во>")
        return
    await db.ensure_user(user_id)
    await db.add_credits(user_id, amount)
    await message.answer(f"Выдано {amount} генераций пользователю {user_id}.")
