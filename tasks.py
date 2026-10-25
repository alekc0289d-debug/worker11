"""Topshiriqlar tizimi — ketma-ket bajariladi, umumiy ballga ta'sir qiladi.

Qoidalar:
- Har bir topshiriq `order` bilan tartiblangan (1, 2, 3...)
- User faqat KEYINGI topshiriqni ko'radi va bajaradi
- Oldingisi bajarilmaguncha keyingisi "locked"
- Bajarilgach keyingisi "available" bo'ladi
- Umumiy ball = barcha bajarilgan topshiriqlar reward yig'indisi
"""

import logging
from datetime import datetime, timezone

from firebase_client import db

log = logging.getLogger("tasks")

# ============================================================
# Standart topshiriqlar — bir marta seed qilinadi
# ============================================================
DEFAULT_TASKS = [
    {
        "order": 1,
        "title": "Oilaviy botga ulanish",
        "desc": "Telegram botga ulanib, telefon raqamingizni tasdiqlang",
        "reward": 10,
        "type": "auto",
        "check": {"event": "bot_connected"},
    },
    {
        "order": 2,
        "title": "Birinchi testni yechish",
        "desc": "Istalgan fandan test yechib, kamida 60% to'plang",
        "reward": 15,
        "type": "test",
        "check": {"min_percent": 60, "any_subject": True},
    },
    {
        "order": 3,
        "title": "Matematikadan 9 ball olish",
        "desc": "Matematika fanidan 9 ball oling (nazorat ishi)",
        "reward": 20,
        "type": "grade",
        "check": {"subject": "Matematika", "min_score": 9},
    },
    {
        "order": 4,
        "title": "Guruhda faol bo'lish",
        "desc": "Sinf guruhida 10 ta xabar yozing",
        "reward": 10,
        "type": "custom",
        "check": {"min_messages": 10},
    },
    {
        "order": 5,
        "title": "Bir hafta davomat 100%",
        "desc": "Bir hafta davomida darslarni qoldirmang",
        "reward": 25,
        "type": "auto",
        "check": {"days": 7, "attendance": 100},
    },
    {
        "order": 6,
        "title": "3 ta fandan o'rtacha 4.5",
        "desc": "Istalgan 3 ta fandan o'rtacha ballingiz 4.5 dan yuqori bo'lsin",
        "reward": 20,
        "type": "grade",
        "check": {"subjects_count": 3, "min_avg": 4.5},
    },
    {
        "order": 7,
        "title": "Do'stingizni taklif qiling",
        "desc": "Do'stingizni botga taklif qiling (referral link orqali)",
        "reward": 30,
        "type": "custom",
        "check": {"min_referrals": 1},
    },
    {
        "order": 8,
        "title": "Haftalik testda 80%+",
        "desc": "Haftalik umumiy testda 80% dan yuqori natija",
        "reward": 25,
        "type": "test",
        "check": {"min_percent": 80, "weekly": True},
    },
    {
        "order": 9,
        "title": "Ota-onani botga ulash",
        "desc": "Ota-onangizdan birini botga taklif qiling",
        "reward": 15,
        "type": "custom",
        "check": {"parent_connected": True},
    },
    {
        "order": 10,
        "title": "AI yordamchidan foydalanish",
        "desc": "AI yordamchidan 5 marta savol so'rang",
        "reward": 10,
        "type": "custom",
        "check": {"min_ai_calls": 5},
    },
]


# ============================================================
# SEED — topshiriqlarni Firestore'ga yozish
# ============================================================
def seed_default_tasks(force: bool = False) -> dict:
    """Standart topshiriqlarni yaratadi (agar yo'q bo'lsa)."""
    c = db()
    existing = list(c.collection("tasks").stream())

    if existing and not force:
        log.info("[TASKS] Allaqachon %s ta topshiriq mavjud", len(existing))
        return {"ok": True, "created": 0, "existing": len(existing)}

    created = 0
    for t in DEFAULT_TASKS:
        task_id = f"task_{t['order']:02d}"
        ref = c.collection("tasks").document(task_id)
        if ref.get().exists and not force:
            continue
        ref.set({
            **t,
            "taskId": task_id,
            "active": True,
            "createdAt": datetime.now(timezone.utc),
        })
        created += 1

    log.info("[TASKS] %s ta topshiriq yaratildi", created)
    return {"ok": True, "created": created}


