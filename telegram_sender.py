"""Telegram Bot API orqali xabar yuborish."""

import logging
import os

import requests

log = logging.getLogger("telegram_sender")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_message(telegram_id: int, text: str, parse_mode: str = "HTML") -> dict:
    """Foydalanuvchiga xabar yuborish."""
    if not BOT_TOKEN:
        log.warning("BOT_TOKEN yo'q — xabar yuborilmadi")
        return {"ok": False, "message": "Bot token sozlanmagan"}

    if not telegram_id:
        return {"ok": False, "message": "Telegram ID yo'q"}

    try:
        res = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": int(telegram_id),
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=15,
        ).json()

        if res.get("ok"):
            log.info("[TG] Xabar yuborildi: %s", telegram_id)
            return {"ok": True}

        err = res.get("description", "Xatolik")
        log.warning("[TG] Xato: %s", err)
        return {"ok": False, "message": err}

    except Exception as e:
        log.exception("[TG] Kutilmagan xato")
        return {"ok": False, "message": str(e)}


def send_password_reset(telegram_id: int, full_name: str, new_password: str) -> dict:
    """Parol tiklash xabari."""
    text = (
        f"🔐 <b>Parolni tiklash</b>\n\n"
        f"Salom, <b>{full_name}</b>!\n\n"
        f"Sizning yangi parolingiz:\n"
        f"<code>{new_password}</code>\n\n"
        f"⚠️ <i>Bu parolni hech kimga bermang!</i>\n"
        f"Kirgandan keyin sozlamalarda o'zgartirib qo'ying.\n\n"
        f"🍂 <b>Maktabim+</b>"
    )
    return send_message(telegram_id, text)