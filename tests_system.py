"""Testlar tizimi — sinfga qarab qiyinlik, avtomatik baholash, ball."""

import logging
import random
from datetime import datetime, timezone

from firebase_client import db

log = logging.getLogger("tests")


# ============================================================
# Standart testlar (seed)
# ============================================================
def _get_sample_tests() -> list[dict]:
    """Testlar namunasi — sinfga qarab 3 xil qiyinlik."""
    return [
        # ============ MATEMATIKA ============
        {
            "testId": "math_easy_01",
            "subject": "Matematika",
            "classRange": [5, 6],
            "difficulty": "easy",
            "reward": 15,
            "questions": [
                {"q": "5 + 7 = ?", "options": ["10", "11", "12", "13"], "correct": 2},
                {"q": "12 - 4 = ?", "options": ["6", "7", "8", "9"], "correct": 2},
                {"q": "3 × 4 = ?", "options": ["10", "11", "12", "14"], "correct": 2},
                {"q": "20 ÷ 4 = ?", "options": ["4", "5", "6", "8"], "correct": 1},
                {"q": "7 + 8 = ?", "options": ["13", "14", "15", "16"], "correct": 2},
            ],
        },
        {
            "testId": "math_medium_01",
            "subject": "Matematika",
            "classRange": [7, 8],
            "difficulty": "medium",
            "reward": 20,
            "questions": [
                {"q": "2x + 5 = 13, x = ?", "options": ["3", "4", "5", "6"], "correct": 1},
                {"q": "x² = 49, x = ?", "options": ["5", "6", "7", "8"], "correct": 2},
                {"q": "(-3)² = ?", "options": ["-9", "6", "9", "12"], "correct": 2},
                {"q": "√144 = ?", "options": ["10", "11", "12", "13"], "correct": 2},
                {"q": "25% of 80 = ?", "options": ["15", "20", "25", "30"], "correct": 1},
            ],
        },
        {
            "testId": "math_hard_01",
            "subject": "Matematika",
            "classRange": [9, 11],
            "difficulty": "hard",
            "reward": 25,
            "questions": [
                {"q": "log₂(32) = ?", "options": ["4", "5", "6", "7"], "correct": 1},
                {"q": "sin(30°) = ?", "options": ["0", "0.5", "1", "√3/2"], "correct": 1},
                {"q": "C(5,2) = ?", "options": ["5", "10", "15", "20"], "correct": 1},
                {"q": "lim x→0 (sin x / x) = ?", "options": ["0", "1", "∞", "Mavjud emas"], "correct": 1},
                {"q": "f(x) = x³, f'(2) = ?", "options": ["6", "8", "10", "12"], "correct": 3},
            ],
        },

        # ============ FIZIKA ============
        {
            "testId": "physics_medium_01",
            "subject": "Fizika",
            "classRange": [7, 9],
            "difficulty": "medium",
            "reward": 20,
            "questions": [
                {"q": "Tezlik formulasi?", "options": ["v = s/t", "v = s×t", "v = t/s", "v = s+t"], "correct": 0},
                {"q": "1 km necha metr?", "options": ["100", "1000", "10000", "100000"], "correct": 1},
                {"q": "Nyuton 2-qonuni?", "options": ["F = ma", "F = m/a", "F = a/m", "F = m+a"], "correct": 0},
                {"q": "Erkin tushish tezlanishi?", "options": ["9.8", "10.8", "8.9", "11"], "correct": 0},
                {"q": "1 soat necha sekund?", "options": ["60", "600", "3600", "36000"], "correct": 2},
            ],
        },
        {
            "testId": "physics_hard_01",
            "subject": "Fizika",
            "classRange": [9, 11],
            "difficulty": "hard",
            "reward": 25,
            "questions": [
                {"q": "Foton energiyasi formulasi?", "options": ["E = hf", "E = mc²", "E = ½mv²", "E = mgh"], "correct": 0},
                {"q": "Om qonuni?", "options": ["I = U/R", "I = UR", "I = R/U", "I = U+R"], "correct": 0},
                {"q": "Plank doimiysi?", "options": ["6.626×10⁻³⁴", "3×10⁸", "1.6×10⁻¹⁹", "9.8"], "correct": 0},
                {"q": "Yorug'lik tezligi?", "options": ["3×10⁶", "3×10⁷", "3×10⁸", "3×10⁹"], "correct": 2},
                {"q": "Elektr zaryadi birligi?", "options": ["Amper", "Volt", "Om", "Kulon"], "correct": 3},
            ],
        },

        # ============ INGLIZ TILI ============
        {
            "testId": "english_easy_01",
            "subject": "Ingliz tili",
            "classRange": [5, 7],
            "difficulty": "easy",
            "reward": 15,
            "questions": [
                {"q": "I ___ a student.", "options": ["am", "is", "are", "be"], "correct": 0},
                {"q": "She ___ from Uzbekistan.", "options": ["am", "is", "are", "be"], "correct": 1},
                {"q": "They ___ friends.", "options": ["am", "is", "are", "be"], "correct": 2},
                {"q": "Plural of 'child'?", "options": ["childs", "childes", "children", "child"], "correct": 2},
                {"q": "'Kitob' inglizcha?", "options": ["pen", "book", "table", "chair"], "correct": 1},
            ],
        },
        {
            "testId": "english_medium_01",
            "subject": "Ingliz tili",
            "classRange": [8, 11],
            "difficulty": "medium",
            "reward": 20,
            "questions": [
                {"q": "Past Simple: I ___ (go) to school.", "options": ["go", "goed", "went", "gone"], "correct": 2},
                {"q": "Present Perfect: She ___ finished.", "options": ["has", "have", "had", "is"], "correct": 0},
                {"q": "Conditional 2: If I ___ rich...", "options": ["am", "was", "were", "be"], "correct": 2},
                {"q": "Passive: The book ___ written.", "options": ["is", "was", "were", "are"], "correct": 1},
                {"q": "Reported: He said he ___ tired.", "options": ["is", "was", "were", "be"], "correct": 1},
            ],
        },

        # ============ KIMYO ============
        {
            "testId": "chem_medium_01",
            "subject": "Kimyo",
            "classRange": [8, 9],
            "difficulty": "medium",
            "reward": 20,
            "questions": [
                {"q": "Suv formulasi?", "options": ["H₂O", "H₂O₂", "HO", "H₃O"], "correct": 0},
                {"q": "Kislorod belgisi?", "options": ["K", "O", "H", "N"], "correct": 1},
                {"q": "CO₂ nomi?", "options": ["Karbonat", "Karbonat angidrid", "Kislorod", "Vodorod"], "correct": 1},
                {"q": "D.I. Mendeleyev — ?", "options": ["Fizik", "Kimyogar", "Biolog", "Matematik"], "correct": 1},
                {"q": "pH = 7 — bu?", "options": ["Kislota", "Neytral", "Asos", "Tuz"], "correct": 1},
            ],
        },

        # ============ BIOLOGIYA ============
        {
            "testId": "bio_easy_01",
            "subject": "Biologiya",
            "classRange": [6, 8],
            "difficulty": "easy",
            "reward": 15,
            "questions": [
                {"q": "O'simliklar qanday nafas oladi?", "options": ["Fotosintez", "Kislorod", "CO₂", "Azot"], "correct": 1},
                {"q": "Inson yuragi necha kamerali?", "options": ["2", "3", "4", "5"], "correct": 2},
                {"q": "Qon rangini beradi?", "options": ["Gemoglobin", "Xlorofill", "Melanin", "Insulin"], "correct": 0},
                {"q": "DNK qayerda?", "options": ["Sitoplazma", "Yadro", "Membrana", "Mitoxondriya"], "correct": 1},
                {"q": "Eng katta organ?", "options": ["Jigar", "Yurak", "Teri", "Miya"], "correct": 2},
            ],
        },

        # ============ TARIX ============
        {
            "testId": "history_medium_01",
            "subject": "Tarix",
            "classRange": [8, 11],
            "difficulty": "medium",
            "reward": 20,
            "questions": [
                {"q": "O'zbekiston mustaqillik yili?", "options": ["1990", "1991", "1992", "1993"], "correct": 1},
                {"q": "Amir Temur yili?", "options": ["1336-1405", "1330-1400", "1340-1410", "1325-1395"], "correct": 0},
                {"q": "Birinchi Prezident?", "options": ["Sh. Mirziyoyev", "I. Karimov", "N. Nazarboyev", "S. Niyozov"], "correct": 1},
                {"q": "Registon — qayerda?", "options": ["Buxoro", "Samarqand", "Xiva", "Toshkent"], "correct": 1},
                {"q": "Buyuk ipak yo'li boshlanishi?", "options": ["Xitoy", "Hindiston", "Rim", "Fors"], "correct": 0},
            ],
        },
    ]


