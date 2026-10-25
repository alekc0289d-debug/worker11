"""Chat tizimi — real-time xabarlar."""

import logging
from datetime import datetime, timezone

from firebase_client import db

log = logging.getLogger("chat")


def send_message(user_id: str, class_id: str, text: str) -> dict:
    """Xabar yuborish."""
    if not text or not text.strip():
        return {"ok": False, "message": "Bo'sh xabar"}

    text = text.strip()[:1000]

    c = db()
    udoc = c.collection("users").document(user_id).get()
    author_name = udoc.to_dict().get("fullName", "Foydalanuvchi") if udoc.exists else "Foydalanuvchi"

    now = datetime.now(timezone.utc)
    ref = c.collection("chat_messages").document()
    ref.set({
        "userId": user_id,
        "authorName": author_name,
        "classId": class_id or "",
        "text": text,
        "createdAt": now,
    })

    return {"ok": True, "messageId": ref.id}


def list_messages(class_id: str = "", limit: int = 50) -> list:
    """Sinf bo'yicha xabarlar (eng yangi oxirida)."""
    c = db()
    q = c.collection("chat_messages")
    if class_id:
        q = q.where("classId", "==", class_id)

    docs = list(q.stream())
    items = [{"id": d.id, **d.to_dict()} for d in docs]
    items.sort(key=lambda x: x.get("createdAt") or datetime.min.replace(tzinfo=timezone.utc))
    return items[-limit:]


def delete_message(message_id: str, by_role: str) -> dict:
    """Xabarni o'chirish (class_admin va yuqori)."""
    if by_role not in ("class_admin", "director", "bosh_admin"):
        return {"ok": False, "message": "Ruxsat yo'q"}
    db().collection("chat_messages").document(message_id).delete()
    return {"ok": True}