"""Bot holati — ulangan/ulanmagan/bloklaganlar statistikasi."""

import logging
from collections import defaultdict

from firebase_client import db

log = logging.getLogger("bot_status")


def get_bot_status_overview(class_id: str = "") -> dict:
    """
    Bot holati — barcha o'quvchilar bo'yicha.
    Holatlar: connected | pending | blocked | not_registered
    """
    c = db()

    students_q = c.collection("students")
    if class_id:
        students_q = students_q.where("classId", "==", class_id)
    students = list(students_q.stream())

    # Bot users
    bot_map = {}
    bot_q = c.collection("bot_users")
    if class_id:
        bot_q = bot_q.where("classId", "==", class_id)
    for b in bot_q.stream():
        bd = b.to_dict()
        bot_map[bd.get("userId")] = {
            "telegramId": bd.get("telegramId"),
            "phone": bd.get("phone"),
            "status": bd.get("status", "pending"),
            "connectedAt": bd.get("connectedAt"),
            "blockedAt": bd.get("blockedAt"),
        }

    by_status = defaultdict(list)
    total = len(students)

    for s in students:
        sd = s.to_dict()
        sid = s.id
        bot = bot_map.get(sid)

        item = {
            "studentId": sid,
            "fullName": sd.get("fullName", "—"),
            "classId": sd.get("classId", ""),
            "phone": sd.get("phone", ""),
            "motherPhone": sd.get("motherPhone", ""),
            "fatherPhone": sd.get("fatherPhone", ""),
            "telegramId": bot.get("telegramId") if bot else None,
        }

        if not bot:
            item["status"] = "not_registered"
            by_status["not_registered"].append(item)
        elif bot["status"] == "connected":
            item["status"] = "connected"
            item["connectedAt"] = bot.get("connectedAt")
            by_status["connected"].append(item)
        elif bot["status"] == "blocked":
            item["status"] = "blocked"
            item["blockedAt"] = bot.get("blockedAt")
            by_status["blocked"].append(item)
        else:
            item["status"] = "pending"
            by_status["pending"].append(item)

    return {
        "ok": True,
        "total": total,
        "stats": {
            "connected": len(by_status["connected"]),
            "pending": len(by_status["pending"]),
            "blocked": len(by_status["blocked"]),
            "not_registered": len(by_status["not_registered"]),
        },
        "connected": sorted(by_status["connected"], key=lambda x: x["fullName"]),
        "pending": sorted(by_status["pending"], key=lambda x: x["fullName"]),
        "blocked": sorted(by_status["blocked"], key=lambda x: x["fullName"]),
        "not_registered": sorted(by_status["not_registered"], key=lambda x: x["fullName"]),
    }