def list_tasks() -> list[dict]:
    """Barcha faol topshiriqlar (order bo'yicha)."""
    docs = list(db().collection("tasks").where("active", "==", True).stream())
    tasks = [{"id": d.id, **d.to_dict()} for d in docs]
    tasks.sort(key=lambda t: t.get("order", 0))
    return tasks


# ============================================================
# USER TASKS — holatni hisoblash
# ============================================================
def _user_task_id(user_id: str, task_id: str) -> str:
    return f"{user_id}__{task_id}"


def get_user_tasks(user_id: str) -> list[dict]:
    """
    Foydalanuvchining barcha topshiriqlari holati.

    Mantiq:
      - 1-topshiriq doimo "available"
      - Qolganlari: oldingisi "done" bo'lsa — "available", aks holda "locked"
      - Bajarilganlar: "done"
    """
    c = db()
    tasks = list_tasks()
    if not tasks:
        return []

    # Foydalanuvchining bajargan topshiriqlari
    done_map = {}
    for d in c.collection("user_tasks").where("userId", "==", user_id).stream():
        data = d.to_dict()
        if data.get("status") == "done":
            done_map[data.get("taskId")] = data

    result = []
    previous_done = True  # 1-topshiriq uchun boshlang'ich ruxsat

    for t in tasks:
        task_id = t["taskId"]
        if task_id in done_map:
            result.append({
                **t,
                "status": "done",
                "completedAt": done_map[task_id].get("completedAt"),
                "reward": done_map[task_id].get("reward", t.get("reward", 0)),
            })
            previous_done = True
        elif previous_done:
            result.append({**t, "status": "available"})
            previous_done = False  # keyingisini bloklaymiz
        else:
            result.append({**t, "status": "locked"})

    return result


def get_next_task(user_id: str) -> dict | None:
    """Keyingi bajarilishi mumkin bo'lgan topshiriq."""
    for t in get_user_tasks(user_id):
        if t["status"] == "available":
            return t
    return None


# ============================================================
# BAJARISH
# ============================================================
def complete_task(user_id: str, task_id: str, proof: dict | None = None) -> dict:
    """Topshiriqni bajarilgan deb belgilash (faqat ruxsat bo'lsa)."""
    c = db()
    now = datetime.now(timezone.utc)

    # Tekshirish: topshiriq ruxsat etilganmi?
    current = get_user_tasks(user_id)
    target = next((t for t in current if t["taskId"] == task_id), None)

    if not target:
        return {"ok": False, "message": "Topshiriq topilmadi"}

    if target["status"] == "done":
        return {"ok": False, "message": "Allaqachon bajarilgan"}

    if target["status"] == "locked":
        return {"ok": False, "message": "Avval oldingi topshiriqni bajaring"}

    # Yozish
    doc_id = _user_task_id(user_id, task_id)
    c.collection("user_tasks").document(doc_id).set({
        "userId": user_id,
        "taskId": task_id,
        "status": "done",
        "reward": target.get("reward", 0),
        "completedAt": now,
        "proof": proof or {},
    })

    # Umumiy ballga qo'shish
    _add_to_total_score(user_id, target.get("reward", 0))

    # Log
    c.collection("task_logs").add({
        "userId": user_id,
        "taskId": task_id,
        "reward": target.get("reward", 0),
        "timestamp": now,
    })

    log.info("[TASK] %s → %s (+%s ball)", user_id[:12], task_id, target.get("reward"))

    # Keyingi topshiriqni "available" qilish kerak emas — get_user_tasks o'zi hisoblaydi
    return {"ok": True, "reward": target.get("reward", 0)}


def _add_to_total_score(user_id: str, points: int):
    """Umumiy ballni yangilash."""
    from firebase_admin import firestore as fs
    db().collection("users").document(user_id).set({
        "totalScore": fs.Increment(points),
        "updatedAt": datetime.now(timezone.utc),
    }, merge=True)


