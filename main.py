import os
import json
import csv
import secrets
from datetime import datetime
from typing import Dict, Any, Optional

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
    ConversationHandler,
    ContextTypes,
    filters,
)

# =========================
# ENV / CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8393121507:AAF5l5kd4xmY4FLnMJ_D-2C6PaA9QAhAQW4").strip()

# Admin yang boleh approve/reject & akses command admin
ADMIN_IDS = [
    int(x) for x in os.getenv("ADMIN_IDS", "5504473114").split(",")
    if x.strip().lstrip("-").isdigit()
]

# Grup panitia tempat bukti dikirim (wajib supergroup, contoh: -1001234567890)
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "-1003393190565"))

# QRIS pakai link gambar (HARUS direct image .png/.jpg)
QRIS_IMAGE_URL = os.getenv("QRIS_IMAGE_URL", "https://ibb.co.com/ynZVW1Mk").strip()

# Payment info
DANA_NUMBER = os.getenv("DANA_NUMBER", "08xxxxxxxxxx").strip()
BANK1_NAME = os.getenv("BANK1_NAME", "BANK 1").strip()
BANK1_REK = os.getenv("BANK1_REK", "1234567890").strip()
BANK1_AN = os.getenv("BANK1_AN", "Nama Kamu").strip()

BANK2_NAME = os.getenv("BANK2_NAME", "BANK 2").strip()
BANK2_REK = os.getenv("BANK2_REK", "0987654321").strip()
BANK2_AN = os.getenv("BANK2_AN", "Nama Kamu").strip()

DATA_FILE = os.getenv("DATA_FILE", "turnamen_data.json").strip()

# =========================
# REG FORM STATES
# =========================
ASK_NAME, ASK_WA, CONFIRM = range(3)

# =========================
# STORAGE
# =========================
def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "pending": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            d.setdefault("users", {})
            d.setdefault("pending", {})
            return d
    except Exception:
        return {"users": {}, "pending": {}}


