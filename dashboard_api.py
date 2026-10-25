"""Dashboard ma'lumotlarini yig'ish — optimallashtirilgan (batch fetch)."""

import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from firebase_client import db
from tasks import get_user_tasks, get_user_total_score, get_next_task
from tests_system import get_user_test_stats

log = logging.getLogger("dashboard")


# ============================================================
# BATCH HELPERS — bitta so'rovda ko'p ma'lumot
# ============================================================
def _batch_grades(student_ids: list) -> dict:
    """
    Barcha o'quvchilarning baholarini BITTA so'rovda olish.
    Returns: {student_id: [grades]}
    """
    if not student_ids:
        return {}

    c = db()
    result = defaultdict(list)
    ids_set = set(student_ids)

    # Firestore "in" 10 tagacha qabul qiladi — bo'lib yuboramiz
    for i in range(0, len(student_ids), 10):
        chunk = student_ids[i:i + 10]
        try:
            for d in (
                c.collection("grades")
                .where("studentId", "in", chunk)
                .stream()
            ):
                g = d.to_dict()
                sid = g.get("studentId")
                if sid in ids_set:
                    result[sid].append({"id": d.id, **g})
        except Exception as e:
            log.warning("batch_grades chunk xato: %s", e)

    return dict(result)


def _avg_from_grades(grades: list) -> float:
    """Baholardan o'rtacha hisoblash."""
    scores = [g.get("score") for g in grades if g.get("score") is not None]
    if not scores:
        return 0
    return round(sum(scores) / len(scores), 2)


