"""
Goofish Monitor Bot
Мониторинг объявлений на Goofish (闲鱼) с переводом и AI поиском по фото
"""

import asyncio
import logging
import json
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database as db
from goofish import GoofishParser
from image_ai import ImageAI
from translator import Translator
from config import BOT_TOKEN, ALLOWED_USERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
parser = GoofishParser()
image_ai = ImageAI()
translator = Translator()


# ══════════════════════════════════════════
# FSM
# ══════════════════════════════════════════

class NewSearch(StatesGroup):
    name = State()
    tags = State()
    price_min = State()
    price_max = State()
    interval = State()
    photo = State()

class PhotoSearch(StatesGroup):
    waiting = State()


# ══════════════════════════════════════════
# Middlewares — whitelist
# ══════════════════════════════════════════

@dp.message.outer_middleware()
async def auth_middleware(handler, message: types.Message, data: dict):
    if ALLOWED_USERS and message.from_user.id not in ALLOWED_USERS:
        await message.answer("⛔ Нет доступа. Напиши владельцу бота.")
        return
    return await handler(message, data)

@dp.callback_query.outer_middleware()
async def auth_cb_middleware(handler, cb: types.CallbackQuery, data: dict):
    if ALLOWED_USERS and cb.from_user.id not in ALLOWED_USERS:
        return
    return await handler(cb, data)


# ══════════════════════════════════════════
# Keyboards
# ══════════════════════════════════════════

def kb_main():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔍 Мои поиски"), KeyboardButton(text="➕ Новый поиск")],
        [KeyboardButton(text="🖼 Найти по фото"),  KeyboardButton(text="ℹ️ Помощь")],
    ], resize_keyboard=True)

def kb_searches(searches: list):
    b = InlineKeyboardBuilder()
    for s in searches:
        tags = json.loads(s["tags"])
        icon = "✅" if s["active"] else "⏸"
        b.button(
            text=f"{icon} {s['name']}  •  {', '.join(tags[:2])}",
            callback_data=f"s:{s['id']}"
        )
    b.adjust(1)
    return b.as_markup()

def kb_search_detail(sid: int, active: bool):
    b = InlineKeyboardBuilder()
    b.button(text="⏸ Пауза" if active else "▶️ Запуск",
             callback_data=f"toggle:{sid}")
    b.button(text="🗑 Удалить", callback_data=f"del:{sid}")
    b.button(text="◀️ Назад",  callback_data="list")
    b.adjust(2, 1)
    return b.as_markup()

def kb_intervals():
    b = InlineKeyboardBuilder()
    for mins, label in [(10,"10 мин"),(30,"30 мин"),(60,"1 час"),(180,"3 часа")]:
        b.button(text=label, callback_data=f"iv:{mins}")
    b.adjust(4)
    return b.as_markup()

def kb_skip_photo():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏭ Без фото", callback_data="skip_photo")
    ]])


# ══════════════════════════════════════════
# /start  ℹ️
# ══════════════════════════════════════════

@dp.message(Command("start"))
@dp.message(F.text == "ℹ️ Помощь")
async def cmd_start(message: types.Message):
    await message.answer(
        "🐟 <b>Goofish Monitor</b>\n\n"
        "Слежу за новыми объявлениями на <b>Goofish (闲鱼)</b> и сразу присылаю сюда.\n\n"
        "<b>Что умею:</b>\n"
        "• Мониторинг по ключевым словам (rick owens / rickowens / ro — всё в одном)\n"
        "• Фильтр по цене (в юанях ¥)\n"
        "• Автоперевод с китайского 🇨🇳→🇷🇺\n"
        "• Поиск похожих объявлений по твоему фото (AI)\n"
        "• Уведомления только о новых объявлениях\n\n"
        "Нажми <b>➕ Новый поиск</b> чтобы начать.",
        parse_mode="HTML",
        reply_markup=kb_main()
    )


# ══════════════════════════════════════════
# FSM — Новый поиск
# ══════════════════════════════════════════

