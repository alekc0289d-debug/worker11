"""Tizim sozlamalari va foydalanuvchi xohishlari."""

import logging
from datetime import datetime, timezone

from firebase_client import db

log = logging.getLogger("settings")


# ============================================================
# GLOBAL SOZLAMALAR
# ============================================================
def get_settings() -> dict:
    """Barcha global sozlamalar (ro'yxatdan o'tish, sync)."""
    c = db()
    doc = c.collection("settings").document("global").get()
    if not doc.exists:
        return {
            "registrationEnabled": True,
            "registrationDisabledMessage": "",
            "syncEnabled": False,  # Direktor bosguncha o'chirilgan
        }
    d = doc.to_dict()
    return {
        "registrationEnabled": d.get("registrationEnabled", True),
        "registrationDisabledMessage": d.get("registrationDisabledMessage", ""),
        "syncEnabled": d.get("syncEnabled", False),
    }


def update_settings(payload: dict, by_role: str) -> dict:
    """Global sozlamalarni yangilash — faqat bosh_admin."""
    if by_role != "bosh_admin":
        return {"ok": False, "message": "Ruxsat yo'q"}

    allowed = {"registrationEnabled", "registrationDisabledMessage", "syncEnabled"}
    safe = {k: v for k, v in payload.items() if k in allowed}
    if not safe:
        return {"ok": False, "message": "O'zgartiriladigan maydon yo'q"}

    safe["updatedAt"] = datetime.now(timezone.utc)
    db().collection("settings").document("global").set(safe, merge=True)
    
    log.info("[SETTINGS] Global yangilandi: %s", safe)
    return {"ok": True}


def is_registration_enabled() -> bool:
    """Ro'yxatdan o'tish yoqilganmi?"""
    return get_settings().get("registrationEnabled", True)


# ============================================================
# FOYDALANUVCHI SOZLAMALARI (Theme, Lang)
# ============================================================
def get_user_preferences(user_id: str) -> dict:
    """Foydalanuvchining shaxsiy sozlamalari (mavzu, til)."""
    doc = db().collection("user_prefs").document(user_id).get()
    if not doc.exists:
        return {"theme": "light", "lang": "uz"}
    d = doc.to_dict()
    return {
        "theme": d.get("theme", "light"),
        "lang": d.get("lang", "uz"),
    }


def update_user_preferences(user_id: str, theme: str = "", lang: str = "") -> dict:
    """Foydalanuvchi sozlamalarini yangilash."""
    upd = {"updatedAt": datetime.now(timezone.utc)}
    
    if theme in ("light", "dark"):
        upd["theme"] = theme
    if lang in ("uz", "uz_cyrl", "ru", "en"):
        upd["lang"] = lang

    if len(upd) == 1:
        return {"ok": False, "message": "O'zgartirish uchun ma'lumot yo'q"}

    db().collection("user_prefs").document(user_id).set(upd, merge=True)
    return {"ok": True}