# ============================================================
# SEED
# ============================================================
def seed_tests(force: bool = False) -> dict:
    """Testlarni Firestore'ga yozish."""
    c = db()
    existing = list(c.collection("tests").stream())

    if existing and not force:
        return {"ok": True, "created": 0, "existing": len(existing)}

    created = 0
    for t in _get_sample_tests():
        ref = c.collection("tests").document(t["testId"])
        if ref.get().exists and not force:
            continue
        ref.set({
            **t,
            "active": True,
            "createdAt": datetime.now(timezone.utc),
        })
        created += 1

    log.info("[TESTS] %s ta test yaratildi", created)
    return {"ok": True, "created": created}


# ============================================================
# RO'YXAT
# ============================================================
def list_tests_for_class(class_id: str) -> list[dict]:
    """Sinfga mos testlarni olish (sinf raqamiga qarab)."""
    try:
        # "9-A" → 9
        class_num = int("".join(c for c in class_id if c.isdigit()))
    except (ValueError, TypeError):
        class_num = 9

    docs = list(db().collection("tests").where("active", "==", True).stream())
    result = []
    for d in docs:
        data = d.to_dict()
        cr = data.get("classRange", [1, 11])
        if cr[0] <= class_num <= cr[1]:
            # Savollarni to'g'ri javobsiz qaytaramiz
            qs = data.get("questions", [])
            safe_qs = [
                {"q": q["q"], "options": q["options"]}
                for q in qs
            ]
            result.append({
                "testId": d.id,
                "subject": data.get("subject"),
                "difficulty": data.get("difficulty"),
                "reward": data.get("reward"),
                "questionCount": len(qs),
                "questions": safe_qs,
            })
    return result