@dp.message(F.text == "➕ Новый поиск")
async def new_search(message: types.Message, state: FSMContext):
    await state.set_state(NewSearch.name)
    await message.answer(
        "📝 Введи <b>название</b> поиска:\n"
        "<i>Например: Rick Owens Ramones, Balenciaga Triple S</i>",
        parse_mode="HTML"
    )

@dp.message(NewSearch.name)
async def ns_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(NewSearch.tags)
    await message.answer(
        "🏷 Введи <b>теги через запятую</b>:\n\n"
        "Все теги ищутся одновременно и объединяются в один поиск.\n"
        "<code>rick owens, rickowens, ro ramones, 瑞克欧文斯</code>\n\n"
        "<i>Совет: добавь китайский перевод бренда — найдёт больше!</i>",
        parse_mode="HTML"
    )

@dp.message(NewSearch.tags)
async def ns_tags(message: types.Message, state: FSMContext):
    tags = [t.strip() for t in message.text.split(",") if t.strip()]
    if not tags:
        await message.answer("❌ Введи хотя бы один тег.")
        return
    await state.update_data(tags=tags)
    await state.set_state(NewSearch.price_min)
    await message.answer(
        "💰 Минимальная цена в <b>юанях ¥</b>:\n"
        "<i>Отправь 0 чтобы пропустить</i>",
        parse_mode="HTML"
    )

@dp.message(NewSearch.price_min)
async def ns_price_min(message: types.Message, state: FSMContext):
    try:
        val = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Только число, например: 500")
        return
    await state.update_data(price_min=val)
    await state.set_state(NewSearch.price_max)
    await message.answer(
        "💰 Максимальная цена в <b>юанях ¥</b>:\n"
        "<i>Отправь 0 — без ограничений</i>",
        parse_mode="HTML"
    )

@dp.message(NewSearch.price_max)
async def ns_price_max(message: types.Message, state: FSMContext):
    try:
        val = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Только число, например: 3000")
        return
    await state.update_data(price_max=val)
    await state.set_state(NewSearch.interval)
    await message.answer("⏱ Как часто проверять новые объявления?",
                         reply_markup=kb_intervals())

@dp.callback_query(F.data.startswith("iv:"), NewSearch.interval)
async def ns_interval(cb: types.CallbackQuery, state: FSMContext):
    mins = int(cb.data.split(":")[1])
    await state.update_data(interval=mins)
    await cb.message.edit_text(
        "🖼 <b>Поиск по фото (AI)</b>\n\n"
        "Отправь фото вещи — бот будет находить объявления, "
        "где похожие фотографии.\n\n"
        "<i>Или пропусти — будет поиск только по тегам.</i>",
        parse_mode="HTML",
        reply_markup=kb_skip_photo()
    )
    await state.set_state(NewSearch.photo)

@dp.callback_query(F.data == "skip_photo", NewSearch.photo)
async def ns_skip_photo(cb: types.CallbackQuery, state: FSMContext):
    await _finish_search(cb.message, state, cb.from_user.id, embedding=None)

