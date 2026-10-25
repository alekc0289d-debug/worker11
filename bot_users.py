"""Bot foydalanuvchilari — Telegram ID va holat boshqaruvi.

Sayt, bot va worker shu modul orqali Telegram ulanishlarini tekshiradi.
"""

import logging
from datetime import datetime, timezone

from firebase_client import db

log = logging.getLogger("bot_users")

# Holatlar
STATUS_CONNECTED = "connected"   # ✅ telefon tasdiqlangan
STATUS_PENDING = "pending"       # ⏳ ro'yxatdan o'tgan, botga ulanmagan
STATUS_BLOCKED = "blocked"       # 🚫 foydalanuvchi botni bloklagan


# ============================================================
# YOZISH
# ============================================================
def register_bot_user(
    telegram_id: int,
    user_id: str,
    full_name: str,
    phone: str,
    class_id: str = "",
):
    """Foydalanuvchi botga /start bosganda va telefon yuborganda."""
    c = db()
    now = datetime.now(timezone.utc)

    # bot_users/{telegramId}
    c.collection("bot_users").document(str(telegram_id)).set({
        "telegramId": telegram_id,
        "userId": user_id,
        "classId": class_id,
        "fullName": full_name,
        "phone": phone,
        "status": STATUS_CONNECTED,
        "connectedAt": now,
        "blockedAt": None,
        "lastSeen": now,
    }, merge=True)

    # users/{userId} — bot ma'lumotlarini ham yangilaymiz
    c.collection("users").document(user_id).set({
        "telegramId": telegram_id,
        "phone": phone,
        "fullName": full_name,
        "classId": class_id,
        "botStatus": STATUS_CONNECTED,
        "botConnectedAt": now,
        "botBlockedAt": None,
        "updatedAt": now,
    }, merge=True)

    log.info("[BOT_USER] +%s (%s) ulandi", telegram_id, full_name)
    return {"ok": True}


def touch_last_seen(telegram_id: int):
    """Har bir xabar uchun oxirgi ko'rilgan vaqtni yangilash."""
    db().collection("bot_users").document(str(telegram_id)).set({
        "lastSeen": datetime.now(timezone.utc),
    }, merge=True)


def mark_blocked(telegram_id: int):
    """Foydalanuvchi botni bloklagan (Telegram webhook orqali)."""
    c = db()
    now = datetime.now(timezone.utc)
    ref = c.collection("bot_users").document(str(telegram_id))
    doc = ref.get()
    if not doc.exists:
        return {"ok": False, "message": "Foydalanuvchi topilmadi"}

    data = doc.to_dict()
    user_id = data.get("userId")

    ref.set({
        "status": STATUS_BLOCKED,
        "blockedAt": now,
    }, merge=True)

    if user_id:
        c.collection("users").document(user_id).set({
            "botStatus": STATUS_BLOCKED,
            "botBlockedAt": now,
            "updatedAt": now,
        }, merge=True)

    log.warning("[BOT_USER] %s bloklandi", telegram_id)
    return {"ok": True}


def mark_unblocked(telegram_id: int):
    """Foydalanuvchi blokdan chiqdi."""
    c = db()
    now = datetime.now(timezone.utc)
    ref = c.collection("bot_users").document(str(telegram_id))
    doc = ref.get()
    if not doc.exists:
        return {"ok": False}

    data = doc.to_dict()
    user_id = data.get("userId")

    ref.set({
        "status": STATUS_CONNECTED,
        "blockedAt": None,
        "lastSeen": now,
    }, merge=True)

    if user_id:
        c.collection("users").document(user_id).set({
            "botStatus": STATUS_CONNECTED,
            "botBlockedAt": None,
            "updatedAt": now,
        }, merge=True)

    log.info("[BOT_USER] %s qayta ulandi", telegram_id)
    return {"ok": True}


def remove_user(telegram_id: int):
    """Foydalanuvchi /stop bosdi yoki hisobni o'chirdi."""
    c = db()
    ref = c.collection("bot_users").document(str(telegram_id))
    doc = ref.get()
    if not doc.exists:
        return {"ok": False}

    user_id = doc.to_dict().get("userId")
    ref.delete()

    if user_id:
        c.collection("users").document(user_id).set({
            "botStatus": STATUS_PENDING,
            "telegramId": None,
            "botConnectedAt": None,
            "updatedAt": datetime.now(timezone.utc),
        }, merge=True)

    return {"ok": True}


