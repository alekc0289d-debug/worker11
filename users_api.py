"""Foydalanuvchilar va sinf o'quvchilari API."""

import logging
from datetime import datetime, timezone
from collections import defaultdict

from firebase_client import db
from auth import clean_phone

log = logging.getLogger("users_api")


# ============================================================
# FOYDALANUVCHILAR (superadmin)
# ============================================================
def list_users(
    role: str = "",
    class_id: str = "",
    search: str = "",
    status: str = "",
    limit: int = 500,
) -> dict:
    """Barcha foydalanuvchilar — filter bilan."""
    c = db()
    q = c.collection("users")

    if role:
        q = q.where("role", "==", role)
    if class_id:
        q = q.where("classId", "==", class_id)

    docs = list(q.limit(limit).stream())
    users = []
    for d in docs:
        data = d.to_dict()
        if status and data.get("status", "active") != status:
            continue
        if search:
            s = search.lower()
            if (
                s not in (data.get("fullName", "") or "").lower()
                and s not in (data.get("phone", "") or "")
            ):
                continue
        users.append({
            "id": d.id,
            "fullName": data.get("fullName", ""),
            "role": data.get("role", ""),
            "classId": data.get("classId", ""),
            "phone": data.get("phone", ""),
            "telegramId": data.get("telegramId"),
            "status": data.get("status", "active"),
            "botStatus": data.get("botStatus", "pending"),
            "totalScore": data.get("totalScore", 0),
            "createdAt": data.get("createdAt"),
        })

    users.sort(key=lambda x: (x["role"], x["fullName"]))
    return {"ok": True, "count": len(users), "users": users}


def get_user_details(user_id: str) -> dict:
    """Bitta foydalanuvchi haqida to'liq ma'lumot."""
    c = db()
    doc = c.collection("users").document(user_id).get()
    if not doc.exists:
        return {"ok": False, "message": "Topilmadi"}

    d = doc.to_dict()

    # Baholar soni
    grades_count = len(list(
        c.collection("grades").where("studentId", "==", user_id).limit(1).stream()
    ))

    return {
        "ok": True,
        "user": {
            "id": doc.id,
            "fullName": d.get("fullName", ""),
            "role": d.get("role", ""),
            "classId": d.get("classId", ""),
            "phone": d.get("phone", ""),
            "telegramId": d.get("telegramId"),
            "status": d.get("status", "active"),
            "botStatus": d.get("botStatus", "pending"),
            "totalScore": d.get("totalScore", 0),
            "hasPassword": bool(d.get("passwordHash")),
            "createdAt": d.get("createdAt"),
            "gradesCount": grades_count,
        },
    }


def update_user_role(user_id: str, new_role: str, by_role: str) -> dict:
    """Foydalanuvchi rolini o'zgartirish (bosh_admin)."""
    if by_role != "bosh_admin":
        return {"ok": False, "message": "Ruxsat yo'q"}

    valid = {"student", "parent", "teacher", "class_admin", "director", "bosh_admin"}
    if new_role not in valid:
        return {"ok": False, "message": "Noto'g'ri rol"}

    db().collection("users").document(user_id).set({
        "role": new_role,
        "updatedAt": datetime.now(timezone.utc),
    }, merge=True)

    log.info("[USER] %s → role=%s", user_id[:12], new_role)
    return {"ok": True}


def delete_user(user_id: str, by_role: str) -> dict:
    """Foydalanuvchini o'chirish (soft)."""
    if by_role != "bosh_admin":
        return {"ok": False, "message": "Ruxsat yo'q"}

    c = db()
    now = datetime.now(timezone.utc)

    c.collection("users").document(user_id).set({
        "status": "deleted",
        "deletedAt": now,
        "updatedAt": now,
    }, merge=True)

    log.warning("[USER] %s o'chirildi (soft)", user_id[:12])
    return {"ok": True}


def promote_to_class_admin(student_id: str, by_role: str, class_id: str = "") -> dict:
    """O'quvchini sinf admini qilish — FAQAT bosh_admin."""
    if by_role != "bosh_admin":
        return {"ok": False, "message": "Faqat Bosh admin tayinlay oladi"}

    c = db()
    doc = c.collection("users").document(student_id).get()
    if not doc.exists:
        return {"ok": False, "message": "Foydalanuvchi topilmadi"}

    d = doc.to_dict()
    if d.get("role") == "class_admin":
        return {"ok": False, "message": "Allaqachon sinf admini"}

    upd = {
        "role": "class_admin",
        "updatedAt": datetime.now(timezone.utc),
    }
    if class_id:
        upd["classId"] = class_id

    c.collection("users").document(student_id).set(upd, merge=True)
    
    log.info("[USER] %s → class_admin", student_id[:12])
    return {"ok": True, "message": f"{d.get('fullName')} sinf admini qilindi"}


