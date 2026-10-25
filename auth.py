"""Foydalanuvchi autentifikatsiyasi — login/parol (PBKDF2)."""
from crypto import decrypt
import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from firebase_client import db

log = logging.getLogger("auth")


def clean_phone(p: str) -> str:
    """Telefon raqamni tozalash: '+998 90 000 00 01' → '+998900000001'."""
    if not p:
        return ""
    cleaned = re.sub(r"[^\d+]", "", p.strip())
    if cleaned.startswith("+"):
        cleaned = "+" + cleaned[1:].replace("+", "")
    else:
        cleaned = "+" + cleaned.replace("+", "")
    return cleaned


def _hash_password(password: str) -> str:
    """Parolni hashlash (PBKDF2-SHA256, 100k iteratsiya)."""
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"pbkdf2_sha256${salt}${h.hex()}"


def _verify_password(password: str, hashed: str) -> bool:
    """Parolni tekshirish."""
    try:
        algo, salt, h = hashed.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 100_000
        )
        return secrets.compare_digest(calc.hex(), h)
    except Exception:
        return False


def user_exists_by_phone(phone: str) -> bool:
    """Telefon raqam bazada bormi?"""
    p = clean_phone(phone)
    if not p:
        return False
    users = list(
        db().collection("users").where("phone", "==", p).limit(1).stream()
    )
    return len(users) > 0


def create_user(
    user_id: str,
    phone: str,
    password: str,
    full_name: str,
    role: str = "student",
    class_id: str = "",
) -> dict:
    """Yangi foydalanuvchi yaratish."""
    c = db()
    now = datetime.now(timezone.utc)
    clean_p = clean_phone(phone)

    existing = list(
        c.collection("users").where("phone", "==", clean_p).limit(1).stream()
    )
    if existing:
        return {"ok": False, "message": "Bu telefon allaqachon ro'yxatdan o'tgan"}

    c.collection("users").document(user_id).set({
        "fullName": full_name,
        "phone": clean_p,
        "passwordHash": _hash_password(password),
        "role": role,
        "classId": class_id,
        "status": "active",
        "totalScore": 0,
        "timezone": "Asia/Tashkent",
        "createdAt": now,
        "updatedAt": now,
    }, merge=True)

    log.info("[AUTH] Yangi user: %s (%s)", full_name, clean_p)
    return {"ok": True, "userId": user_id}


def login(phone: str, password: str) -> dict:
    """Login: telefon + emaktab parol (yoki admin parol)."""
    c = db()
    clean_p = clean_phone(phone)

    log.info("[AUTH] Login: raw=%r cleaned=%r", phone, clean_p)

    users = list(
        c.collection("users").where("phone", "==", clean_p).limit(1).stream()
    )

    if not users:
        for u in c.collection("users").stream():
            d = u.to_dict()
            if clean_phone(d.get("phone", "")) == clean_p:
                users = [u]
                break

    if not users:
        return {"ok": False, "message": "Login yoki parol xato"}

    doc = users[0]
    data = doc.to_dict()

    # ===== PAROLNI TEKSHIRISH =====
    # 1. Adminlar (bosh_admin, director, teacher, class_admin) uchun — passwordHash
    # 2. O'quvchilar uchun — emaktab_creds dagi parol
    
    authenticated = False

    # Admin paroli
    if data.get("passwordHash"):
        if _verify_password(password, data["passwordHash"]):
            authenticated = True

    # O'quvchi emaktab paroli
    if not authenticated:
        creds = c.collection("emaktab_creds").document(doc.id).get()
        if creds.exists:
            try:
                emaktab_pass = decrypt(creds.to_dict().get("passwordEncrypted", ""))
                if emaktab_pass and emaktab_pass == password:
                    authenticated = True
                    log.info("[AUTH] Emaktab parol mos keldi: %s", clean_p)
            except Exception as e:
                log.warning("[AUTH] Emaktab parol deshifrlash xato: %s", e)

    if not authenticated:
        log.warning("[AUTH] ❌ Parol xato: %s", clean_p)
        return {"ok": False, "message": "Login yoki parol xato"}

    if data.get("status") == "deleted":
        return {"ok": False, "message": "Hisob o'chirilgan"}

    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=30)

    c.collection("sessions").document(token).set({
        "userId": doc.id, "phone": clean_p,
        "expiresAt": expires, "createdAt": datetime.now(timezone.utc),
    })

    log.info("[AUTH] ✅ OK: %s | %s | role=%s",
             clean_p, data.get("fullName"), data.get("role"))

    return {
        "ok": True,
        "token": token,
        "user": {
            "id": doc.id,
            "fullName": data.get("fullName", ""),
            "role": data.get("role", "student"),
            "classId": data.get("classId", ""),
            "phone": clean_p,
            "totalScore": data.get("totalScore", 0),
        },
    }


