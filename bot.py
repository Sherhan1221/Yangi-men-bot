import asyncio
import logging
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
CARD_NUMBER = os.getenv("CARD_NUMBER", "0000 0000 0000 0000")
CARD_HOLDER = os.getenv("CARD_HOLDER", "F.I.SH.")
COURSE_PRICE = os.getenv("COURSE_PRICE", "350 000 so'm / oy")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", "8080"))

logging.basicConfig(level=logging.INFO)

DB_PATH = "registrations.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def save_registration(user_id, username, full_name):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO registrations (user_id, username, full_name, created_at) VALUES (?, ?, ?, ?)",
        (user_id, username, full_name, datetime.now().isoformat()),
    )
    conn.commit()
    reg_id = cur.lastrowid
    conn.close()
    return reg_id


def update_status(reg_id, status):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE registrations SET status = ? WHERE id = ?", (status, reg_id))
    conn.commit()
    conn.close()


router = Router()


class Reg(StatesGroup):
    waiting_receipt = State()


def paid_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="To'lovni amalga oshirish", callback_data="paid_confirm")]
        ]
    )


def admin_keyboard(reg_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tekshirildi", callback_data=f"approve_{reg_id}"),
                InlineKeyboardButton(text="❌ Muammo bor", callback_data=f"reject_{reg_id}"),
            ]
        ]
    )


# ---- /start сразу показывает оплату, без лишнего экрана ----
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    text = (
        "🌸 <b>YANGI MEN</b>\n\n"
        f"{COURSE_PRICE}\n\n"
        f"Karta:\n{CARD_NUMBER}\n\n"
        f"Karta egasi:\n{CARD_HOLDER}"
    )
    await message.answer(text, reply_markup=paid_keyboard(), parse_mode="HTML")


# ---- ЧЕК (любой формат) ----
@router.callback_query(F.data == "paid_confirm")
async def ask_receipt(callback: CallbackQuery, state: FSMContext):
    text = (
        "To'lov qilganingiz uchun rahmat! 💛\n\n"
        "Chekni tashlashni unutmang — rasm, PDF yoki matn ko'rinishida, qanday bo'lsa ham yuboring."
    )
    await callback.message.answer(text)
    await state.set_state(Reg.waiting_receipt)
    await callback.answer()


@router.message(Reg.waiting_receipt)
async def get_receipt(message: Message, state: FSMContext, bot: Bot):
    user = message.from_user
    reg_id = save_registration(user.id, user.username or "", user.full_name)

    info = (
        f"🔔 YANGI MEN — YANGI TO'LOV\n\n"
        f"👤 Ism: {user.full_name}\n"
        f"🔗 Username: @{user.username if user.username else '—'}\n"
        f"🆔 ID: {user.id}\n"
        f"💰 Summa: {COURSE_PRICE}\n"
        f"#{reg_id}"
    )

    await bot.forward_message(
        chat_id=ADMIN_CHAT_ID, from_chat_id=message.chat.id, message_id=message.message_id
    )
    await bot.send_message(chat_id=ADMIN_CHAT_ID, text=info, reply_markup=admin_keyboard(reg_id))

    await message.answer(
        "Rahmat! Ma'lumot administratorga yuborildi.\n"
        "Tez orada tasdiqlaymiz va siz bilan bog'lanamiz."
    )
    await state.clear()


# ---- АДМИН: только отметка для учёта ----
@router.callback_query(F.data.startswith("approve_"))
async def approve_reg(callback: CallbackQuery):
    reg_id = int(callback.data.split("_")[1])
    update_status(reg_id, "approved")
    await callback.message.edit_text(callback.message.text + "\n\n✅ TEKSHIRILDI")
    await callback.answer("Belgilandi")


@router.callback_query(F.data.startswith("reject_"))
async def reject_reg(callback: CallbackQuery):
    reg_id = int(callback.data.split("_")[1])
    update_status(reg_id, "rejected")
    await callback.message.edit_text(callback.message.text + "\n\n❌ MUAMMO BOR")
    await callback.answer("Belgilandi")


async def on_startup(bot: Bot):
    if WEBHOOK_URL:
        await bot.set_webhook(f"{WEBHOOK_URL}{WEBHOOK_PATH}")
        logging.info("Webhook set to %s%s", WEBHOOK_URL, WEBHOOK_PATH)
    else:
        logging.warning("WEBHOOK_URL not set — bot will not receive updates until it is configured.")


def main():
    init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    dp.startup.register(on_startup)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
