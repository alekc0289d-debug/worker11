"""Oylik TOP-3 sovg'a — pul yoki 1 oy Telegram Premium."""

import logging
from calendar import monthrange
from datetime import datetime, timedelta, timezone

from firebase_client import db
from config import settings

log = logging.getLogger("prizes")

PRIZE_AMOUNTS = {1: 100_000, 2: 40_000, 3: 20_000}
PRIZE_PREMIUM_MONTHS = {1: 1, 2: 1, 3: 1}   # hammasiga 1 oy


def _month_range(year: int, month: int):
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    last_day = monthrange(year, month)[1]
    last = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return first, last


def _student_scores(sid: str, since: datetime, until: datetime):
    c = db()
    grades = [
        d.to_dict()
        for d in c.collection("grades")
        .where("studentId", "==", sid)
        .where("source", "==", "emaktab")
        .stream()
        if d.to_dict().get("score") is not None
    ]
    if not grades:
        return None

    def in_range(g, s, u):
        try:
            dt = datetime.fromisoformat(g.get("date", "")).replace(tzinfo=timezone.utc)
            return s <= dt <= u
        except Exception:
            return False

    month_grades = [g for g in grades if in_range(g, since, until)]
    prev_start = since - timedelta(days=30)
    prev_grades = [g for g in grades if in_range(g, prev_start, since)]

    if not month_grades:
        return None

    def avg(gs):
        vals = [float(g["score"]) for g in gs if g.get("score") is not None]
        return round(sum(vals) / len(vals), 2) if vals else 0

    m_avg = avg(month_grades)
    p_avg = avg(prev_grades)
    growth = round(m_avg - p_avg, 2) if prev_grades else 0

    metric = getattr(settings, "prize_metric", "combined")
    if metric == "avg":
        final = m_avg
    elif metric == "growth":
        final = growth
    else:
        aw = getattr(settings, "prize_avg_weight", 0.6)
        gw = getattr(settings, "prize_growth_weight", 0.4)
        final = round(aw * m_avg + gw * (growth * 10), 2)

    return {"avg": m_avg, "growth": growth, "final": final,
            "gradesCount": len(month_grades)}


def compute_class_ranking(class_id: str, year: int, month: int):
    c = db()
    since, until = _month_range(year, month)
    students = list(
        c.collection("students").where("classId", "==", class_id).stream()
    )
    ranking = []
    for sdoc in students:
        score = _student_scores(sdoc.id, since, until)
        if not score:
            continue
        ranking.append({
            "studentId": sdoc.id,
            "fullName": sdoc.to_dict().get("fullName", "—"),
            "classId": class_id,
            **score,
        })
    ranking.sort(key=lambda x: x["final"], reverse=True)
    for i, r in enumerate(ranking):
        r["rank"] = i + 1
    return ranking[:50]


def compute_school_ranking(year: int, month: int, limit: int = 100):
    c = db()
    since, until = _month_range(year, month)
    all_s = []
    for sdoc in c.collection("students").stream():
        sdata = sdoc.to_dict()
        score = _student_scores(sdoc.id, since, until)
        if score:
            all_s.append({
                "studentId": sdoc.id,
                "fullName": sdata.get("fullName", "—"),
                "classId": sdata.get("classId", "—"),
                **score,
            })
    all_s.sort(key=lambda x: x["final"], reverse=True)
    for i, r in enumerate(all_s):
        r["rank"] = i + 1
    return all_s[:limit]


