"""Sinflar boshqaruvi — Firestore'dan."""

import logging
import re
import uuid as _uuid
from datetime import datetime, timezone

from firebase_client import db
from auth import _hash_password, clean_phone

log = logging.getLogger("classes")


# ============================================================
# Yordamchi
# ============================================================
def _normalize_class_id(raw: str) -> str:
    """'9a' → '9-A', '9 a' → '9-A', '9-A' → '9-A'."""
    if not raw:
        return ""
    s = raw.strip().upper().replace(" ", "").replace("_", "-")
    m = re.match(r"^(\d{1,2})-?([A-ZА-Я]?)$", s)
    if m:
        num, letter = m.group(1), m.group(2)
        return f"{num}-{letter}" if letter else num
    return s


# ============================================================
# O'QISH
# ============================================================
def list_classes(active_only: bool = True) -> list:
    """Barcha sinflar (sinf raqami bo'yicha tartiblangan)."""
    c = db()
    q = c.collection("classes")
    if active_only:
        q = q.where("active", "==", True)
    docs = list(q.stream())
    items = [{"id": d.id, **d.to_dict()} for d in docs]

    def sort_key(x):
        cid = x.get("classId", "")
        m = re.match(r"^(\d+)", cid)
        num = int(m.group(1)) if m else 0
        return (num, cid)

    items.sort(key=sort_key)
    return items


def get_class(class_id: str):
    """Bitta sinfni olish."""
    doc = db().collection("classes").document(class_id).get()
    if not doc.exists:
        return None
    return {"id": doc.id, **doc.to_dict()}


# ============================================================
# YARATISH
# ============================================================
def create_class(
    class_id: str,
    created_by: str,
    created_by_role: str,
    description: str = "",
    class_teacher: dict = None,
    class_admin: dict = None,
) -> dict:
    """
    Yangi sinf ochish.

    class_teacher = {"fullName": "...", "phone": "+998...", "telegramId": 123}
    class_admin   = {"fullName": "...", "phone": "+998...", "telegramId": 456}
    """
    if created_by_role not in ("bosh_admin", "director"):
        return {"ok": False, "message": "Sizda sinf ochish huquqi yo'q"}

    cid = _normalize_class_id(class_id)
    if not cid:
        return {"ok": False, "message": "Sinf nomi bo'sh"}
    if len(cid) > 10:
        return {"ok": False, "message": "Sinf nomi juda uzun"}

    c = db()
    ref = c.collection("classes").document(cid)
    if ref.get().exists:
        return {"ok": False, "message": f"'{cid}' sinfi allaqachon mavjud"}

    # ============ Rahbar ============
    ct = class_teacher or {}
    ct_name = (ct.get("fullName") or "").strip()
    ct_phone = clean_phone(ct.get("phone") or "")
    ct_tg = ct.get("telegramId")

    if not ct_name:
        return {"ok": False, "message": "Sinf rahbarining ismi majburiy"}
    if len(ct_phone) < 12:
        return {"ok": False, "message": "Sinf rahbarining telefoni to'liq emas"}

    # ============ Admin ============
    ca = class_admin or {}
    ca_name = (ca.get("fullName") or "").strip()
    ca_phone = clean_phone(ca.get("phone") or "")
    ca_tg = ca.get("telegramId")

    if not ca_name:
        return {"ok": False, "message": "Sinf adminining ismi majburiy"}
    if len(ca_phone) < 12:
        return {"ok": False, "message": "Sinf adminining telefoni to'liq emas"}

    if ct_phone == ca_phone:
        return {"ok": False, "message": "Rahbar va admin telefoni bir xil"}

    now = datetime.now(timezone.utc)

    ref.set({
        "classId": cid,
        "description": description.strip(),
        "active": True,
        "studentsCount": 0,

        "classTeacher": {
            "fullName": ct_name,
            "phone": ct_phone,
            "telegramId": ct_tg,
            "addedAt": now,
        },
        "classAdmin": {
            "fullName": ca_name,
            "phone": ca_phone,
            "telegramId": ca_tg,
            "addedAt": now,
        },

        "createdBy": created_by,
        "createdByRole": created_by_role,
        "createdAt": now,
        "updatedAt": now,
    })

    log.info("[CLASS] + %s | rahbar: %s | admin: %s", cid, ct_name, ca_name)

    # Users'ga qo'shish
    _add_staff_user(ct_name, ct_phone, "teacher", cid, ct_tg)
    _add_staff_user(ca_name, ca_phone, "class_admin", cid, ca_tg)

    return {"ok": True, "classId": cid}