def save_data(data: Dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def now_utc() -> str:
    return datetime.utcnow().isoformat() + "Z"


def gen_ticket() -> str:
    # contoh: UNO-9K3F7A
    return "UNO-" + secrets.token_hex(3).upper()


def get_user_record(data: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    return data["users"].get(str(user_id), {})


def set_user_record(data: Dict[str, Any], user_id: int, record: Dict[str, Any]) -> None:
    data["users"][str(user_id)] = record


# =========================
# UI HELPERS
# =========================
def payment_caption(ticket: str) -> str:
    return (
        "**FORMAT QRIS**\n\n"
        f"🎟️ **Ticket:** `{ticket}`\n\n"
        "_(foto QRIS di atas)_\n\n"
        f"**Nomor DANA:** `{DANA_NUMBER}`\n"
        f"**{BANK1_NAME}:** `{BANK1_REK}` a/n `{BANK1_AN}`\n"
        f"**{BANK2_NAME}:** `{BANK2_REK}` a/n `{BANK2_AN}`\n\n"
        "Setelah bayar, **kirim bukti foto** ke bot ini.\n"
        "_Bukti akan masuk grup panitia untuk verifikasi._"
    )


# =========================
# COMMANDS (USER)
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ketik /daftar buat pendaftaran.\n"
        "Ketik /status buat cek status kamu."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = load_data()
    u = get_user_record(data, user_id)

    if not u:
        return await update.message.reply_text("Kamu belum daftar. Ketik /daftar dulu.")

    st = u.get("status", "UNKNOWN")
    ticket = u.get("ticket", "-")
    name = u.get("name", "-")
    wa = u.get("wa", "-")

    pretty = {
        "FORM": "📄 Lagi isi form",
        "WAIT_PROOF": "💳 Menunggu bukti pembayaran",
        "PENDING": "⏳ Bukti sudah dikirim, nunggu verifikasi",
        "APPROVED": "✅ LUNAS / Terverifikasi",
        "REJECTED": "❌ Ditolak (kirim bukti ulang)",
    }.get(st, st)

    await update.message.reply_text(
        f"**Status kamu**\n"
        f"- Ticket: `{ticket}`\n"
        f"- Nama/IGN: {name}\n"
        f"- WA: `{wa}`\n"
        f"- Status: {pretty}",
        parse_mode=ParseMode.MARKDOWN,
    )


# =========================
# REGISTRATION FORM
# =========================
async def daftar_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = load_data()
    u = get_user_record(data, user_id)

    # Kalau sudah approved, jangan daftar ulang
    if u and u.get("status") == "APPROVED":
        await update.message.reply_text("Kamu udah LUNAS/terverifikasi. Gak perlu daftar ulang.")
        return ConversationHandler.END

    # Kalau pending, jangan daftar ulang
    if u and u.get("status") == "PENDING":
        await update.message.reply_text("Bukti kamu lagi diproses panitia. Tunggu dulu ya.")
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["reg"] = {"status": "FORM"}
    await update.message.reply_text("Isi **Nama/IGN** kamu:")
    return ASK_NAME


async def daftar_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if len(name) < 2:
        await update.message.reply_text("Nama/IGN kependekan. Coba lagi:")
        return ASK_NAME

    context.user_data["reg"]["name"] = name
    await update.message.reply_text("Masukin **No WA** kamu (contoh: 08xxxxxxxxxx):")
    return ASK_WA


async def daftar_wa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wa = (update.message.text or "").strip().replace(" ", "")
    # validasi ringan
    if not wa.startswith("08") or len(wa) < 9:
        await update.message.reply_text("Format WA kurang valid. Contoh: 08xxxxxxxxxx. Coba lagi:")
        return ASK_WA

    context.user_data["reg"]["wa"] = wa
    name = context.user_data["reg"]["name"]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Lanjut bayar", callback_data="reg:ok")],
        [InlineKeyboardButton("✏️ Ubah Nama/IGN", callback_data="reg:edit:name"),
         InlineKeyboardButton("✏️ Ubah WA", callback_data="reg:edit:wa")],
        [InlineKeyboardButton("❌ Batal", callback_data="reg:cancel")]
    ])

    await update.message.reply_text(
        f"Konfirmasi data kamu:\n"
        f"- Nama/IGN: {name}\n"
        f"- WA: {wa}\n\n"
        "Kalau sudah benar, klik **Lanjut bayar**.",
        reply_markup=kb,
    )
    return CONFIRM


async def reg_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    data = load_data()

    if q.data == "reg:cancel":
        await q.edit_message_text("Pendaftaran dibatalkan.")
        return ConversationHandler.END

    if q.data == "reg:edit:name":
        await q.edit_message_text("Oke, kirim ulang **Nama/IGN** kamu:")
        return ASK_NAME

    if q.data == "reg:edit:wa":
        await q.edit_message_text("Oke, kirim ulang **No WA** kamu (08xxxxxxxxxx):")
        return ASK_WA

    if q.data == "reg:ok":
        reg = context.user_data.get("reg", {})
        name = reg.get("name", "-")
        wa = reg.get("wa", "-")

        # buat / reuse ticket
        old = get_user_record(data, user_id)
        ticket = old.get("ticket") if old.get("ticket") else gen_ticket()

        record = {
            "user_id": user_id,
            "username": q.from_user.username or "",
            "name": name,
            "wa": wa,
            "ticket": ticket,
            "status": "WAIT_PROOF",
            "created_at": old.get("created_at", now_utc()),
            "updated_at": now_utc(),
        }
        set_user_record(data, user_id, record)
        save_data(data)

        # kirim QRIS
        cap = payment_caption(ticket)
        try:
            await context.bot.send_photo(
                chat_id=q.message.chat_id,
                photo=QRIS_IMAGE_URL,
                caption=cap,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text=cap + "\n\n⚠️ (QRIS image gagal dimuat. Pastikan link direct .png/.jpg)",
                parse_mode=ParseMode.MARKDOWN,
            )

        await q.edit_message_text("Oke, lanjut pembayaran. Habis bayar, kirim bukti foto ke bot ini.")
        return ConversationHandler.END

    return ConversationHandler.END


