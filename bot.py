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
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
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
            fio TEXT,
            phone TEXT,
            receipt_file_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def save_registration(user_id, username, fio, phone, receipt_file_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO registrations (user_id, username, fio, phone, receipt_file_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, username, fio, phone, receipt_file_id, datetime.now().isoformat()),
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
    waiting_fio = State()
    waiting_phone = State()
    waiting_receipt = State()


def join_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="YANGI MEN'GA QO'SHILISH", callback_data="join")]
        ]
    )


def paid_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ TO'LOV QILDIM", callback_data="paid_confirm")]
        ]
    )


def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 TELEFON RAQAMIMNI YUBORISH", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
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


# ---- LANDING ----
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "YANGI MEN dasturiga xush kelibsiz.",
        reply_markup=join_keyboard(),
    )


# ---- БЛОК 1: ОПЛАТА ----
@router.callback_query(F.data == "join")
async def show_payment(callback: CallbackQuery, state: FSMContext):
    text = (
        f"💳 YANGI MEN'GA QO'SHILISH\n\n"
        f"{COURSE_PRICE}\n\n"
        f"Karta:\n{CARD_NUMBER}\n\n"
        f"Karta egasi:\n{CARD_HOLDER}\n\n"
        f"To'lovni amalga oshirgach, chekni yuboring."
    )
    await callback.message.answer(text, reply_markup=paid_keyboard())
    await callback.answer()


# ---- БЛОК 2: ДАННЫЕ + ЧЕК ----
@router.callback_query(F.data == "paid_confirm")
async def ask_data(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "To'lovni tekshirish uchun ma'lumotlaringizni yuboring:\n\n👤 Ism va familiya"
    )
    await state.set_state(Reg.waiting_fio)
    await callback.answer()


@router.message(Reg.waiting_fio)
async def get_fio(message: Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await message.answer(
        "📱 Telefon raqam",
        reply_markup=phone_keyboard(),
    )
    await state.set_state(Reg.waiting_phone)


@router.message(Reg.waiting_phone, F.contact)
async def get_phone_contact(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await ask_receipt(message, state)


@router.message(Reg.waiting_phone, F.text)
async def get_phone_text(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await ask_receipt(message, state)


async def ask_receipt(message: Message, state: FSMContext):
    await message.answer(
        "📎 To'lov chekini yuboring (rasm yoki fayl):",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(Reg.waiting_receipt)


async def process_receipt(message: Message, state: FSMContext, bot: Bot, file_id: str, is_document: bool):
    data = await state.get_data()
    fio = data.get("fio")
    phone = data.get("phone")
    user = message.from_user

    reg_id = save_registration(user.id, user.username or "", fio, phone, file_id)

    caption = (
        f"🔔 YANGI MEN — YANGI TO'LOV\n\n"
        f"👤 Ism: {fio}\n"
        f"📱 Telefon: {phone}\n"
        f"💰 Summa: {COURSE_PRICE}\n"
        f"🔗 Username: @{user.username if user.username else '—'}\n"
        f"🆔 ID: {user.id}\n"
        f"#{reg_id}"
    )

    if is_document:
        await bot.send_document(
            chat_id=ADMIN_CHAT_ID, document=file_id, caption=caption, reply_markup=admin_keyboard(reg_id)
        )
    else:
        await bot.send_photo(
            chat_id=ADMIN_CHAT_ID, photo=file_id, caption=caption, reply_markup=admin_keyboard(reg_id)
        )

    await message.answer(
        "Rahmat! Ma'lumotlaringiz qabul qilindi.\n"
        "Administrator to'lovni tekshirgach, siz bilan bog'lanadi."
    )
    await state.clear()


@router.message(Reg.waiting_receipt, F.photo)
async def get_receipt_photo(message: Message, state: FSMContext, bot: Bot):
    await process_receipt(message, state, bot, message.photo[-1].file_id, is_document=False)


@router.message(Reg.waiting_receipt, F.document)
async def get_receipt_doc(message: Message, state: FSMContext, bot: Bot):
    await process_receipt(message, state, bot, message.document.file_id, is_document=True)


# ---- АДМИН: только отметка для учёта, никаких авто-сообщений участнице ----
@router.callback_query(F.data.startswith("approve_"))
async def approve_reg(callback: CallbackQuery):
    reg_id = int(callback.data.split("_")[1])
    update_status(reg_id, "approved")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ TEKSHIRILDI")
    await callback.answer("Belgilandi")


@router.callback_query(F.data.startswith("reject_"))
async def reject_reg(callback: CallbackQuery):
    reg_id = int(callback.data.split("_")[1])
    update_status(reg_id, "rejected")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ MUAMMO BOR")
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
