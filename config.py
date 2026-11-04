# -*- coding: utf-8 -*-
"""Настройки бота и тарифы."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_TOKEN = os.getenv("PROBLEMBO_API_TOKEN")
MODEL_ID = os.getenv("PROBLEMBO_MODEL_ID", "gpt-image")
API_BASE = "https://problembo.com/apis/v1/client"

DB_PATH = os.getenv("DB_PATH", "bot.db")
FREE_GENERATIONS = int(os.getenv("FREE_GENERATIONS", "1"))

ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
}


@dataclass(frozen=True)
class Pack:
    id: str        # короткий id, попадает в payload счёта
    credits: int   # сколько генераций получает пользователь
    stars: int     # цена в Telegram Stars


# Меняй цены под свою себестоимость (стоимость генерации в Problembo)
PACKS = {
    p.id: p
    for p in (
        Pack("p5", 1, 10),
        Pack("p20", 20, 160),
        Pack("p50", 50, 350),
    )
}