async def reg_cancel_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pendaftaran dibatalkan.")
    return ConversationHandler.END


# =========================
# PROOF HANDLING (ANTI-SPAM)
# =========================
async def handle_proof_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    user_id = user.id

    data = load_data()
    u = get_user_record(data, user_id)

    if not u:
        return await msg.reply_text("Kamu belum daftar. Ketik /daftar dulu.")

    st = u.get("status")

    # Anti spam bukti
    if st == "PENDING":
        return await msg.reply_text("Bukti kamu udah masuk antrian. Jangan spam, nanti panitia kesel.")
    if st == "APPROVED":
        return await msg.reply_text("Kamu udah terverifikasi. Santai.")
    if st not in ("WAIT_PROOF", "REJECTED"):
        return await msg.reply_text("Status kamu belum siap untuk kirim bukti. Ketik /status.")

    if not msg.photo:
        return

    photo = msg.photo[-1]
    file_id = photo.file_id

    ticket = u.get("ticket", gen_ticket())
    payment_id = f"{user_id}_{int(msg.date.timestamp())}"

    # set status pending
    u["status"] = "PENDING"
    u["updated_at"] = now_utc()
    set_user_record(data, user_id, u)

    # simpan pending detail (buat /pending dan approve)
    data["pending"][payment_id] = {
        "payment_id": payment_id,
        "ticket": ticket,
        "user_id": user_id,
        "chat_id": msg.chat_id,
        "username": user.username or "",
        "name": u.get("name", user.full_name or ""),
        "wa": u.get("wa", ""),
        "status": "PENDING",
        "created_at": now_utc(),
        "proof_file_id": file_id,
    }
    save_data(data)

    # kirim ke grup panitia
    kb = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Approve", callback_data=f"pay:ok:{payment_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"pay:no:{payment_id}"),
        ]]
    )

    uname = f"@{user.username}" if user.username else "(tidak ada)"
    cap = (
        "🧾 **BUKTI PEMBAYARAN MASUK**\n"
        f"- Ticket: `{ticket}`\n"
        f"- Nama/IGN: {u.get('name','-')}\n"
        f"- WA: `{u.get('wa','-')}`\n"
        f"- Username: {uname}\n"
        f"- User ID: `{user_id}`\n"
        f"- Payment ID: `{payment_id}`"
    )

    sent = False
    if ADMIN_GROUP_ID != -1000 and ADMIN_GROUP_ID != -100:
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_GROUP_ID,
                photo=file_id,
                caption=cap,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb,
            )
            sent = True
        except Exception as e:
            print(f"[WARN] gagal kirim ke ADMIN_GROUP_ID: {e}")

    # fallback ke admin PM kalau grup gagal
    if not sent:
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=file_id,
                    caption=cap + "\n\n⚠️ (fallback: grup panitia gagal)",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb,
                )
                sent = True
            except Exception as e:
                print(f"[WARN] gagal kirim ke admin {admin_id}: {e}")

    if sent:
        await msg.reply_text("Oke, bukti kamu udah masuk antrian panitia. Tinggal tunggu cap ‘LUNAS’ ya.")
    else:
        await msg.reply_text("Bukti kebaca, tapi gagal terkirim ke panitia. Pastikan ADMIN_GROUP_ID & admin sudah /start bot.")


