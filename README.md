# Бот редактирования фото + оплата через Telegram Stars

## Запуск
1. `python -m venv venv && source venv/bin/activate` (Windows: `venv\Scripts\activate`)
2. `pip install -r requirements.txt`
3. Скопируй `.env.example` в `.env` и заполни токены и `ADMIN_IDS`.
4. `python bot.py`

В BotFather ничего включать не нужно — Stars работают у любого бота.

## Как это работает
Пользователь → фото → описание → бот списывает 1 генерацию → Problembo → результат.
Если генерация упала — генерация возвращается на баланс.

Оплата: `/buy` → выбор пакета → счёт в Stars → Telegram присылает
`pre_checkout_query` (проверяем пакет и сумму, отвечаем ok) →
после списания приходит `successful_payment` → начисляем генерации.

## Файлы
- `config.py` — настройки и **тарифы (PACKS)**, меняй цены здесь
- `db.py` — SQLite: баланс, платежи (защита от двойного начисления)
- `payments.py` — /buy, /balance, счёт, начисление, /refund, /grant
- `problembo.py` — API Problembo
- `bot.py` — основная логика

## Команды
Пользователь: /start, /balance, /buy, /cancel, /paysupport, /terms
Админ: `/refund <charge_id>` — вернуть Stars, `/grant <user_id> <n>` — подарить генерации

## Расчёт цен
Поставь цену пакета выше, чем стоит генерация в Problembo (с учётом
комиссий Apple/Google при покупке Stars). Проверь актуальный курс Stars.

## Оплата рублями / картами (ЮKassa и др.)
Подключи провайдера в BotFather → Payments, получишь provider token. В
`send_invoice` замени `currency="XTR"` на `"RUB"`, `provider_token` на токен,
а `amount` задавай в копейках (100 ₽ = 10000). В `pre_checkout` проверку
`currency != "XTR"` поменяй на `"RUB"`. Возврат у провайдеров делается через
их кабинет, а не `refund_star_payment`.

## Безопасность
Файл `.env` и `*.conf` (VPN) не должны попадать в git или в чужие руки.
