"""Yangiliklar tizimi — Bosh admin va Direktor yozadi."""

import logging
from datetime import datetime, timezone

from firebase_client import db

log = logging.getLogger("news")

# Ruxsat etilgan rollar
ALLOWED_AUTHORS = {"bosh_admin", "director"}

# Toifalar
CATEGORIES = [
    "umumiy",     # Umumiy yangiliklar
    "talim",      # Ta'lim yangiliklari
    "tadbir",     # Tadbirlar
    "musobaqa",   # Musobaqalar
    "e'lon",      # E'lonlar
    "muvaffaqiyat",  # O'quvchilar muvaffaqiyati
]

# Muhimlik darajasi
PRIORITIES = ["past", "orta", "yuqori", "shoshilinch"]


# ============================================================
# YOZISH
# ============================================================
def create_news(
    author_id: str,
    author_role: str,
    title: str,
    content: str,
    category: str = "umumiy",
    priority: str = "orta",
    image_url: str = "",
    pinned: bool = False,
) -> dict:
    """Yangi yangilik yaratish (faqat Bosh admin va Direktor)."""
    if author_role not in ALLOWED_AUTHORS:
        return {"ok": False, "message": "Sizda yangilik yozish huquqi yo'q"}

    if not title or len(title.strip()) < 5:
        return {"ok": False, "message": "Sarlavha kamida 5 belgi"}

    if not content or len(content.strip()) < 20:
        return {"ok": False, "message": "Matn kamida 20 belgi"}

    if category not in CATEGORIES:
        category = "umumiy"
    if priority not in PRIORITIES:
        priority = "orta"

    c = db()
    now = datetime.now(timezone.utc)

    # Muallif ma'lumotlari
    author_doc = c.collection("users").document(author_id).get()
    author_name = (
        author_doc.to_dict().get("fullName", "Admin")
        if author_doc.exists else "Admin"
    )

    ref = c.collection("news").document()
    ref.set({
        "title": title.strip(),
        "content": content.strip(),
        "category": category,
        "priority": priority,
        "imageUrl": image_url,
        "pinned": pinned,
        "authorId": author_id,
        "authorRole": author_role,
        "authorName": author_name,
        "views": 0,
        "published": True,
        "createdAt": now,
        "updatedAt": now,
    })

    log.info("[NEWS] + %s (%s)", title[:40], author_name)
    return {"ok": True, "newsId": ref.id}


def update_news(
    news_id: str,
    author_id: str,
    author_role: str,
    **updates,
) -> dict:
    """Yangilikni tahrirlash (faqat muallif yoki Bosh admin)."""
    c = db()
    doc = c.collection("news").document(news_id).get()
    if not doc.exists:
        return {"ok": False, "message": "Yangilik topilmadi"}

    data = doc.to_dict()
    if data.get("authorId") != author_id and author_role != "bosh_admin":
        return {"ok": False, "message": "Faqat muallif tahrirlashi mumkin"}

    allowed = {"title", "content", "category", "priority", "imageUrl", "pinned", "published"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        return {"ok": False, "message": "O'zgartiriladigan maydon yo'q"}

    safe["updatedAt"] = datetime.now(timezone.utc)
    c.collection("news").document(news_id).set(safe, merge=True)

    return {"ok": True}


def delete_news(news_id: str, author_id: str, author_role: str) -> dict:
    """Yangilikni o'chirish."""
    c = db()
    doc = c.collection("news").document(news_id).get()
    if not doc.exists:
        return {"ok": False, "message": "Topilmadi"}

    data = doc.to_dict()
    if data.get("authorId") != author_id and author_role != "bosh_admin":
        return {"ok": False, "message": "Faqat muallif yoki Bosh admin"}

    c.collection("news").document(news_id).delete()
    log.info("[NEWS] o'chirildi: %s", news_id)
    return {"ok": True}


# ============================================================
# O'QISH
# ============================================================
def list_news(
    limit: int = 20,
    category: str = "",
    pinned_first: bool = True,
) -> list[dict]:
    """Yangiliklar ro'yxati."""
    c = db()
    q = c.collection("news").where("published", "==", True)
    if category:
        q = q.where("category", "==", category)

    docs = list(q.stream())
    items = [{"id": d.id, **d.to_dict()} for d in docs]

    # Saralash: pinned → priority → createdAt
    priority_order = {"shoshilinch": 0, "yuqori": 1, "orta": 2, "past": 3}

    def sort_key(n):
        pinned = 0 if n.get("pinned") else 1
        prio = priority_order.get(n.get("priority", "orta"), 2)
        created = n.get("createdAt")
        ts = created.timestamp() if created else 0
        return (pinned, prio, -ts)

    items.sort(key=sort_key)
    return items[:limit]


def get_news(news_id: str, increment_view: bool = True) -> dict | None:
    """Bitta yangilikni olish."""
    c = db()
    ref = c.collection("news").document(news_id)
    doc = ref.get()
    if not doc.exists:
        return None

    if increment_view:
        from firebase_admin import firestore as fs
        ref.set({"views": fs.Increment(1)}, merge=True)

    return {"id": doc.id, **doc.to_dict()}


def get_categories() -> list[dict]:
    """Toifalar ro'yxati (labels bilan)."""
    labels = {
        "umumiy": "📰 Umumiy",
        "talim": "🎓 Ta'lim",
        "tadbir": "🎉 Tadbir",
        "musobaqa": "🏆 Musobaqa",
        "e'lon": "📢 E'lon",
        "muvaffaqiyat": "⭐ Muvaffaqiyat",
    }
    return [
        {"value": c, "label": labels.get(c, c)}
        for c in CATEGORIES
    ]


def get_priorities() -> list[dict]:
    """Muhimlik darajalari."""
    labels = {
        "past": "Past",
        "orta": "O'rta",
        "yuqori": "Yuqori",
        "shoshilinch": "Shoshilinch",
    }
    return [
        {"value": p, "label": labels.get(p, p)}
        for p in PRIORITIES
    ]