"""To'lov va haftalik hisobot — yiliga 5000 so'm."""

import logging
from datetime import datetime, timezone

from firebase_client import BatchWriter, db

log = logging.getLogger("payments")

ANNUAL_FEE = 5000


# ============================================================
# TO'LOV
# ============================================================
def mark_paid(sid: str, year: int, collected_by: str, notes: str = ""):
    c = db()
    now = datetime.now(timezone.utc)
    ref = c.collection("payments").document(f"{sid}_{year}")

    existing = ref.get()
    if existing.exists and existing.to_dict().get("status") == "paid":
        return {"ok": False, "message": "Allaqachon to'langan"}

    s = c.collection("students").document(sid).get()
    if not s.exists:
        return {"ok": False, "message": "O'quvchi topilmadi"}
    student = s.to_dict()

    ref.set({
        "studentId": sid,
        "classId": student.get("classId"),
        "fullName": student.get("fullName"),
        "year": year,
        "amount": ANNUAL_FEE,
        "status": "paid",
        "paidAt": now,
        "collectedBy": collected_by,
        "submittedToSuperAdmin": False,
        "submittedAt": None,
        "submissionId": None,
        "notes": notes,
        "updatedAt": now,
    }, merge=True)

    c.collection("payment_logs").add({
        "studentId": sid,
        "classId": student.get("classId"),
        "action": "paid",
        "amount": ANNUAL_FEE,
        "by": collected_by,
        "timestamp": now,
    })
    log.info("[PAY] %s paid by %s", sid[:12], collected_by)
    return {"ok": True, "message": "To'lov qabul qilindi"}


def unmark_paid(sid: str, year: int, by: str, reason: str = ""):
    c = db()
    now = datetime.now(timezone.utc)
    ref = c.collection("payments").document(f"{sid}_{year}")
    if not ref.get().exists:
        return {"ok": False, "message": "To'lov topilmadi"}
    ref.set({"status": "unpaid", "paidAt": None, "updatedAt": now}, merge=True)
    c.collection("payment_logs").add({
        "studentId": sid, "action": "unpaid",
        "by": by, "reason": reason, "timestamp": now,
    })
    return {"ok": True}


# ============================================================
# HISOBOT
# ============================================================
def class_report(class_id: str, year: int):
    c = db()
    students = list(
        c.collection("students").where("classId", "==", class_id).stream()
    )
    total = len(students)
    registered = connected = paid = expired = 0
    detail = []

    for sdoc in students:
        sid = sdoc.id
        sdata = sdoc.to_dict()

        creds = c.collection("emaktab_creds").document(sid).get()
        is_registered = creds.exists
        is_connected = False
        status = "not_registered"

        if is_registered:
            registered += 1
            cd = creds.to_dict()
            st = cd.get("status", "")
            if st == "active" and cd.get("cookiesEncrypted"):
                connected += 1
                is_connected = True
                status = "connected"
            elif st == "captcha_required":
                status = "captcha_required"
            elif st in ("expired", "error"):
                expired += 1
                status = "expired"
            else:
                status = "registered"

        pay = c.collection("payments").document(f"{sid}_{year}").get()
        is_paid = pay.exists and pay.to_dict().get("status") == "paid"
        if is_paid:
            paid += 1

        detail.append({
            "studentId": sid,
            "fullName": sdata.get("fullName", "—"),
            "registered": is_registered,
            "connected": is_connected,
            "paid": is_paid,
            "status": status,
        })

    return {
        "classId": class_id, "year": year, "total": total,
        "registered": registered, "connected": connected,
        "expired": expired, "paid": paid,
        "notRegistered": total - registered,
        "notConnected": registered - connected,
        "unpaid": total - paid,
        "expectedAmount": total * ANNUAL_FEE,
        "collectedAmount": paid * ANNUAL_FEE,
        "detail": detail,
    }


# ============================================================
# HAFTALIK HISOBOT
# ============================================================
def submit_weekly_report(class_id: str, year: int, week: int,
                         submitted_by: str, notes: str = ""):
    c = db()
    now = datetime.now(timezone.utc)
    stats = class_report(class_id, year)
    detail = stats.pop("detail")

    report_id = f"{class_id}_{year}_W{week:02d}"

    c.collection("weekly_reports").document(report_id).set({
        "classId": class_id, "year": year, "week": week,
        "stats": stats,
        "submittedBy": submitted_by,
        "submittedAt": now,
        "notes": notes,
        "status": "submitted",
    }, merge=True)

    c.collection("super_admin_inbox").add({
        "type": "weekly_report",
        "classId": class_id, "year": year, "week": week,
        "submittedBy": submitted_by,
        "stats": stats,
        "timestamp": now, "read": False,
    })

    log.info("[REPORT] %s W%s: %s/%s to'langan",
             class_id, week, stats["paid"], stats["total"])
    return {"ok": True, "reportId": report_id, "stats": stats}


def list_weekly_reports(year: int = 0, class_id: str = ""):
    c = db()
    q = c.collection("weekly_reports")
    if year:
        q = q.where("year", "==", year)
    if class_id:
        q = q.where("classId", "==", class_id)
    docs = list(q.stream())
    docs.sort(key=lambda d: d.to_dict().get("submittedAt") or 0, reverse=True)
    return [{"id": d.id, **d.to_dict()} for d in docs[:200]]


# ============================================================
# PUL TOPSHIRISH (sinf admini → superadmin)
# ============================================================
def submit_collected_money(class_id: str, year: int, week: int,
                           submitted_by: str):
    c = db()
    now = datetime.now(timezone.utc)

    paid_docs = list(
        c.collection("payments")
        .where("classId", "==", class_id)
        .where("year", "==", year)
        .where("status", "==", "paid")
        .where("submittedToSuperAdmin", "==", False)
        .stream()
    )
    if not paid_docs:
        return {"ok": False, "message": "Topshirish uchun yangi to'lov yo'q"}

    sub_ref = c.collection("payment_submissions").document()
    student_ids = [d.id.split("_")[0] for d in paid_docs]
    total = len(paid_docs) * ANNUAL_FEE

    sub_ref.set({
        "classId": class_id, "year": year, "week": week,
        "studentIds": student_ids,
        "studentCount": len(student_ids),
        "totalAmount": total,
        "submittedBy": submitted_by,
        "submittedAt": now,
        "status": "pending",
        "receivedBy": None, "receivedAt": None,
    })

    w = BatchWriter(c)
    for d in paid_docs:
        w.set(d.reference, {
            "submittedToSuperAdmin": True,
            "submittedAt": now,
            "submissionId": sub_ref.id,
        }, merge=True)
    w.flush()

    c.collection("super_admin_inbox").add({
        "type": "payment_submission",
        "submissionId": sub_ref.id,
        "classId": class_id,
        "studentCount": len(student_ids),
        "totalAmount": total,
        "submittedBy": submitted_by,
        "timestamp": now, "read": False,
    })

    log.info("[PAY] %s: %s ta, %s so'm", class_id, len(student_ids), total)
    return {
        "ok": True,
        "submissionId": sub_ref.id,
        "studentCount": len(student_ids),
        "totalAmount": total,
    }


def receive_submission(submission_id: str, received_by: str):
    c = db()
    now = datetime.now(timezone.utc)
    ref = c.collection("payment_submissions").document(submission_id)
    if not ref.get().exists:
        return {"ok": False, "message": "Topshiriq topilmadi"}
    ref.set({
        "status": "received",
        "receivedBy": received_by,
        "receivedAt": now,
    }, merge=True)
    return {"ok": True}