# ============================================================
# AVTOMATIK TEKSHIRISH
# ============================================================
def check_auto_tasks(user_id: str) -> list[dict]:
    """
    Avtomatik topshiriqlarni tekshirish va bajarish.

    Chaqiriladigan joylar:
      - Bot ulanishi → task 1
      - Test yakunlanganda → task 2, 8
      - Grade sync'dan keyin → task 3, 6
      - Haftalik cron → task 5
    """
    completed = []
    c = db()

    for t in get_user_tasks(user_id):
        if t["status"] != "available":
            continue

        if t["type"] == "auto":
            if _check_auto(user_id, t):
                complete_task(user_id, t["taskId"], proof={"auto": True})
                completed.append(t["taskId"])

        elif t["type"] == "test":
            if _check_test(user_id, t):
                complete_task(user_id, t["taskId"], proof={"test": True})
                completed.append(t["taskId"])

        elif t["type"] == "grade":
            if _check_grade(user_id, t):
                complete_task(user_id, t["taskId"], proof={"grade": True})
                completed.append(t["taskId"])

    return completed


def _check_auto(user_id: str, task: dict) -> bool:
    """type=auto tekshiruv."""
    check = task.get("check", {})
    event = check.get("event")

    if event == "bot_connected":
        u = db().collection("users").document(user_id).get()
        if u.exists and u.to_dict().get("botStatus") == "connected":
            return True

    if event == "attendance_week":
        # Haftalik davomatni tekshirish
        # TODO: davomat moduli qo'shilganda
        pass

    return False


def _check_test(user_id: str, task: dict) -> bool:
    """type=test tekshiruv — test_attempts'dan."""
    check = task.get("check", {})
    min_percent = check.get("min_percent", 60)
    weekly = check.get("weekly", False)

    attempts = list(
        db().collection("test_attempts")
        .where("userId", "==", user_id)
        .stream()
    )

    for a in attempts:
        d = a.to_dict()
        score = d.get("score", 0)
        total = d.get("total", 1)
        if total > 0 and (score / total * 100) >= min_percent:
            if weekly and not d.get("weekly"):
                continue
            return True
    return False


def _check_grade(user_id: str, task: dict) -> bool:
    """type=grade tekshiruv — grades kolleksiyasidan."""
    check = task.get("check", {})
    c = db()

    # Bitta fandan aniq ball
    if "subject" in check and "min_score" in check:
        subject = check["subject"]
        min_score = check["min_score"]
        for g in c.collection("grades").where("studentId", "==", user_id).stream():
            d = g.to_dict()
            if d.get("subject") == subject and (d.get("score") or 0) >= min_score:
                return True

    # Bir nechta fandan o'rtacha
    if "subjects_count" in check and "min_avg" in check:
        min_count = check["subjects_count"]
        min_avg = check["min_avg"]

        subj_scores = {}
        for g in c.collection("grades").where("studentId", "==", user_id).stream():
            d = g.to_dict()
            subj = d.get("subject")
            score = d.get("score")
            if subj and score is not None:
                subj_scores.setdefault(subj, []).append(score)

        qualified = 0
        for subj, scores in subj_scores.items():
            if not scores:
                continue
            avg = sum(scores) / len(scores)
            if avg >= min_avg:
                qualified += 1

        if qualified >= min_count:
            return True

    return False


# ============================================================
# BALL HISOBLASH
# ============================================================
def get_user_total_score(user_id: str) -> dict:
    """Foydalanuvchining umumiy balli va tafsiloti."""
    c = db()
    tasks = get_user_tasks(user_id)

    task_points = sum(
        t.get("reward", 0) for t in tasks if t["status"] == "done"
    )

    # Testlar
    test_points = 0
    for d in c.collection("test_attempts").where("userId", "==", user_id).stream():
        data = d.to_dict()
        if data.get("passed"):
            test_points += data.get("reward", 0)

    # Baholardan
    grade_points = _compute_grade_points(user_id)

    total = task_points + test_points + grade_points

    return {
        "total": total,
        "tasks": task_points,
        "tests": test_points,
        "grades": grade_points,
        "tasks_done": sum(1 for t in tasks if t["status"] == "done"),
        "tasks_total": len(tasks),
    }


def _compute_grade_points(user_id: str) -> int:
    """Baholardan ball hisoblash.
    Qoida: har bir '5' → 2 ball, '4' → 1 ball
    """
    c = db()
    points = 0
    for g in c.collection("grades").where("studentId", "==", user_id).stream():
        d = g.to_dict()
        if d.get("source") != "emaktab":
            continue
        score = d.get("score")
        if score == 5:
            points += 2
        elif score == 4:
            points += 1
    return points