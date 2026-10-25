"""Sinf jadvali — sinf admini o'zi kiritadi."""

import logging
from datetime import datetime, timezone

from firebase_client import db

log = logging.getLogger("schedule")

VALID_DAYS = {
    "Dushanba", "Seshanba", "Chorshanba",
    "Payshanba", "Juma", "Shanba", "Yakshanba",
}


def save_class_schedule(class_id: str, days: dict, entered_by: str):
    """
    days = {
      "Dushanba": [ {lessonNumber, subject, teacher, startTime, endTime, room}, ... ],
      "Seshanba": [ ... ], ...
    }
    """
    if not class_id or not isinstance(days, dict):
        return {"ok": False, "message": "classId va days majburiy"}

    # Validatsiya
    cleaned = {}
    for day, lessons in days.items():
        if day not in VALID_DAYS:
            continue
        if not isinstance(lessons, list):
            continue
        cleaned_lessons = []
        for l in lessons:
            if not l.get("subject"):
                continue
            cleaned_lessons.append({
                "lessonNumber": int(l.get("lessonNumber") or 0),
                "subject": str(l.get("subject")).strip(),
                "teacher": (l.get("teacher") or "").strip(),
                "startTime": l.get("startTime") or "",
                "endTime": l.get("endTime") or "",
                "room": (l.get("room") or "").strip(),
            })
        cleaned_lessons.sort(key=lambda x: x["lessonNumber"])
        cleaned[day] = cleaned_lessons

    if not cleaned:
        return {"ok": False, "message": "Bo'sh jadval"}

    now = datetime.now(timezone.utc)
    ref = db().collection("class_schedules").document(class_id)
    existing = ref.get()

    ref.set({
        "classId": class_id,
        "days": cleaned,
        "enteredBy": entered_by,
        "enteredAt": existing.to_dict().get("enteredAt") if existing.exists else now,
        "updatedAt": now,
        "status": "active",
        "totalLessons": sum(len(v) for v in cleaned.values()),
    }, merge=True)

    log.info("[SCHEDULE] %s: %s kun saqlandi",
             class_id, len(cleaned))
    return {"ok": True, "days": len(cleaned),
            "totalLessons": sum(len(v) for v in cleaned.values())}


def get_class_schedule(class_id: str):
    d = db().collection("class_schedules").document(class_id).get()
    if not d.exists:
        return None
    return {"id": d.id, **d.to_dict()}


def clear_class_schedule(class_id: str):
    db().collection("class_schedules").document(class_id).delete()
    log.info("[SCHEDULE] %s o'chirildi", class_id)
    return {"ok": True}