# ============================================================
# O'QISH
# ============================================================
def get_by_telegram(telegram_id: int) -> dict | None:
    """Telegram ID orqali foydalanuvchini olish."""
    doc = db().collection("bot_users").document(str(telegram_id)).get()
    if not doc.exists:
        return None
    return {"id": doc.id, **doc.to_dict()}


def get_by_user_id(user_id: str) -> dict | None:
    """user_id orqali Telegram ma'lumotlarini olish."""
    docs = list(
        db().collection("bot_users")
        .where("userId", "==", user_id)
        .limit(1)
        .stream()
    )
    if not docs:
        return None
    return {"id": docs[0].id, **docs[0].to_dict()}


def get_by_phone(phone: str) -> dict | None:
    """Telefon raqam orqali."""
    docs = list(
        db().collection("bot_users")
        .where("phone", "==", phone)
        .limit(1)
        .stream()
    )
    if not docs:
        return None
    return {"id": docs[0].id, **docs[0].to_dict()}


def is_connected(telegram_id: int) -> bool:
    """Foydalanuvchi botga ulangan va bloklanmaganmi?

    Bot middleware shu funksiyani chaqiradi.
    """
    user = get_by_telegram(telegram_id)
    if not user:
        return False
    return user.get("status") == STATUS_CONNECTED


def list_by_class(class_id: str, status: str | None = None) -> list[dict]:
    """Sinf bo'yicha foydalanuvchilar."""
    q = db().collection("bot_users").where("classId", "==", class_id)
    if status:
        q = q.where("status", "==", status)
    return [{"id": d.id, **d.to_dict()} for d in q.stream()]


def list_pending(class_id: str | None = None) -> list[dict]:
    """Botga ulanmaganlar — 13:00 ogohlantirish uchun."""
    q = db().collection("bot_users").where("status", "==", STATUS_PENDING)
    if class_id:
        q = q.where("classId", "==", class_id)
    return [{"id": d.id, **d.to_dict()} for d in q.stream()]


def list_blocked(class_id: str | None = None) -> list[dict]:
    """Botni bloklaganlar."""
    q = db().collection("bot_users").where("status", "==", STATUS_BLOCKED)
    if class_id:
        q = q.where("classId", "==", class_id)
    return [{"id": d.id, **d.to_dict()} for d in q.stream()]


def list_unregistered_students(class_id: str) -> list[dict]:
    """Sinfda ro'yxatdan o'tmagan o'quvchilar (bot_users da yo'q)."""
    c = db()
    all_students = list(
        c.collection("students").where("classId", "==", class_id).stream()
    )
    connected = set()
    for d in c.collection("bot_users").where("classId", "==", class_id).stream():
        connected.add(d.to_dict().get("userId"))

    unregistered = []
    for s in all_students:
        if s.id not in connected:
            unregistered.append({"studentId": s.id, **s.to_dict()})
    return unregistered


# ============================================================
# GURUHLAR
# ============================================================
def set_class_group(class_id: str, group_id: int, group_name: str, set_by: int):
    """Kichik admin sinf guruhini ulaydi (/setgroup orqali)."""
    db().collection("bot_groups").document(class_id).set({
        "classId": class_id,
        "groupId": group_id,
        "groupName": group_name,
        "setBy": set_by,
        "setAt": datetime.now(timezone.utc),
        "active": True,
    }, merge=True)
    log.info("[GROUP] %s → %s (%s)", class_id, group_id, group_name)
    return {"ok": True}


def get_class_group(class_id: str) -> dict | None:
    doc = db().collection("bot_groups").document(class_id).get()
    if not doc.exists:
        return None
    return {"id": doc.id, **doc.to_dict()}


def list_all_groups() -> list[dict]:
    return [
        {"id": d.id, **d.to_dict()}
        for d in db().collection("bot_groups").where("active", "==", True).stream()
    ]