def verify_token(token: str):
    """Session tokenni tekshirish."""
    if not token:
        return None
    doc = db().collection("sessions").document(token).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    expires = data.get("expiresAt")
    if expires:
        now = datetime.now(timezone.utc)
        exp = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
        if exp < now:
            db().collection("sessions").document(token).delete()
            return None
    return {"userId": data.get("userId"), "phone": data.get("phone")}


def logout(token: str) -> dict:
    """Tokenni o'chirish."""
    db().collection("sessions").document(token).delete()
    return {"ok": True}

def request_password_reset(phone: str) -> dict:
    """Parolni tiklash — Telegram bot orqali yangi parol yuborish."""
    import secrets as _secrets
    from telegram_sender import send_password_reset

    p = clean_phone(phone)
    if not p or len(p) < 12:
        return {"ok": False, "message": "Telefon raqam noto'g'ri"}

    c = db()
    users = list(c.collection("users").where("phone", "==", p).limit(1).stream())
    if not users:
        # Xavfsizlik uchun "topilmadi" deb aytmaymiz
        return {
            "ok": True,
            "sent": False,
            "message": "Agar bu raqam tizimda mavjud bo'lsa, botga xabar yuboriladi",
        }

    user_id = users[0].id
    ud = users[0].to_dict()

    # Bot users dan telegram ID olish
    telegram_id = ud.get("telegramId")
    if not telegram_id:
        # bot_users kolleksiyasidan qidirish
        bot_users = list(
            c.collection("bot_users")
            .where("userId", "==", user_id)
            .where("status", "==", "connected")
            .limit(1)
            .stream()
        )
        if bot_users:
            telegram_id = bot_users[0].to_dict().get("telegramId")

    if not telegram_id:
        return {
            "ok": False,
            "code": "BOT_NOT_CONNECTED",
            "message": "Avval Telegram botga ulanishingiz kerak",
            "botLink": "https://t.me/maktabim65_bot",
        }

    # Bot bloklanganmi?
    bot_doc = c.collection("bot_users").document(str(telegram_id)).get()
    if bot_doc.exists and bot_doc.to_dict().get("status") == "blocked":
        return {
            "ok": False,
            "code": "BOT_BLOCKED",
            "message": "Bot bloklangan. Iltimos, botni blokdan chiqaring",
            "botLink": "https://t.me/maktabim65_bot",
        }

    # Yangi parol
    new_pass = _secrets.token_hex(4)
    now = datetime.now(timezone.utc)

    # Parolni yangilash
    c.collection("users").document(user_id).set({
        "passwordHash": _hash_password(new_pass),
        "updatedAt": now,
    }, merge=True)

    # Log
    c.collection("password_resets").add({
        "userId": user_id,
        "phone": p,
        "fullName": ud.get("fullName", ""),
        "telegramId": telegram_id,
        "method": "telegram",
        "status": "sent",
        "createdAt": now,
    })

    # Botga yuborish
    send_result = send_password_reset(
        telegram_id,
        ud.get("fullName", "Foydalanuvchi"),
        new_pass,
    )

    if not send_result.get("ok"):
        return {
            "ok": False,
            "code": "SEND_FAILED",
            "message": f"Botga xabar yuborilmadi: {send_result.get('message')}",
        }

    log.info("[AUTH] ✅ Parol botga yuborildi: %s", p)

    return {
        "ok": True,
        "sent": True,
        "method": "telegram",
        "message": "Yangi parol Telegram botga yuborildi",
    }