"""Kirish vaqtini nazorat qilish — 00:00–07:00 UZT bloklanadi (sozlanadi).

Bu modul ham API, ham bot tomonidan ishlatiladi.
"""

import logging
import os
from datetime import datetime, time, timezone, timedelta

log = logging.getLogger("access")

TASHKENT_TZ = timezone(timedelta(hours=5))

# Blok oralig'i
BLOCK_START = time(0, 0)   # 00:00
BLOCK_END = time(7, 0)     # 07:00


def _enabled() -> bool:
    """Blok yoqilganmi? ENV orqali boshqarish mumkin."""
    return os.getenv("ACCESS_WINDOW_ENABLED", "true").lower() in ("1", "true", "yes")


def now_tashkent() -> datetime:
    """Hozirgi vaqt Toshkent vaqtida."""
    return datetime.now(TASHKENT_TZ)


def is_within_block_hours() -> bool:
    """Hozir bloklangan vaqtmi?"""
    if not _enabled():
        return False
    t = now_tashkent().time()
    return BLOCK_START <= t < BLOCK_END


def is_access_allowed() -> bool:
    """Foydalanuvchi hozir kira oladimi?"""
    return not is_within_block_hours()


def access_denied_message() -> str:
    """Bloklangan paytda ko'rsatiladigan xabar."""
    now = now_tashkent()
    return (
        "🌙 Hozir dam olish vaqti (00:00–07:00)\n\n"
        f"🕐 Hozirgi vaqt: {now.strftime('%H:%M')} (Toshkent)\n"
        "⏰ Tizim ertalab soat 07:00 da qayta ochiladi\n\n"
        "Yaxshi dam oling! 😴"
    )


def allowed_hours_text() -> str:
    """Ish vaqti matni."""
    if not _enabled():
        return "♾️ Tizim 24/7 ishlaydi (blok o'chirilgan)"
    return "⏰ Tizim ish vaqti: 07:00 – 00:00 (Toshkent vaqti)"