def get_test(test_id: str, include_answers: bool = False) -> dict | None:
    """Testni olish."""
    doc = db().collection("tests").document(test_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    if not include_answers:
        data["questions"] = [
            {"q": q["q"], "options": q["options"]}
            for q in data.get("questions", [])
        ]
    return {"id": doc.id, **data}


# ============================================================
# TEST TOPSHIRISH
# ============================================================
def submit_test(user_id: str, test_id: str, answers: list[int]) -> dict:
    """Test javoblarini qabul qilish va baholash."""
    c = db()
    now = datetime.now(timezone.utc)

    # Testni olish (javoblar bilan)
    test = get_test(test_id, include_answers=True)
    if not test:
        return {"ok": False, "message": "Test topilmadi"}

    questions = test.get("questions", [])
    total = len(questions)
    if total == 0:
        return {"ok": False, "message": "Test savollari yo'q"}

    if len(answers) != total:
        return {"ok": False, "message": f"{total} ta javob kerak"}

    # Baholash
    correct = 0
    detailed = []
    for i, q in enumerate(questions):
        is_correct = answers[i] == q["correct"]
        if is_correct:
            correct += 1
        detailed.append({
            "question": q["q"],
            "your_answer": q["options"][answers[i]] if 0 <= answers[i] < len(q["options"]) else "—",
            "correct_answer": q["options"][q["correct"]],
            "is_correct": is_correct,
        })

    percent = round(correct / total * 100)
    passed = percent >= 60
    reward = test.get("reward", 0) if passed else 0

    # Saqlash
    attempt_ref = c.collection("test_attempts").document()
    attempt_ref.set({
        "userId": user_id,
        "testId": test_id,
        "subject": test.get("subject"),
        "score": correct,
        "total": total,
        "percent": percent,
        "passed": passed,
        "reward": reward,
        "answers": answers,
        "detailed": detailed,
        "startedAt": now,
        "finishedAt": now,
        "weekly": test.get("weekly", False),
    })

    # Umumiy ballga qo'shish
    if passed and reward > 0:
        from firebase_admin import firestore as fs
        c.collection("users").document(user_id).set({
            "totalScore": fs.Increment(reward),
            "updatedAt": now,
        }, merge=True)

    # Task tekshirish
    from tasks import check_auto_tasks
    check_auto_tasks(user_id)

    log.info("[TEST] %s → %s: %s/%s (%s%%)", user_id[:12], test_id, correct, total, percent)

    return {
        "ok": True,
        "score": correct,
        "total": total,
        "percent": percent,
        "passed": passed,
        "reward": reward,
        "detailed": detailed,
    }


def get_user_attempts(user_id: str, limit: int = 20) -> list[dict]:
    """Foydalanuvchining test urinishlari."""
    docs = list(
        db().collection("test_attempts")
        .where("userId", "==", user_id)
        .stream()
    )
    docs.sort(key=lambda d: d.to_dict().get("finishedAt") or 0, reverse=True)
    return [{"id": d.id, **d.to_dict()} for d in docs[:limit]]


def get_user_test_stats(user_id: str) -> dict:
    """Statistika."""
    attempts = get_user_attempts(user_id, limit=1000)
    if not attempts:
        return {"total": 0, "passed": 0, "avg_percent": 0, "total_reward": 0}

    passed = sum(1 for a in attempts if a.get("passed"))
    avg_percent = round(sum(a.get("percent", 0) for a in attempts) / len(attempts))
    total_reward = sum(a.get("reward", 0) for a in attempts)

    return {
        "total": len(attempts),
        "passed": passed,
        "avg_percent": avg_percent,
        "total_reward": total_reward,
    }