@dp.message(NewSearch.photo, F.photo)
async def ns_photo(message: types.Message, state: FSMContext):
    await message.answer("🔄 Обрабатываю фото...")
    file = await bot.get_file(message.photo[-1].file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    embedding = await image_ai.get_embedding_from_url(url)
    await _finish_search(message, state, message.from_user.id, embedding)

async def _finish_search(message: types.Message, state: FSMContext,
                         user_id: int, embedding):
    data = await state.get_data()
    await state.clear()
    await db.create_search(
        user_id=user_id,
        name=data["name"],
        tags=data["tags"],
        price_min=data.get("price_min", 0),
        price_max=data.get("price_max", 0),
        interval=data.get("interval", 30),
        embedding=embedding,
    )
    tags_str = ", ".join(data["tags"])
    pmin, pmax = data.get("price_min", 0), data.get("price_max", 0)
    price_str = ""
    if pmin or pmax:
        price_str = f"\n💰 Цена: {pmin or '—'}¥ — {pmax or '∞'}¥"
    ai_str = "\n🖼 AI-поиск по фото: включён ✅" if embedding else ""

    await message.answer(
        f"✅ <b>Поиск создан и запущен!</b>\n\n"
        f"📌 {data['name']}\n"
        f"🏷 Теги: <code>{tags_str}</code>"
        f"{price_str}\n"
        f"⏱ Интервал: {data.get('interval', 30)} мин"
        f"{ai_str}",
        parse_mode="HTML",
        reply_markup=kb_main()
    )


# ══════════════════════════════════════════
# Мои поиски
# ══════════════════════════════════════════

@dp.message(F.text == "🔍 Мои поиски")
async def my_searches(message: types.Message):
    searches = await db.get_user_searches(message.from_user.id)
    if not searches:
        await message.answer("У тебя пока нет поисков. Нажми ➕ Новый поиск!")
        return
    await message.answer(
        f"📋 <b>Твои поиски</b> ({len(searches)} шт):",
        parse_mode="HTML",
        reply_markup=kb_searches(searches)
    )

@dp.callback_query(F.data.startswith("s:"))
async def show_search(cb: types.CallbackQuery):
    sid = int(cb.data.split(":")[1])
    s = await db.get_search(sid)
    if not s:
        await cb.answer("Не найден")
        return
    tags = json.loads(s["tags"])
    pmin, pmax = s["price_min"], s["price_max"]
    price_str = f"{pmin or '—'}¥ — {pmax or '∞'}¥" if (pmin or pmax) else "без ограничений"
    status = "✅ Активен" if s["active"] else "⏸ На паузе"
    ai = "Да 🖼" if s["image_embedding"] else "Нет"
    count = await db.get_seen_count(sid)

    await cb.message.edit_text(
        f"<b>{s['name']}</b>\n\n"
        f"🏷 Теги: <code>{', '.join(tags)}</code>\n"
        f"💰 Цена: {price_str}\n"
        f"⏱ Интервал: {s['interval_minutes']} мин\n"
        f"🖼 AI-фото: {ai}\n"
        f"📦 Найдено объявлений: {count}\n"
        f"📊 Статус: {status}\n"
        f"🕐 Последняя проверка: {s['last_checked'][:16]}",
        parse_mode="HTML",
        reply_markup=kb_search_detail(sid, bool(s["active"]))
    )

@dp.callback_query(F.data.startswith("toggle:"))
async def toggle_search(cb: types.CallbackQuery):
    sid = int(cb.data.split(":")[1])
    s = await db.get_search(sid)
    await db.set_active(sid, not s["active"])
    await cb.answer("✅ Готово")
    await show_search(cb)

@dp.callback_query(F.data.startswith("del:"))
async def del_search(cb: types.CallbackQuery):
    sid = int(cb.data.split(":")[1])
    await db.delete_search(sid)
    await cb.answer("🗑 Удалено")
    searches = await db.get_user_searches(cb.from_user.id)
    if searches:
        await cb.message.edit_text("📋 <b>Твои поиски:</b>",
                                   parse_mode="HTML",
                                   reply_markup=kb_searches(searches))
    else:
        await cb.message.edit_text("Поисков нет. Создай новый — ➕")

@dp.callback_query(F.data == "list")
async def back_list(cb: types.CallbackQuery):
    searches = await db.get_user_searches(cb.from_user.id)
    await cb.message.edit_text("📋 <b>Твои поиски:</b>",
                               parse_mode="HTML",
                               reply_markup=kb_searches(searches))


# ══════════════════════════════════════════
# Поиск по фото
# ══════════════════════════════════════════

@dp.message(F.text == "🖼 Найти по фото")
async def photo_prompt(message: types.Message, state: FSMContext):
    await state.set_state(PhotoSearch.waiting)
    await message.answer(
        "📸 Отправь фото вещи — найду похожие объявления на Goofish через AI!\n\n"
        "<i>Лучше работает с чёткими фото на белом фоне.</i>",
        parse_mode="HTML"
    )

@dp.message(PhotoSearch.waiting, F.photo)
async def photo_search(message: types.Message, state: FSMContext):
    await state.clear()
    msg = await message.answer("🔍 Ищу похожие объявления...")
    file = await bot.get_file(message.photo[-1].file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    embedding = await image_ai.get_embedding_from_url(url)
    ads = await parser.search_by_embedding(embedding, limit=10)
    await msg.delete()
    if not ads:
        await message.answer("😔 Ничего похожего не нашлось. Попробуй другое фото.")
        return
    await message.answer(f"✨ <b>Нашёл {len(ads)} похожих объявлений:</b>", parse_mode="HTML")
    for ad in ads[:5]:
        await send_ad(message.chat.id, ad, similarity=ad.get("similarity"))
        await asyncio.sleep(0.3)


# ══════════════════════════════════════════
# Отправка объявления
# ══════════════════════════════════════════

async def send_ad(chat_id: int, ad: dict, search_name: str = None,
                  similarity: float = None):
    price_cny = ad.get("price", 0)
    price_rub = int(price_cny * 13.5)  # ~курс, обновляй при необходимости

    title_ru = await translator.translate(ad.get("title", ""))
    desc_ru = ""
    if ad.get("description"):
        desc_ru = await translator.translate(ad["description"][:200])

    sim_str = f"\n🤖 Схожесть: {similarity:.0%}" if similarity else ""
    search_str = f"🔍 <b>{search_name}</b>\n" if search_name else ""
    desc_str = f"\n📄 {desc_ru}" if desc_ru else ""
    date_str = f"\n🕐 {ad.get('date', '')}" if ad.get("date") else ""

    text = (
        f"{search_str}"
        f"📦 <b>{title_ru}</b>\n"
        f"💰 {price_cny}¥  (~{price_rub:,}₽)\n"
        f"👤 {ad.get('seller', '')}"
        f"{desc_str}"
        f"{date_str}"
        f"{sim_str}\n"
        f"🔗 <a href='{ad.get('url', '')}'>Открыть на Goofish</a>"
    ).replace(",", " ")

    try:
        if ad.get("image_url"):
            await bot.send_photo(chat_id=chat_id, photo=ad["image_url"],
                                 caption=text, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception as e:
        log.error(f"send_ad error: {e}")
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception:
            pass


# ══════════════════════════════════════════
# Фоновый мониторинг
# ══════════════════════════════════════════

async def monitor():
    log.info("🟢 Monitor started")
    while True:
        try:
            searches = await db.get_active_searches()
            now = datetime.utcnow()

            for s in searches:
                from datetime import timedelta
                last = datetime.fromisoformat(s["last_checked"])
                if now - last < timedelta(minutes=s["interval_minutes"]):
                    continue

                tags = json.loads(s["tags"])
                log.info(f"Checking #{s['id']} «{s['name']}»: {tags}")

                ads = await parser.search_all_tags(
                    tags=tags,
                    price_min=s["price_min"],
                    price_max=s["price_max"],
                )

                embedding = None
                if s["image_embedding"]:
                    embedding = json.loads(s["image_embedding"])

                new_count = 0
                for ad in ads:
                    is_new = await db.mark_seen(s["id"], ad["id"])
                    if not is_new:
                        continue

                    if embedding and ad.get("image_url"):
                        sim = await image_ai.compare_url(embedding, ad["image_url"])
                        if sim < 0.25:
                            continue
                        ad["similarity"] = sim

                    await send_ad(s["user_id"], ad, search_name=s["name"])
                    new_count += 1
                    await asyncio.sleep(0.5)

                await db.update_checked(s["id"])
                if new_count:
                    log.info(f"  → {new_count} new ads sent")

        except Exception as e:
            log.error(f"Monitor error: {e}")

        await asyncio.sleep(60)


# ══════════════════════════════════════════
# Main
# ══════════════════════════════════════════

async def main():
    await db.init()
    asyncio.create_task(monitor())
    log.info("🤖 Bot polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
