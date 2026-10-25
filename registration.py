"""Ro'yxatdan o'tish — baholarni hoziroq olmaslik."""

import logging
import uuid
from datetime import datetime, timezone

from crypto import encrypt
from firebase_admin import firestore
from firebase_client import db
from emaktab import login, fetch_data, CaptchaRequired, LoginFailed
from config import settings

log = logging.getLogger("registration")


def register_student(task_id: str, req) -> dict:
    """
    Ro'yxatdan o'tish (baholar YO'Q).
    
    1. Emaktab ga kirib tekshirish (login/parol to'g'rimi?)
    2. Faqat credentials saqlash
    3. Baholar keyin — Direktor "Ishga tushirish" bosganda yuklanadi
    """
    # 1. Emaktab ga kirib tekshirish
    try:
        lr = login(req.login, req.password)
        cookies = lr.cookies
    except CaptchaRequired:
        return {"ok": False, "error": "CAPTCHA chiqdi. Qayta urinib ko'ring."}
    except LoginFailed:
        return {"ok": False, "error": "eMaktab login yoki parol xato"}
    except Exception as e:
        log.exception("Login xato")
        return {"ok": False, "error": f"Xatolik: {type(e).__name__}"}

    # 2. Emaktab dan ismni olish (baholarni EMAS, faqat profil)
    try:
        data = fetch_data(cookies, fetch_grades=False)  # ✅ Baholar yo'q
        student_info = data.get("student", {})
    except Exception as e:
        log.exception("Fetch xato")
        return {"ok": False, "error": "Ma'lumot olib bo'lmadi"}

    first_name = student_info.get("firstName") or ""
    last_name = student_info.get("lastName") or ""

    if first_name and last_name:
        full_name = f"{first_name} {last_name}".strip()
    else:
        full_name = req.fullName.strip() or "Noma'lum"

    # 3. Saqlash
    c = db()
    now = datetime.now(timezone.utc)
    student_id = f"student_{uuid.uuid4().hex[:12]}"

    phone_clean = req.phone.strip()
    mother_clean = req.motherPhone.strip()
    father_clean = req.fatherPhone.strip() if req.fatherPhone else ""

    # students
    c.collection("students").document(student_id).set({
        "fullName": full_name,
        "classId": req.classId or settings.class_id,
        "phone": phone_clean,
        "motherPhone": mother_clean,
        "fatherPhone": father_clean,
        "status": "active",
        "emaktab": {
            "personId": student_info.get("personId"),
            "userId": student_info.get("userId"),
            "firstName": first_name,
            "lastName": last_name,
        },
        "gradesCount": 0,      # ← 0 dan boshlanadi
        "subjectsCount": 0,
        "scheduleCount": 0,
        "registeredAt": now,
        "createdAt": now,
        "updatedAt": now,
        "syncEnabled": False,   # ← Direktor bosguncha baholar yuklanmaydi
    })

    # users
    c.collection("users").document(student_id).set({
        "fullName": full_name,
        "role": "student",
        "classId": req.classId or settings.class_id,
        "phone": phone_clean,
        "botStatus": "pending",
        "totalScore": 0,
        "timezone": "Asia/Tashkent",
        "createdAt": now,
        "updatedAt": now,
    }, merge=True)

    # credentials
    c.collection("emaktab_creds").document(student_id).set({
        "login": req.login,
        "passwordEncrypted": encrypt(req.password),
        "cookiesEncrypted": encrypt(str(cookies)),
        "status": "active",
        "lastSync": None,  # ← hali sync bo'lmagan
        "createdAt": now,
    })

    # queue — Direktor bosguncha kutadi
    c.collection("emaktab_queue").document(student_id).set({
        "studentId": student_id,
        "priority": 5,
        "nextAttempt": None,   # ← keyin qo'yiladi
        "lastAttempt": None,
        "attempts": 0,
        "lastResult": None,
        "errorMessage": "",
        "syncEnabled": False,  # ← Direktor bosguncha
    })

    log.info("[REGISTER] %s yaratildi (baholarsiz)", full_name)

    return {
        "ok": True,
        "student_id": student_id,
        "fullName": full_name,
        "message": f"{full_name} ro'yxatdan o'tdi. Baholar direktor ishga tushirgach yuklanadi.",
    }