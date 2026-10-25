"""Yangiliklar commentlari."""

import logging
from datetime import datetime, timezone

from firebase_client import db

log = logging.getLogger("comments")


def add_comment(news_id: str, user_id: str, text: str) -> dict:
    """Comment qo'shish."""
    if not text or len(text.strip()) < 2:
        return {"ok": False, "message": "Comment juda qisqa"}
    if len(text.strip()) > 500:
        return {"ok": False, "message": "Comment juda uzun"}

    c = db()
    udoc = c.collection("users").document(user_id).get()
    if not udoc.exists:
        return {"ok": False, "message": "Foydalanuvchi topilmadi"}

    ud = udoc.to_dict()
    now = datetime.now(timezone.utc)

    ref = c.collection("comments").document()
    ref.set({
        "newsId": news_id,
        "userId": user_id,
        "authorName": ud.get("fullName", ""),
        "authorRole": ud.get("role", "student"),
        "text": text.strip(),
        "createdAt": now,
        "likes": 0,
    })

    # Yangilik views hisoblagichi
    c.collection("news").document(news_id).set({
        "commentsCount": __import__("firebase_admin").firestore.Increment(1),
    }, merge=True)

    return {"ok": True, "commentId": ref.id}


def list_comments(news_id: str, limit: int = 50) -> list:
    """Commentlarni olish."""
    docs = list(
        db().collection("comments")
        .where("newsId", "==", news_id)
        .limit(limit)
        .stream()
    )
    items = [{"id": d.id, **d.to_dict()} for d in docs]
    items.sort(key=lambda x: x.get("createdAt") or datetime.min.replace(tzinfo=timezone.utc))
    return items


def delete_comment(comment_id: str, user_id: str, role: str) -> dict:
    """Commentni o'chirish."""
    c = db()
    doc = c.collection("comments").document(comment_id).get()
    if not doc.exists:
        return {"ok": False, "message": "Topilmadi"}

    d = doc.to_dict()
    if d.get("userId") != user_id and role not in ("bosh_admin", "director"):
        return {"ok": False, "message": "Ruxsat yo'q"}

    c.collection("comments").document(comment_id).delete()

    c.collection("news").document(d["newsId"]).set({
        "commentsCount": __import__("firebase_admin").firestore.Increment(-1),
    }, merge=True)

    return {"ok": True}