# =========================
# ADMIN ACTIONS
# =========================
async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.answer("Kamu bukan admin.", show_alert=True)
        return

    try:
        _, decision, payment_id = q.data.split(":", 2)
    except ValueError:
        return

    data = load_data()
    p = data["pending"].get(payment_id)
    if not p:
        try:
            await q.edit_message_caption(caption=(q.message.caption or "") + "\n\n⚠️ Data pending tidak ditemukan / sudah diproses.")
        except Exception:
            pass
        return

    user_id = int(p["user_id"])
    user_chat_id = int(p["chat_id"])
    u = get_user_record(data, user_id)

    if not u:
        u = {
            "user_id": user_id,
            "ticket": p.get("ticket", "-"),
            "name": p.get("name", "-"),
            "wa": p.get("wa", "-"),
            "status": "PENDING",
            "created_at": p.get("created_at", now_utc()),
            "updated_at": now_utc(),
        }

    if decision == "ok":
        u["status"] = "APPROVED"
        u["updated_at"] = now_utc()
        set_user_record(data, user_id, u)
        p["status"] = "APPROVED"
        save_data(data)

        await context.bot.send_message(
            chat_id=user_chat_id,
            text=f"✅ Pembayaran kamu **TERVERIFIKASI**.\nTicket: `{u.get('ticket','-')}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        try:
            await q.edit_message_caption(caption=(q.message.caption or "") + "\n\n✅ Status: APPROVED")
        except Exception:
            pass

    elif decision == "no":
        u["status"] = "REJECTED"
        u["updated_at"] = now_utc()
        set_user_record(data, user_id, u)
        p["status"] = "REJECTED"
        save_data(data)

        await context.bot.send_message(
            chat_id=user_chat_id,
            text="❌ Bukti kamu **DITOLAK** panitia.\nKirim ulang bukti yang jelas ya.",
            parse_mode=ParseMode.MARKDOWN,
        )
        try:
            await q.edit_message_caption(caption=(q.message.caption or "") + "\n\n❌ Status: REJECTED")
        except Exception:
            pass


async def pending_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("Khusus admin.")

    data = load_data()
    pending = [p for p in data.get("pending", {}).values() if p.get("status") == "PENDING"]

    if not pending:
        return await update.message.reply_text("Pending kosong. Panitia lagi gabut.")

    lines = ["**DAFTAR PENDING**\n"]
    for p in sorted(pending, key=lambda x: x.get("created_at", "")):
        lines.append(
            f"- `{p.get('payment_id')}` | Ticket `{p.get('ticket')}` | {p.get('name')} | WA `{p.get('wa')}`"
        )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("Khusus admin.")

    data = load_data()
    users = list(data.get("users", {}).values())

    # export semua yang APPROVED dulu (biar rapi)
    approved = [u for u in users if u.get("status") == "APPROVED"]

    if not approved:
        return await update.message.reply_text("Belum ada yang APPROVED. CSV-nya masih sepi.")

    filename = "peserta_turnamen.csv"
    with open(filename, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticket", "name_ign", "wa", "user_id", "username", "status", "created_at", "updated_at"])
        for u in approved:
            w.writerow([
                u.get("ticket", ""),
                u.get("name", ""),
                u.get("wa", ""),
                u.get("user_id", ""),
                u.get("username", ""),
                u.get("status", ""),
                u.get("created_at", ""),
                u.get("updated_at", ""),
            ])

    await update.message.reply_document(
        document=open(filename, "rb"),
        filename=filename,
        caption="CSV peserta (status APPROVED)."
    )


# =========================
# MAIN
# =========================
def main():
    if not BOT_TOKEN:
        raise SystemExit("ENV BOT_TOKEN belum diisi.")

    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation form
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("daftar", daftar_entry)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, daftar_name)],
            ASK_WA: [MessageHandler(filters.TEXT & ~filters.COMMAND, daftar_wa)],
            CONFIRM: [CallbackQueryHandler(reg_confirm_cb, pattern=r"^reg:")],
        },
        fallbacks=[CommandHandler("cancel", reg_cancel_text)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(reg_conv)

    # proof photo
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_proof_photo))

    # admin callbacks approve/reject
    app.add_handler(CallbackQueryHandler(admin_decision, pattern=r"^pay:(ok|no):"))

    # admin commands
    app.add_handler(CommandHandler("pending", pending_list))
    app.add_handler(CommandHandler("export", export_csv))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
