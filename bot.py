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
    waiting_all = State()


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


# ---- БЛОК 2: ВСЁ ОДНИМ СООБЩЕНИЕМ ----
@router.callback_query(F.data == "paid_confirm")
async def ask_data(callback: CallbackQuery, state: FSMContext):
    text = (
        "To'lov chekini yuborish uchun:\n\n"
        "1️⃣ 📎 (skrepka) belgisini bosing\n"
        "2️⃣ Chek rasmini tanlang\n"
        "3️⃣ Rasm ostidagi \"Izoh yozish\" (yoki \"Caption\") maydoniga bosing\n"
        "4️⃣ Shu yerga ism-familiya va telefon raqamingizni yozing\n"
        "5️⃣ Yuboring ➡️\n\n"
        "Yozish namunasi (2 qatorda):\n"
        "Anora Karimova\n"
        "+998 90 123 45 67\n\n"
        "❗️Rasmni matn bilan BIRGA, bitta xabar qilib yuboring — alohida emas."
    )
    await callback.message.answer(text)
    await state.set_state(Reg.waiting_all)
    await callback.answer()


def parse_caption(caption: str | None):
    if not caption:
        return None, None
    lines = [line.strip() for line in caption.strip().split("\n") if line.strip()]
    fio = lines[0] if len(lines) >= 1 else None
    phone = lines[1] if len(lines) >= 2 else None
    return fio, phone


async def process_receipt(message: Message, state: FSMContext, bot: Bot, file_id: str, is_document: bool):
    caption = message.caption
    fio, phone = parse_caption(caption)

    if not fio or not phone:
        await message.answer(
            "Iltimos, rasmning tavsifiga (caption) ikkita qatorda yozing:\n\n"
            "Ism Familiya\n"
            "Telefon raqam\n\n"
            "Va chekni shu tavsif bilan qayta yuboring."
        )
        return

    user = message.from_user
    reg_id = save_registration(user.id, user.username or "", fio, phone, file_id)

    admin_caption = (
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
            chat_id=ADMIN_CHAT_ID, document=file_id, caption=admin_caption, reply_markup=admin_keyboard(reg_id)
        )
    else:
        await bot.send_photo(
            chat_id=ADMIN_CHAT_ID, photo=file_id, caption=admin_caption, reply_markup=admin_keyboard(reg_id)
        )

    await message.answer(
        "Rahmat! Ma'lumotlaringiz qabul qilindi.\n"
        "Administrator to'lovni tekshirgach, siz bilan bog'lanadi."
    )
    await state.clear()


@router.message(Reg.waiting_all, F.photo)
async def get_receipt_photo(message: Message, state: FSMContext, bot: Bot):
    await process_receipt(message, state, bot, message.photo[-1].file_id, is_document=False)


@router.message(Reg.waiting_all, F.document)
async def get_receipt_doc(message: Message, state: FSMContext, bot: Bot):
    await process_receipt(message, state, bot, message.document.file_id, is_document=True)


@router.message(Reg.waiting_all)
async def wrong_input(message: Message):
    await message.answer(
        "Iltimos, to'lov chekini RASM sifatida yuboring, tavsifiga (caption) ism-familiya "
        "va telefon raqamingizni yozib."
    )


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
