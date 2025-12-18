import os
import json
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8393121507:AAF5l5kd4xmY4FLnMJ_D-2C6PaA9QAhAQW4").strip()

# Isi admin yang mau nerima bukti (PAKAI ID angka, bukan username)
ADMIN_IDS = [5504473114, 123456789]  # ganti sesuai kebutuhan

# Foto QRIS static kamu (png/jpg)
QRIS_IMAGE_PATH = os.getenv("QRIS_IMAGE_PATH", "qris.png")

# Penyimpanan ringan (biar approval bisa mapping ke user)
DATA_FILE = os.getenv("DATA_FILE", "payments.json")


def load_data():
    if not os.path.exists(DATA_FILE):
        return {"pending": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ketik /daftar buat ambil QRIS, habis bayar kirim bukti foto ke sini."
    )


async def daftar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    caption = (
        "**PAYMENT TURNAMEN**\n\n"
        "Silakan lakukan pembayaran via salah satu metode di bawah:\n\n"
        "🔹 **QRIS**\n"
        "_(scan QR di atas)_\n\n"
        "🔹 **DANA**\n"
        "`08xxxxxxxxxx`\n\n"
        "🔹 **BANK 1 (BCA)**\n"
        "`1234567890` a/n `Nama Kamu`\n\n"
        "🔹 **BANK 2 (BRI)**\n"
        "`0987654321` a/n `Nama Kamu`\n\n"
        "Setelah bayar, **kirim bukti foto ke bot ini**.\n"
        "_Bukti akan diteruskan ke admin untuk verifikasi._"
    )

    if os.path.exists(QRIS_IMAGE_PATH):
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=open(QRIS_IMAGE_PATH, "rb"),
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "QRIS image belum ada. Upload file qris.png ke folder bot."
        )



async def handle_proof_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user

    # Ambil foto resolusi tertinggi
    photo = msg.photo[-1]
    file_id = photo.file_id

    # Buat payment_id sederhana
    payment_id = f"{user.id}_{int(msg.date.timestamp())}"

    # Simpan pending
    data = load_data()
    data["pending"][payment_id] = {
        "user_id": user.id,
        "chat_id": msg.chat_id,
        "username": user.username,
        "name": user.full_name,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "status": "PENDING",
    }
    save_data(data)

    # Tombol admin
    kb = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Approve", callback_data=f"pay:ok:{payment_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"pay:no:{payment_id}"),
        ]]
    )

    caption = (
        f"🧾 **BUKTI PEMBAYARAN MASUK**\n"
        f"- Nama: {user.full_name}\n"
        f"- Username: @{user.username}" if user.username else f"- Username: (tidak ada)\n"
    )
    caption += f"\n- User ID: `{user.id}`\n- Payment ID: `{payment_id}`"

    # Kirim ke semua admin
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=file_id,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb,
            )
        except Exception as e:
            # Kalau admin belum pernah chat bot, pengiriman bisa gagal
            print(f"Failed send to admin {admin_id}: {e}")

    await msg.reply_text(
        "Oke, bukti udah kekirim ke admin. Tunggu verifikasi ya."
    )


async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    try:
        _, decision, payment_id = q.data.split(":", 2)
    except ValueError:
        return

    data = load_data()
    item = data["pending"].get(payment_id)
    if not item:
        await q.edit_message_caption(
            caption=(q.message.caption or "") + "\n\n⚠️ Status: data tidak ditemukan / sudah diproses."
        )
        return

    user_chat_id = item["chat_id"]
    user_id = item["user_id"]

    if decision == "ok":
        item["status"] = "APPROVED"
        save_data(data)

        # notif user
        await context.bot.send_message(
            chat_id=user_chat_id,
            text="✅ Pembayaran kamu sudah diverifikasi. Kamu resmi masuk peserta."
        )

        # update pesan admin
        await q.edit_message_caption(
            caption=(q.message.caption or "") + "\n\n✅ Status: APPROVED"
        )

    elif decision == "no":
        item["status"] = "REJECTED"
        save_data(data)

        await context.bot.send_message(
            chat_id=user_chat_id,
            text="❌ Bukti kamu ditolak admin. Cek lagi pembayaran/nominal, lalu kirim ulang bukti yang jelas."
        )
        await q.edit_message_caption(
            caption=(q.message.caption or "") + "\n\n❌ Status: REJECTED"
        )


def main():
    if not BOT_TOKEN:
        raise SystemExit("ENV BOT_TOKEN belum diisi.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("daftar", daftar))

    # Bukti pembayaran: foto
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_proof_photo))

    # Tombol admin approve/reject
    app.add_handler(CallbackQueryHandler(admin_decision, pattern=r"^pay:(ok|no):"))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