def generate_monthly_prizes(year: int, month: int, class_id: str | None = None):
    """O'tgan oy uchun TOP-3 sovg'a yaratadi."""
    c = db()
    now = datetime.now(timezone.utc)
    if month == 1:
        prev_y, prev_m = year - 1, 12
    else:
        prev_y, prev_m = year, month - 1

    classes = [class_id] if class_id else sorted({
        s.to_dict().get("classId")
        for s in c.collection("students").stream()
        if s.to_dict().get("classId")
    })

    created = 0
    for cid in classes:
        ranking = compute_class_ranking(cid, prev_y, prev_m)
        for entry in ranking[:3]:
            place = entry["rank"]
            prize_id = f"{cid}_{prev_y}_{prev_m:02d}_p{place}"
            ref = c.collection("prizes").document(prize_id)
            if ref.get().exists:
                continue
            ref.set({
                "studentId": entry["studentId"],
                "studentName": entry["fullName"],
                "classId": cid,
                "year": prev_y, "month": prev_m,
                "place": place,
                "metric": getattr(settings, "prize_metric", "combined"),
                "score": entry["final"],
                "avg": entry["avg"],
                "growth": entry["growth"],
                "choice": None,
                "moneyAmount": PRIZE_AMOUNTS[place],
                "premiumMonths": PRIZE_PREMIUM_MONTHS[place],
                "status": "awaiting_choice",
                "createdAt": now,
                "chosenAt": None, "givenAt": None, "givenBy": None,
                "telegramUsername": None,
                "notes": "",
            })
            created += 1

    log.info("[PRIZE] %s-%s: %s ta yaratildi", prev_y, prev_m, created)
    return {"ok": True, "created": created,
            "period": f"{prev_y}-{prev_m:02d}"}


def choose_prize(prize_id: str, choice: str, telegram_username: str = ""):
    if choice not in ("money", "premium"):
        return {"ok": False, "message": "Faqat 'money' yoki 'premium'"}
    c = db()
    now = datetime.now(timezone.utc)
    ref = c.collection("prizes").document(prize_id)
    doc = ref.get()
    if not doc.exists:
        return {"ok": False, "message": "Sovg'a topilmadi"}
    d = doc.to_dict()
    if d.get("status") != "awaiting_choice":
        return {"ok": False, "message": "Tanlov allaqachon qilingan"}

    ref.set({
        "choice": choice,
        "telegramUsername": telegram_username or None,
        "chosenAt": now,
        "status": "pending",
    }, merge=True)

    c.collection("super_admin_inbox").add({
        "type": "prize_choice",
        "prizeId": prize_id,
        "studentId": d["studentId"],
        "classId": d["classId"],
        "place": d["place"],
        "choice": choice,
        "amount": d.get("moneyAmount") if choice == "money" else None,
        "months": d.get("premiumMonths") if choice == "premium" else None,
        "telegramUsername": telegram_username,
        "timestamp": now, "read": False,
    })
    return {"ok": True, "choice": choice}


def mark_prize_given(prize_id: str, given_by: str, notes: str = ""):
    c = db()
    now = datetime.now(timezone.utc)
    ref = c.collection("prizes").document(prize_id)
    doc = ref.get()
    if not doc.exists:
        return {"ok": False, "message": "Sovg'a topilmadi"}
    d = doc.to_dict()
    ref.set({
        "status": "given",
        "givenAt": now, "givenBy": given_by, "notes": notes,
    }, merge=True)
    c.collection("prize_logs").add({
        "prizeId": prize_id,
        "studentId": d["studentId"],
        "place": d["place"],
        "choice": d.get("choice"),
        "amount": d.get("moneyAmount") if d.get("choice") == "money" else None,
        "months": d.get("premiumMonths") if d.get("choice") == "premium" else None,
        "givenBy": given_by, "timestamp": now,
    })
    return {"ok": True}


def list_pending_prizes():
    c = db()
    docs = c.collection("prizes").where("status", "==", "pending").stream()
    return [{"id": d.id, **d.to_dict()} for d in docs]


def list_awaiting_choice(sid: str):
    c = db()
    docs = (
        c.collection("prizes")
        .where("studentId", "==", sid)
        .where("status", "==", "awaiting_choice")
        .stream()
    )
    return [{"id": d.id, **d.to_dict()} for d in docs]