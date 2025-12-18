import os
import json
from datetime import datetime
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================
# ENV / CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8393121507:AAF5l5kd4xmY4FLnMJ_D-2C6PaA9QAhAQW4").strip()

# Admin penerima bukti pembayaran (ISI ID ANGKA)
# contoh: [5504473114]
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "5504473114").split(",") if x.strip().isdigit()]

# QRIS pakai link gambar (HARUS direct image .png/.jpg)
QRIS_IMAGE_URL = os.getenv("QRIS_IMAGE_URL", "https://ibb.co.com/ynZVW1Mk").strip()

# Payment text
DANA_NUMBER = os.getenv("DANA_NUMBER", "08xxxxxxxxxx").strip()
BANK1_NAME = os.getenv("BANK1_NAME", "BANK 1").strip()
BANK1_REK = os.getenv("BANK1_REK", "1234567890").strip()
BANK1_AN = os.getenv("BANK1_AN", "Nama Kamu").strip()

BANK2_NAME = os.getenv("BANK2_NAME", "BANK 2").strip()
BANK2_REK = os.getenv("BANK2_REK", "0987654321").strip()
BANK2_AN = os.getenv("BANK2_AN", "Nama Kamu").strip()

# File data pending payment
DATA_FILE = os.getenv("DATA_FILE", "payments.json").strip()


# =========================
# STORAGE
# =========================
def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {"pending": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"pending": {}}


def save_data(data: Dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================
# HANDLERS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ketik /daftar buat ambil QRIS.\n"
        "Habis bayar, kirim bukti foto ke sini."
    )


async def daftar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    caption = (
        "**FORMAT QRIS**\n\n"
        "_(foto QRIS di atas)_\n\n"
        f"**Nomor DANA:** `{DANA_NUMBER}`\n"
        f"**{BANK1_NAME}:** `{BANK1_REK}` a/n `{BANK1_AN}`\n"
        f"**{BANK2_NAME}:** `{BANK2_REK}` a/n `{BANK2_AN}`\n\n"
        "Setelah bayar, **kirim bukti foto** ke bot ini.\n"
        "_Bukti akan diteruskan ke admin untuk verifikasi._"
    )

    # kirim QRIS via link gambar
    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=QRIS_IMAGE_URL,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        # fallback kalau link error
        await context.bot.send_message(
            chat_id=chat_id,
            text=caption + "\n\n⚠️ (QRIS image gagal dimuat dari link. Coba pakai link direct .png/.jpg)",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_proof_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    if not msg.photo:
        return

    # foto resolusi tertinggi
    photo = msg.photo[-1]
    file_id = photo.file_id

    # id transaksi sederhana
    payment_id = f"{user.id}_{int(msg.date.timestamp())}"

    data = load_data()
    data["pending"][payment_id] = {
        "user_id": user.id,
        "chat_id": msg.chat_id,
        "username": user.username or "",
        "name": user.full_name or "",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "status": "PENDING",
    }
    save_data(data)

    # tombol admin
    kb = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Approve", callback_data=f"pay:ok:{payment_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"pay:no:{payment_id}"),
        ]]
    )

    uname = f"@{user.username}" if user.username else "(tidak ada)"
    caption = (
        "🧾 **BUKTI PEMBAYARAN MASUK**\n"
        f"- Nama: {user.full_name}\n"
        f"- Username: {uname}\n"
        f"- User ID: `{user.id}`\n"
        f"- Payment ID: `{payment_id}`"
    )

    # kirim ke admin
    sent_any = False
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=file_id,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb,
            )
            sent_any = True
        except Exception as e:
            print(f"[WARN] gagal kirim ke admin {admin_id}: {e}")

    if sent_any:
        await msg.reply_text("Oke, bukti udah kekirim ke admin. Tunggu verifikasi ya.")
    else:
        await msg.reply_text(
            "Bukti kamu kebaca, tapi bot gagal kirim ke admin.\n"
            "Pastikan admin sudah /start ke bot dan ADMIN_IDS benar."
        )


async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    # keamanan: hanya admin yang boleh klik
    if q.from_user.id not in ADMIN_IDS:
        await q.answer("Kamu bukan admin.", show_alert=True)
        return

    try:
        _, decision, payment_id = q.data.split(":", 2)
    except ValueError:
        return

    data = load_data()
    item = data["pending"].get(payment_id)
    if not item:
        # data sudah diproses / hilang
        try:
            await q.edit_message_caption(
                caption=(q.message.caption or "") + "\n\n⚠️ Status: data tidak ditemukan / sudah diproses."
            )
        except Exception:
            pass
        return

    user_chat_id = item["chat_id"]

    if decision == "ok":
        item["status"] = "APPROVED"
        save_data(data)

        # notif user
        await context.bot.send_message(
            chat_id=user_chat_id,
            text="✅ Pembayaran kamu sudah diverifikasi. Kamu resmi masuk peserta."
        )

        # update caption admin
        try:
            await q.edit_message_caption(
                caption=(q.message.caption or "") + "\n\n✅ Status: APPROVED"
            )
        except Exception:
            pass

    elif decision == "no":
        item["status"] = "REJECTED"
        save_data(data)

        await context.bot.send_message(
            chat_id=user_chat_id,
            text="❌ Bukti kamu ditolak admin. Cek lagi pembayaran/nominal, lalu kirim ulang bukti yang jelas."
        )

        try:
            await q.edit_message_caption(
                caption=(q.message.caption or "") + "\n\n❌ Status: REJECTED"
            )
        except Exception:
            pass


# =========================
# MAIN
# =========================
def main():
    if not BOT_TOKEN:
        raise SystemExit("ENV BOT_TOKEN belum diisi.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("daftar", daftar))

    # bukti pembayaran (foto)
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_proof_photo))

    # approve/reject
    app.add_handler(CallbackQueryHandler(admin_decision, pattern=r"^pay:(ok|no):"))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