def _add_staff_user(
    full_name: str, phone: str, role: str,
    class_id: str, telegram_id=None,
):
    """Sinf rahbari yoki adminini users kolleksiyasiga qo'shish."""
    c = db()
    now = datetime.now(timezone.utc)
    p = clean_phone(phone)

    # Mavjudmi?
    existing = list(
        c.collection("users").where("phone", "==", p).limit(1).stream()
    )

    if existing:
        c.collection("users").document(existing[0].id).set({
            "fullName": full_name,
            "role": role,
            "classId": class_id,
            "telegramId": telegram_id,
            "updatedAt": now,
        }, merge=True)
        log.info("[CLASS] user yangilandi: %s (%s)", full_name, role)
        return existing[0].id

    # Yangi (parol = telefon)
    user_id = f"{role}_{_uuid.uuid4().hex[:12]}"
    c.collection("users").document(user_id).set({
        "fullName": full_name,
        "phone": p,
        "passwordHash": _hash_password(p),
        "role": role,
        "classId": class_id,
        "telegramId": telegram_id,
        "status": "active",
        "totalScore": 0,
        "timezone": "Asia/Tashkent",
        "createdAt": now,
        "updatedAt": now,
    })
    log.info("[CLASS] yangi user: %s (%s)", full_name, role)
    return user_id


# ============================================================
# O'CHIRISH
# ============================================================
def delete_class(class_id: str, by_role: str) -> dict:
    """Sinfni o'chirish — faqat bosh_admin."""
    if by_role != "bosh_admin":
        return {"ok": False, "message": "Faqat Bosh admin o'chira oladi"}

    c = db()
    ref = c.collection("classes").document(class_id)
    if not ref.get().exists:
        return {"ok": False, "message": "Sinf topilmadi"}

    students = list(
        c.collection("students").where("classId", "==", class_id).limit(1).stream()
    )
    if students:
        return {
            "ok": False,
            "message": f"'{class_id}' sinfida o'quvchilar bor",
        }

    ref.delete()
    log.info("[CLASS] - %s", class_id)
    return {"ok": True}


# ============================================================
# TOGGLE
# ============================================================
def toggle_active(class_id: str, by_role: str) -> dict:
    """Sinfni aktiv/nofaol qilish."""
    if by_role not in ("bosh_admin", "director"):
        return {"ok": False, "message": "Ruxsat yo'q"}

    ref = db().collection("classes").document(class_id)
    doc = ref.get()
    if not doc.exists:
        return {"ok": False, "message": "Topilmadi"}

    current = doc.to_dict().get("active", True)
    ref.set({
        "active": not current,
        "updatedAt": datetime.now(timezone.utc),
    }, merge=True)

    return {"ok": True, "active": not current}


# ============================================================
# UPDATE COUNT
# ============================================================
def update_students_count(class_id: str, count: int) -> dict:
    """O'quvchilar sonini yangilash."""
    db().collection("classes").document(class_id).set({
        "studentsCount": count,
        "updatedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {"ok": True}
def update_class(
    class_id: str,
    by_role: str,
    description: str = "",
    class_teacher: dict = None,
    class_admin: dict = None,
) -> dict:
    """Sinfni tahrirlash."""
    if by_role not in ("bosh_admin", "director"):
        return {"ok": False, "message": "Ruxsat yo'q"}

    c = db()
    ref = c.collection("classes").document(class_id)
    if not ref.get().exists:
        return {"ok": False, "message": "Sinf topilmadi"}

    upd = {"updatedAt": datetime.now(timezone.utc)}

    if description is not None:
        upd["description"] = description.strip()

    if class_teacher:
        ct_name = (class_teacher.get("fullName") or "").strip()
        ct_phone = clean_phone(class_teacher.get("phone") or "")
        ct_tg = class_teacher.get("telegramId")
        if ct_name and len(ct_phone) >= 12:
            upd["classTeacher"] = {
                "fullName": ct_name,
                "phone": ct_phone,
                "telegramId": ct_tg,
                "addedAt": datetime.now(timezone.utc),
            }
            _add_staff_user(ct_name, ct_phone, "teacher", class_id, ct_tg)

    if class_admin:
        ca_name = (class_admin.get("fullName") or "").strip()
        ca_phone = clean_phone(class_admin.get("phone") or "")
        ca_tg = class_admin.get("telegramId")
        if ca_name and len(ca_phone) >= 12:
            upd["classAdmin"] = {
                "fullName": ca_name,
                "phone": ca_phone,
                "telegramId": ca_tg,
                "addedAt": datetime.now(timezone.utc),
            }
            _add_staff_user(ca_name, ca_phone, "class_admin", class_id, ca_tg)

    ref.set(upd, merge=True)
    log.info("[CLASS] yangilandi: %s", class_id)
    return {"ok": True}