def _parse_date(s):
    if not s:
        return None
    try:
        if isinstance(s, (int, float)):
            return datetime.fromtimestamp(s, tz=timezone.utc)
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ============================================================
# O'QUVCHI DASHBOARD
# ============================================================
def student_dashboard(user_id: str) -> dict:
    c = db()

    udoc = c.collection("users").document(user_id).get()
    if not udoc.exists:
        return {"ok": False, "message": "Foydalanuvchi topilmadi"}
    u = udoc.to_dict()
    class_id = u.get("classId", "")

    # Grades — 1 so'rov
    grades = [
        {"id": d.id, **d.to_dict()}
        for d in c.collection("grades")
        .where("studentId", "==", user_id)
        .stream()
    ]
    grades_sorted = sorted(grades, key=lambda g: g.get("date") or "", reverse=True)
    avg = _avg_from_grades(grades)

    # Fan bo'yicha
    by_subject: dict = defaultdict(list)
    for g in grades:
        if g.get("score") is not None and g.get("subject"):
            by_subject[g["subject"]].append(g["score"])

    subjects_data = []
    for subj, vals in by_subject.items():
        if vals:
            a = round(sum(vals) / len(vals), 2)
            subjects_data.append({
                "name": subj,
                "avg": a,
                "count": len(vals),
                "percent": round(a / 5 * 100, 1),
            })
    subjects_data.sort(key=lambda s: s["avg"], reverse=True)

    # Chart — oxirgi 12 hafta
    now = datetime.now(timezone.utc)
    chart = []
    for i in range(11, -1, -1):
        ws = now - timedelta(weeks=i)
        we = ws + timedelta(weeks=1)
        wg_scores = []
        for g in grades:
            dt = _parse_date(g.get("date"))
            if dt and ws <= dt < we and g.get("score") is not None:
                wg_scores.append(g["score"])
        w_avg = round(sum(wg_scores) / len(wg_scores), 2) if wg_scores else 0
        chart.append({
            "label": f"W{12 - i}",
            "date": ws.date().isoformat(),
            "avg": w_avg,
        })

    # Ranking — sinf o'quvchilari
    class_students = list(
        c.collection("students").where("classId", "==", class_id).stream()
    )
    class_ids = [s.id for s in class_students]

    # Batch grades — bitta so'rovda barcha sinf
    all_grades = _batch_grades(class_ids)

    ranking = []
    for s in class_students:
        s_grades = all_grades.get(s.id, [])
        s_avg = _avg_from_grades(s_grades)
        ranking.append({
            "studentId": s.id,
            "fullName": s.to_dict().get("fullName", "—"),
            "avg": s_avg,
        })
    ranking.sort(key=lambda x: x["avg"], reverse=True)
    for i, r in enumerate(ranking):
        r["rank"] = i + 1
    my_rank = next((r["rank"] for r in ranking if r["studentId"] == user_id), 0)

    # Streak
    streak = 0
    for g in grades_sorted:
        if g.get("score") in (4, 5):
            streak += 1
        else:
            break

    # Bugungi darslar
    schedule_doc = c.collection("class_schedules").document(class_id).get()
    today_lessons = []
    if schedule_doc.exists:
        days = schedule_doc.to_dict().get("days", {})
        day_names = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
        today_name = day_names[now.weekday()]
        today_lessons = days.get(today_name, [])

    # Topshiriqlar
    tasks = get_user_tasks(user_id)
    next_task = next((t for t in tasks if t["status"] == "available"), None)
    tasks_done = sum(1 for t in tasks if t["status"] == "done")

    test_stats = get_user_test_stats(user_id)
    score_data = get_user_total_score(user_id)

    prizes = [
        {"id": d.id, **d.to_dict()}
        for d in c.collection("prizes")
        .where("studentId", "==", user_id)
        .where("status", "==", "awaiting_choice")
        .stream()
    ]

    news_docs = list(c.collection("news").where("published", "==", True).stream())
    news_docs.sort(
        key=lambda d: d.to_dict().get("createdAt") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    news = [{"id": d.id, **d.to_dict()} for d in news_docs[:3]]

    return {
        "ok": True,
        "user": {
            "id": user_id,
            "fullName": u.get("fullName", ""),
            "classId": class_id,
            "phone": u.get("phone", ""),
            "botStatus": u.get("botStatus", "pending"),
        },
        "stats": {
            "avg": avg,
            "rank": my_rank,
            "totalStudents": len(class_students),
            "streak": streak,
            "totalScore": score_data.get("total", 0),
        },
        "subjects": subjects_data,
        "recentGrades": [
            {
                "id": g.get("id"),
                "subject": g.get("subject"),
                "score": g.get("score"),
                "date": g.get("date"),
                "markType": g.get("markType"),
            }
            for g in grades_sorted[:10]
        ],
        "chart": chart,
        "ranking": ranking[:5],
        "todayLessons": today_lessons,
        "tasks": {
            "next": next_task,
            "done": tasks_done,
            "total": len(tasks),
        },
        "tests": test_stats,
        "prizes": prizes,
        "news": news,
    }


# ============================================================
# OTA-ONA
# ============================================================
def parent_dashboard(parent_id: str) -> dict:
    c = db()
    pdoc = c.collection("users").document(parent_id).get()
    if not pdoc.exists:
        return {"ok": False, "message": "Topilmadi"}
    parent = pdoc.to_dict()

    phones = []
    if parent.get("phone"):
        phones.append(parent["phone"])
    children_ids = parent.get("childrenIds", [])

    children = []
    for cid in children_ids:
        sdoc = c.collection("students").document(cid).get()
        if sdoc.exists:
            children.append({"id": sdoc.id, **sdoc.to_dict()})

    for ph in phones:
        for field in ("motherPhone", "fatherPhone"):
            for s in c.collection("students").where(field, "==", ph).stream():
                if not any(ch["id"] == s.id for ch in children):
                    children.append({"id": s.id, **s.to_dict()})

    child_ids = [ch["id"] for ch in children]
    all_grades = _batch_grades(child_ids)

    today = datetime.now(timezone.utc).date()
    result = []
    for ch in children:
        sid = ch["id"]
        grades = all_grades.get(sid, [])
        avg = _avg_from_grades(grades)
        today_grades = []
        for g in grades:
            dt = _parse_date(g.get("date"))
            if dt and dt.date() == today:
                today_grades.append({
                    "subject": g.get("subject"),
                    "score": g.get("score"),
                })
        result.append({
            "id": sid,
            "fullName": ch.get("fullName", ""),
            "classId": ch.get("classId", ""),
            "avg": avg,
            "gradesCount": len(grades),
            "todayGrades": today_grades[:5],
        })

    alerts = []
    for ch in result:
        bad = [g for g in all_grades.get(ch["id"], []) if g.get("score") and g["score"] < 4]
        if len(bad) >= 2:
            alerts.append({
                "childId": ch["id"],
                "childName": ch["fullName"],
                "type": "warning",
                "title": "Baholar pasaymoqda",
                "desc": f"{ch['fullName']}'da {len(bad)} ta past baho",
            })

    return {
        "ok": True,
        "parent": {"id": parent_id, "fullName": parent.get("fullName", "")},
        "children": result,
        "alerts": alerts,
        "messages": [],
    }


# ============================================================
# DIREKTOR — optimallashtirilgan
# ============================================================
def director_dashboard(school_id: str = "") -> dict:
    c = db()

    all_students = list(c.collection("students").stream())
    student_ids = [s.id for s in all_students]

    # ⚡ BARCHA baholarni bitta batch'da
    all_grades = _batch_grades(student_ids)

    classes_map: dict = defaultdict(list)
    for s in all_students:
        cid = s.to_dict().get("classId")
        if cid:
            classes_map[cid].append(s)

    class_stats = []
    for cid, students in classes_map.items():
        total_avg = 0
        count = 0
        struggling = 0
        for s in students:
            s_grades = all_grades.get(s.id, [])
            s_avg = _avg_from_grades(s_grades)
            if s_grades:
                total_avg += s_avg
                count += 1
                if s_avg < 3.5:
                    struggling += 1
        avg = round(total_avg / count, 2) if count else 0
        class_stats.append({
            "classId": cid,
            "students": len(students),
            "avg": avg,
            "struggling": struggling,
        })

    class_stats.sort(key=lambda x: x["avg"], reverse=True)

    total_students = sum(cs["students"] for cs in class_stats)
    overall_avg = (
        round(sum(cs["avg"] * cs["students"] for cs in class_stats) / total_students, 2)
        if total_students else 0
    )

    teachers = [
        {"id": d.id, **d.to_dict()}
        for d in c.collection("users").where("role", "==", "teacher").stream()
    ]

    return {
        "ok": True,
        "school": {
            "id": school_id or "65-maktab",
            "name": "65-maktab",
            "students": total_students,
            "classes": len(class_stats),
            "avg": overall_avg,
        },
        "classes": class_stats,
        "teachers": teachers[:10],
    }


# ============================================================
# O'QITUVCHI
# ============================================================
def teacher_dashboard(teacher_id: str) -> dict:
    c = db()
    tdoc = c.collection("users").document(teacher_id).get()
    if not tdoc.exists:
        return {"ok": False, "message": "Topilmadi"}
    teacher = tdoc.to_dict()

    class_ids = teacher.get("classIds", [])
    subject = teacher.get("subject", "")

    result_classes = []
    for cid in class_ids:
        students = list(c.collection("students").where("classId", "==", cid).stream())
        s_ids = [s.id for s in students]
        grades_map = _batch_grades(s_ids)
        scores_all = []
        for sid, grades in grades_map.items():
            if subject:
                grades = [g for g in grades if g.get("subject") == subject]
            scores_all.extend([g["score"] for g in grades if g.get("score") is not None])
        avg = round(sum(scores_all) / len(scores_all), 2) if scores_all else 0
        result_classes.append({
            "classId": cid,
            "students": len(students),
            "avg": avg,
        })

    return {
        "ok": True,
        "teacher": {
            "id": teacher_id,
            "fullName": teacher.get("fullName", ""),
            "subject": subject,
        },
        "classes": result_classes,
    }


# ============================================================
# BOSH ADMIN
# ============================================================
def bosh_admin_dashboard() -> dict:
    c = db()

    schools_count = len(list(c.collection("schools").stream()))
    students_count = len(list(c.collection("students").stream()))
    users_count = len(list(c.collection("users").stream()))
    bot_connected = len(
        list(c.collection("bot_users").where("status", "==", "connected").stream())
    )

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    payments = list(c.collection("payments").where("status", "==", "paid").stream())
    monthly_income = 0
    for p in payments:
        d = p.to_dict()
        paid_at = d.get("paidAt")
        if paid_at and hasattr(paid_at, "timestamp") and paid_at >= month_start:
            monthly_income += d.get("amount", 0)

    deletion_requests = len(
        list(c.collection("deletion_requests").where("status", "==", "pending").stream())
    )

    return {
        "ok": True,
        "stats": {
            "schools": schools_count,
            "students": students_count,
            "users": users_count,
            "botConnected": bot_connected,
            "monthlyIncome": monthly_income,
            "deletionRequests": deletion_requests,
        },
    }