# ============================================================
# SINF O'QUVCHILARI (class_admin)
# ============================================================
def class_students(class_id: str, year: int) -> dict:
    """Sinfdagi barcha o'quvchilar — to'lov, bot, baholar bilan."""
    c = db()

    students = list(
        c.collection("students").where("classId", "==", class_id).stream()
    )

    # Batch grades
    s_ids = [s.id for s in students]
    grades_map = defaultdict(list)
    for i in range(0, len(s_ids), 10):
        chunk = s_ids[i:i + 10]
        if not chunk:
            continue
        try:
            for d in (
                c.collection("grades").where("studentId", "in", chunk).stream()
            ):
                g = d.to_dict()
                sid = g.get("studentId")
                if sid in s_ids:
                    grades_map[sid].append(g)
        except Exception:
            pass

    # Payments
    payments_map = {}
    for p in c.collection("payments").where("classId", "==", class_id).stream():
        pd = p.to_dict()
        if pd.get("year") == year and pd.get("status") == "paid":
            sid = pd.get("studentId")
            if sid:
                payments_map[sid] = True

    # Bot users
    bot_map = {}
    for b in c.collection("bot_users").where("classId", "==", class_id).stream():
        bd = b.to_dict()
        bot_map[bd.get("userId")] = bd.get("status", "pending")

    result = []
    for s in students:
        sd = s.to_dict()
        sid = s.id

        # O'rtacha
        grades = grades_map.get(sid, [])
        scores = [g.get("score") for g in grades if g.get("score") is not None]
        avg = round(sum(scores) / len(scores), 2) if scores else 0

        # Telegram
        udoc = c.collection("users").document(sid).get()
        bot_status = "not_registered"
        if udoc.exists:
            bot_status = udoc.to_dict().get("botStatus", "pending")

        result.append({
            "studentId": sid,
            "fullName": sd.get("fullName", "—"),
            "classId": sd.get("classId", ""),
            "phone": sd.get("phone", ""),
            "motherPhone": sd.get("motherPhone", ""),
            "fatherPhone": sd.get("fatherPhone", ""),
            "status": sd.get("status", "active"),
            "avg": avg,
            "gradesCount": len(grades),
            "paid": payments_map.get(sid, False),
            "botStatus": bot_status,
        })

    result.sort(key=lambda x: x["fullName"])
    return {"ok": True, "count": len(result), "students": result}


def get_student_detail(student_id: str) -> dict:
    """Bitta o'quvchi haqida to'liq ma'lumot."""
    c = db()

    sdoc = c.collection("students").document(student_id).get()
    if not sdoc.exists:
        return {"ok": False, "message": "O'quvchi topilmadi"}

    sd = sdoc.to_dict()

    # Baholar
    grades = [
        {"id": d.id, **d.to_dict()}
        for d in c.collection("grades").where("studentId", "==", student_id).stream()
    ]
    grades.sort(key=lambda g: g.get("date") or "", reverse=True)

    # Fan bo'yicha
    by_subject = defaultdict(list)
    for g in grades:
        if g.get("subject") and g.get("score") is not None:
            by_subject[g["subject"]].append(g["score"])

    subjects = [
        {
            "name": s,
            "avg": round(sum(v) / len(v), 2),
            "count": len(v),
        }
        for s, v in by_subject.items()
    ]
    subjects.sort(key=lambda x: x["avg"], reverse=True)

    return {
        "ok": True,
        "student": {
            "id": student_id,
            "fullName": sd.get("fullName", ""),
            "classId": sd.get("classId", ""),
            "phone": sd.get("phone", ""),
            "motherPhone": sd.get("motherPhone", ""),
            "fatherPhone": sd.get("fatherPhone", ""),
            "status": sd.get("status", "active"),
            "gradesCount": len(grades),
            "subjects": subjects,
            "recentGrades": [
                {
                    "id": g.get("id"),
                    "subject": g.get("subject"),
                    "score": g.get("score"),
                    "date": g.get("date"),
                }
                for g in grades[:30]
            ],
        },
    }


def update_student(student_id: str, payload: dict, by_role: str) -> dict:
    """O'quvchi ma'lumotlarini yangilash."""
    if by_role not in ("class_admin", "director", "bosh_admin"):
        return {"ok": False, "message": "Ruxsat yo'q"}

    allowed = {"fullName", "phone", "motherPhone", "fatherPhone", "classId"}
    safe = {k: v for k, v in payload.items() if k in allowed}
    if not safe:
        return {"ok": False, "message": "O'zgartiriladigan maydon yo'q"}

    # Telefonlarni tozalash
    for k in ("phone", "motherPhone", "fatherPhone"):
        if k in safe:
            safe[k] = clean_phone(safe[k])

    safe["updatedAt"] = datetime.now(timezone.utc)
    db().collection("students").document(student_id).set(safe, merge=True)

    # users ham yangilansin
    if "fullName" in safe or "phone" in safe or "classId" in safe:
        db().collection("users").document(student_id).set(safe, merge=True)

    log.info("[STUDENT] %s yangilandi", student_id[:12])
    return {"ok": True}


def delete_student(student_id: str, by_role: str) -> dict:
    """O'quvchini o'chirish (soft)."""
    if by_role not in ("director", "bosh_admin"):
        return {"ok": False, "message": "Faqat direktor va bosh admin"}

    c = db()
    now = datetime.now(timezone.utc)

    c.collection("students").document(student_id).set({
        "status": "deleted",
        "deletedAt": now,
        "updatedAt": now,
    }, merge=True)

    c.collection("users").document(student_id).set({
        "status": "deleted",
        "deletedAt": now,
    }, merge=True)

    log.warning("[STUDENT] %s o'chirildi", student_id[:12])
    return {"ok": True}


def get_student_grades_paginated(student_id: str, limit: int = 30, offset: int = 0) -> dict:
    """Baholar pagination bilan."""
    c = db()
    
    grades = [
        {"id": d.id, **d.to_dict()}
        for d in c.collection("grades").where("studentId", "==", student_id).stream()
    ]
    grades.sort(key=lambda g: g.get("date") or "", reverse=True)
    
    total = len(grades)
    page = grades[offset:offset + limit]
    
    return {
        "ok": True,
        "grades": page,
        "total": total,
        "hasMore": offset + limit < total,
        "offset": offset,
        "limit": limit,
    }