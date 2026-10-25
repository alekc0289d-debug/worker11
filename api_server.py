"""Maktabim+ API — FastAPI. To'liq versiya (v16.0)."""

import hmac
import json
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import firestore
from pydantic import BaseModel

# --- Core ---
from config import settings
from crypto import decrypt
from captcha_flow import process_answered
from emaktab import login, fetch_data, CaptchaRequired, LoginFailed
from firebase_client import (
    BatchWriter, db, save_credentials, save_sync,
    save_captcha_to_queue, mark_error, read_credentials,
    check_login_exists,
)

# --- Auth ---
from auth import (
    create_user, login as auth_login, verify_token, logout as auth_logout,
    clean_phone, _hash_password, user_exists_by_phone,
    request_password_reset,
)

# --- Modullar ---
from payments import (
    mark_paid, unmark_paid, class_report,
    submit_weekly_report, list_weekly_reports,
    submit_collected_money, receive_submission,
)
from prizes import (
    compute_class_ranking, compute_school_ranking,
    generate_monthly_prizes, choose_prize,
    mark_prize_given, list_pending_prizes, list_awaiting_choice,
)
from schedule import save_class_schedule, get_class_schedule
from tasks import (
    seed_default_tasks, list_tasks, get_user_tasks,
    get_next_task, complete_task, check_auto_tasks,
    get_user_total_score,
)
from tests_system import (
    seed_tests, list_tests_for_class, get_test,
    submit_test, get_user_attempts, get_user_test_stats,
)
from news import (
    create_news, update_news, delete_news,
    list_news, get_news, get_categories, get_priorities,
)
from comments import add_comment, list_comments, delete_comment
from bot_users import (
    get_by_user_id, list_pending, list_blocked,
    list_by_class, list_unregistered_students,
    set_class_group, get_class_group, list_all_groups,
)
from bot_status import get_bot_status_overview
from classes import (
    list_classes, get_class, create_class, update_class,
    delete_class, toggle_active,
)
from dashboard_api import (
    student_dashboard, parent_dashboard,
    teacher_dashboard, director_dashboard,
    bosh_admin_dashboard,
)
from users_api import (
    list_users, get_user_details, update_user_role, delete_user,
    class_students, get_student_detail, update_student, delete_student,
    promote_to_class_admin, get_student_grades_paginated,
)
from chat import send_message, list_messages, delete_message as delete_chat_msg
from settings import (
    get_settings, update_settings, is_registration_enabled,
    get_user_preferences, update_user_preferences,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")


# ============================================================
# LIFESPAN
# ============================================================
def _seed_on_startup():
    try:
        seed_default_tasks()
        seed_tests()
    except Exception:
        pass

@asynccontextmanager
async def lifespan(_app):
    scheduler.start()
    _seed_on_startup()
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(title="Maktabim+ API", version="16.0", lifespan=lifespan)

_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "PUT"],
    allow_headers=["Content-Type", "X-Admin-Token", "X-User-Token"],
)

tasks_state = {}
_task_ts = {}
_TASK_TTL = 3600
_register_slots = threading.BoundedSemaphore(2)


# ============================================================
# AUTH GUARDS & HELPERS
# ============================================================
def require_admin(x_admin_token: str = Header(default="")):
    expected = settings.api_admin_token
    if not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(401, "Ruxsat yo'q")

def require_user(x_user_token: str = Header(default="")):
    if not x_user_token: raise HTTPException(401, "Token yuborilmagan")
    info = verify_token(x_user_token)
    if not info: raise HTTPException(401, "Token yaroqsiz")
    doc = db().collection("users").document(info["userId"]).get()
    if not doc.exists: raise HTTPException(404, "Foydalanuvchi topilmadi")
    d = doc.to_dict()
    return {
        "id": doc.id, "role": d.get("role", "student"),
        "roles": d.get("roles", [d.get("role", "student")]),
        "fullName": d.get("fullName", ""), "classId": d.get("classId", ""),
        "phone": d.get("phone", ""),
    }

def require_role(allowed_roles: list):
    def dep(user=Depends(require_user)):
        if user["role"] not in allowed_roles:
            raise HTTPException(403, "Ruxsat yo'q")
        return user
    return dep

def _purge_tasks():
    now = time.time()
    for tid in [t for t, ts in _task_ts.items() if now - ts > _TASK_TTL]:
        tasks_state.pop(tid, None)
        _task_ts.pop(tid, None)

def _run_register(task_id, req):
    set_status(task_id, "queue", "Navbatda...", 1)
    with _register_slots:
        do_register(task_id, req)


# ============================================================
# PYDANTIC MODELLAR
# ============================================================
class RegisterRequest(BaseModel):
    fullName: str = ""
    login: str
    password: str
    phone: str
    motherPhone: str
    fatherPhone: str = ""
    classId: str = ""
    consent: bool = False

class LoginRequest(BaseModel):
    phone: str
    password: str

class TelegramLoginRequest(BaseModel):
    telegramId: int

class UpdateEmaktabRequest(BaseModel):
    userId: str
    login: str
    password: str

class LogoutRequest(BaseModel):
    token: str

class ResetPasswordRequest(BaseModel):
    phone: str

class ChangePasswordRequest(BaseModel):
    userId: str
    oldPassword: str
    newPassword: str

class UpdateProfileRequest(BaseModel):
    userId: str
    fullName: str

class UserPrefsRequest(BaseModel):
    theme: str = ""
    lang: str = ""

class MarkPaidRequest(BaseModel):
    studentId: str
    year: int
    collectedBy: str
    notes: str = ""

class WeeklyReportRequest(BaseModel):
    classId: str
    year: int
    week: int
    submittedBy: str
    notes: str = ""

class SubmitMoneyRequest(BaseModel):
    classId: str
    year: int
    week: int
    submittedBy: str

class ReceiveSubmissionRequest(BaseModel):
    submissionId: str
    receivedBy: str

class ChoosePrizeRequest(BaseModel):
    prizeId: str
    choice: str
    telegramUsername: str = ""

class MarkPrizeGivenRequest(BaseModel):
    prizeId: str
    givenBy: str
    notes: str = ""

class ScheduleRequest(BaseModel):
    classId: str
    days: dict
    enteredBy: str

class CompleteTaskRequest(BaseModel):
    userId: str
    taskId: str
    proof: dict = {}

class SubmitTestRequest(BaseModel):
    userId: str
    testId: str
    answers: list

class NewsCreateRequest(BaseModel):
    authorId: str = ""
    authorRole: str = ""
    title: str
    content: str
    category: str = "umumiy"
    priority: str = "orta"
    imageUrl: str = ""
    pinned: bool = False

class NewsUpdateRequest(BaseModel):
    newsId: str
    authorId: str = ""
    authorRole: str = ""
    title: str | None = None
    content: str | None = None
    category: str | None = None
    priority: str | None = None
    imageUrl: str | None = None
    pinned: bool | None = None
    published: bool | None = None

class CommentRequest(BaseModel):
    newsId: str
    text: str

class SetGroupRequest(BaseModel):
    classId: str
    groupId: int
    groupName: str
    setBy: int

class DeletionRequest(BaseModel):
    userId: str = ""
    fullName: str = ""
    classId: str = ""
    reason: str

class DeletionDecision(BaseModel):
    userId: str
    adminId: str = ""
    decision: str
    notes: str = ""

class StaffInfo(BaseModel):
    fullName: str
    phone: str
    telegramId: int | None = None

class ClassCreateRequest(BaseModel):
    classId: str
    description: str = ""
    classTeacher: StaffInfo | None = None
    classAdmin: StaffInfo | None = None

class ClassDeleteRequest(BaseModel):
    classId: str
    byRole: str = ""

class ClassToggleRequest(BaseModel):
    classId: str
    byRole: str = ""

class RoleUpdateRequest(BaseModel):
    userId: str
    newRole: str

class StudentUpdateRequest(BaseModel):
    studentId: str
    fullName: str | None = None
    phone: str | None = None
    motherPhone: str | None = None
    fatherPhone: str | None = None
    classId: str | None = None

class SendMessageRequest(BaseModel):
    userId: str = ""
    classId: str = ""
    text: str

class SettingsUpdateRequest(BaseModel):
    registrationEnabled: bool | None = None
    registrationDisabledMessage: str | None = None
    syncEnabled: bool | None = None

class PromoteClassAdminRequest(BaseModel):
    studentId: str


# ============================================================
# STATUS & REGISTER LOGIC
# ============================================================
def set_status(task_id, step, message, progress, status="processing"):
    data = {
        "taskId": task_id, "status": status, "step": step,
        "message": message, "progress": progress,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    tasks_state[task_id] = {
        "status": status, "step": step, "message": message,
        "progress": progress, "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        ref = db().collection("register_tasks").document(task_id)
        if not ref.get().exists:
            data["createdAt"] = firestore.SERVER_TIMESTAMP
        ref.set(data, merge=True)
    except Exception:
        pass

def do_register(task_id, req):
    try:
        set_status(task_id, "check", "Login tekshirilmoqda...", 5)
        if check_login_exists(req.login):
            set_status(task_id, "error", "Bu login allaqachon ro'yxatdan o'tgan.", 0, "error")
            return

        set_status(task_id, "login", "eMaktab'ga tekshirilmoqda...", 15)
        try:
            lr = login(req.login, req.password)
            cookies = lr.cookies
            set_status(task_id, "login", "eMaktab parol to'g'ri", 30)
        except Exception as e:
            set_status(task_id, "error", f"Login xatolik: {type(e).__name__}", 0, "error")
            return

        set_status(task_id, "fetch", "Profil yuklanmoqda...", 50)
        try:
            data = fetch_data(cookies, fetch_grades=False)
        except Exception:
            set_status(task_id, "error", "Ma'lumot olib bo'lmadi.", 0, "error")
            return

        student_info = data.get("student", {})
        full_name = f"{student_info.get('firstName', '')} {student_info.get('lastName', '')}".strip() or req.fullName.strip()
        phone_clean = clean_phone(req.phone)
        mother_clean = clean_phone(req.motherPhone)
        father_clean = clean_phone(req.fatherPhone) if req.fatherPhone else ""

        set_status(task_id, "save", "Hisob yaratilmoqda...", 85)
        try:
            student_id = f"student_{uuid.uuid4().hex[:12]}"
            client = db()
            now = datetime.now(timezone.utc)
            class_id = req.classId or settings.class_id

            client.collection("students").document(student_id).set({
                "fullName": full_name, "classId": class_id,
                "phone": phone_clean, "motherPhone": mother_clean, "fatherPhone": father_clean,
                "status": "active", "syncEnabled": False,
                "emaktab": {
                    "personId": student_info.get("personId"), "userId": student_info.get("userId"),
                },
                "gradesCount": 0, "subjectsCount": 0, "scheduleCount": 0,
                "registeredAt": now, "createdAt": now, "updatedAt": now,
            })

            client.collection("users").document(student_id).set({
                "fullName": full_name, "role": "student", "roles": ["student"], "classId": class_id,
                "phone": phone_clean, "passwordHash": _hash_password(phone_clean),
                "botStatus": "pending", "totalScore": 0, "timezone": "Asia/Tashkent",
                "createdAt": now, "updatedAt": now,
            }, merge=True)

            save_credentials(student_id, req.login, req.password, cookies)

            client.collection("emaktab_queue").document(student_id).set({
                "studentId": student_id, "priority": 5, "nextAttempt": None,
                "syncEnabled": False,
            })
        except Exception as e:
            set_status(task_id, "error", f"Saqlashda xatolik: {type(e).__name__}", 0, "error")
            return

        set_status(task_id, "done", f"{full_name} ro'yxatdan o'tdi. Baholar direktor ishga tushirgach yuklanadi.", 100, "done")
        
        result_data = {"student_id": student_id, "student": {"fullName": full_name, "classId": class_id}}
        tasks_state[task_id]["result"] = result_data
        
        try:
            db().collection("register_tasks").document(task_id).set({"result": result_data, "status": "done"}, merge=True)
        except Exception:
            pass
    except Exception:
        set_status(task_id, "error", "Kutilmagan xatolik.", 0, "error")


# ============================================================
# SYNC LOGIC
# ============================================================
def sync_all_students(force: bool = False):
    st = get_settings()
    if not st.get("syncEnabled") and not force:
        return
    
    log.info("AUTO-SYNC boshlandi")
    try:
        client = db()
        students_snap = list(client.collection("students").stream())
        for sdoc in students_snap:
            sid = sdoc.id
            try:
                creds = read_credentials(sid)
                if creds.get("status") == "captcha_required": continue
                
                cookies = (json.loads(decrypt(creds["cookiesEncrypted"])) if creds.get("cookiesEncrypted") else [])
                method = "cookie"
                try:
                    result = fetch_data(cookies)
                except LoginFailed:
                    try:
                        lr = login(creds["login"], decrypt(creds["passwordEncrypted"]))
                        cookies = lr.cookies
                        method = "login"
                        result = fetch_data(cookies)
                        save_credentials(sid, creds["login"], decrypt(creds["passwordEncrypted"]), cookies)
                    except LoginFailed:
                        # Emaktab paroli o'zgargan!
                        log.warning("[%s] Emaktab paroli xato (o'zgargan)", sid[:12])
                        mark_error(sid, "password_changed", "Emaktab paroli o'zgargan. Yangilang.")
                        client.collection("students").document(sid).set({"syncEnabled": False}, merge=True)
                        continue
                
                save_sync(sid, result, method)
                check_auto_tasks(sid)
            except Exception as e:
                log.error("[%s] Sync xato: %s", sid[:12], e)
    except Exception:
        log.exception("Auto-sync xato")

def _process_captcha_answers():
    try:
        from main import sync_one
        process_answered(sync_one)
    except Exception:
        pass

def _monthly_prizes_cron():
    try:
        from datetime import date
        y, m, _ = date.today().isocalendar()
        generate_monthly_prizes(y, m)
    except Exception:
        pass

def _weekly_report_reminder():
    try:
        from datetime import date
        y, w, _ = date.today().isocalendar()
        log.info("[REPORT] Haftalik: %s-W%s", y, w)
    except Exception:
        pass

scheduler = BackgroundScheduler(timezone="Asia/Tashkent")
scheduler.add_job(sync_all_students, "cron", hour="*", minute=0, id="hourly_sync", max_instances=1, coalesce=True)
scheduler.add_job(_process_captcha_answers, "interval", minutes=5, id="captcha_answers", max_instances=1, coalesce=True)
scheduler.add_job(_monthly_prizes_cron, "cron", day=1, hour=9, minute=0, id="monthly_prizes", max_instances=1, coalesce=True)
scheduler.add_job(_weekly_report_reminder, "cron", day_of_week="mon", hour=8, minute=0, id="weekly_reminder", max_instances=1, coalesce=True)


# ============================================================
# ROUTES
# ============================================================
@app.get("/")
def root():
    return {"status": "ok", "syncEnabled": get_settings().get("syncEnabled", False)}

# --- AUTH ---
@app.post("/api/auth/login")
def api_login(req: LoginRequest):
    return auth_login(req.phone, req.password)

@app.get("/api/auth/me")
def api_me(user=Depends(require_user)):
    return user

@app.post("/api/auth/telegram-login")
def api_telegram_login(req: TelegramLoginRequest):
    c = db()
    users = list(c.collection("users").where("telegramId", "==", req.telegramId).limit(1).stream())
    if not users: raise HTTPException(404, "Topilmadi")
    doc = users[0]
    token = __import__("secrets").token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    c.collection("sessions").document(token).set({"userId": doc.id, "expiresAt": expires})
    return {"ok": True, "token": token}

@app.post("/api/auth/update-emaktab")
def api_update_emaktab(req: UpdateEmaktabRequest, user=Depends(require_user)):
    if req.userId != user["id"] and user["role"] != "bosh_admin":
        raise HTTPException(403, "Ruxsat yo'q")
    try:
        lr = login(req.login, req.password)
        save_credentials(req.userId, req.login, req.password, lr.cookies)
        db().collection("emaktab_creds").document(req.userId).set({"status": "active", "errorMessage": ""}, merge=True)
        db().collection("students").document(req.userId).set({"syncEnabled": True}, merge=True)
        return {"ok": True, "message": "Parol yangilandi va sinxronizatsiya yoqildi"}
    except Exception as e:
        return {"ok": False, "message": f"Xatolik: {str(e)}"}

@app.post("/api/auth/logout")
def api_logout(req: LogoutRequest):
    return auth_logout(req.token)

@app.post("/api/auth/forgot-password")
def api_forgot_password(req: ResetPasswordRequest):
    return request_password_reset(req.phone)

@app.post("/api/auth/change-password")
def api_change_password(req: ChangePasswordRequest, user=Depends(require_user)):
    from auth import _verify_password
    if req.userId != user["id"]: raise HTTPException(403, "Ruxsat yo'q")
    if len(req.newPassword) < 4: raise HTTPException(400, "Yangi parol kamida 4 belgi")
    c = db()
    doc = c.collection("users").document(req.userId).get()
    if not doc.exists: raise HTTPException(404, "Topilmadi")
    hashed = doc.to_dict().get("passwordHash", "")
    if not _verify_password(req.oldPassword, hashed): return {"ok": False, "message": "Hozirgi parol xato"}
    c.collection("users").document(req.userId).set({"passwordHash": _hash_password(req.newPassword), "updatedAt": datetime.now(timezone.utc)}, merge=True)
    return {"ok": True, "message": "Parol o'zgartirildi"}

@app.post("/api/users/update-profile")
def api_update_profile(req: UpdateProfileRequest, user=Depends(require_user)):
    if req.userId != user["id"] and user["role"] != "bosh_admin": raise HTTPException(403, "Ruxsat yo'q")
    db().collection("users").document(req.userId).set({"fullName": req.fullName.strip(), "updatedAt": datetime.now(timezone.utc)}, merge=True)
    return {"ok": True}

@app.get("/api/user/prefs")
def api_get_prefs(user=Depends(require_user)): return get_user_preferences(user["id"])

@app.post("/api/user/prefs")
def api_update_prefs(req: UserPrefsRequest, user=Depends(require_user)):
    return update_user_preferences(user["id"], req.theme, req.lang)

# --- REGISTER ---
@app.post("/api/register")
def register_start(req: RegisterRequest):
    if not is_registration_enabled():
        raise HTTPException(403, "Ro'yxatdan o'tish to'xtatilgan")
    if not req.classId: raise HTTPException(400, "Sinfni tanlang")

    _purge_tasks()
    task_id = uuid.uuid4().hex
    _task_ts[task_id] = time.time()
    tasks_state[task_id] = {"status": "processing", "step": "start", "progress": 0}

    threading.Thread(target=_run_register, args=(task_id, req), daemon=True).start()
    return {"task_id": task_id}

@app.get("/api/register/status/{task_id}")
def register_status(task_id: str):
    if task_id in tasks_state: return tasks_state[task_id]
    try:
        doc = db().collection("register_tasks").document(task_id).get()
        if doc.exists:
            d = doc.to_dict()
            return {"status": d.get("status", "processing"), "step": d.get("step", ""), "message": d.get("message", ""), "progress": d.get("progress", 0), "result": d.get("result")}
    except Exception as e:
        pass
    raise HTTPException(404, "Task topilmadi")

@app.get("/api/register/check-user")
def api_check_user(phone: str = ""):
    if not phone: return {"exists": False}
    return {"exists": user_exists_by_phone(phone)}

# --- SETTINGS & SYNC ---
@app.get("/api/settings")
def api_get_settings(): return get_settings()

@app.post("/api/settings/update")
def api_update_settings(req: SettingsUpdateRequest, user=Depends(require_role(["bosh_admin"]))):
    return update_settings(req.model_dump(exclude_none=True), user["role"])

@app.post("/api/sync/start")
def api_start_sync(user=Depends(require_role(["director", "bosh_admin"]))):
    update_settings({"syncEnabled": True}, user["role"])
    c = db()
    students = list(c.collection("students").stream())
    batch = c.batch()
    for s in students:
        batch.set(c.collection("emaktab_queue").document(s.id), {"syncEnabled": True, "nextAttempt": datetime.now(timezone.utc)}, merge=True)
    batch.commit()
    threading.Thread(target=sync_all_students, kwargs={"force": True}, daemon=True).start()
    return {"ok": True, "count": len(students)}

@app.post("/api/sync/emergency")
def api_sync_emergency(user=Depends(require_role(["bosh_admin"]))):
    scheduler.pause()
    update_settings({"syncEnabled": True}, user["role"])
    c = db()
    students = list(c.collection("students").stream())
    batch = c.batch()
    for s in students:
        batch.set(c.collection("emaktab_queue").document(s.id), {"syncEnabled": True, "priority": 100}, merge=True)
    batch.commit()
    def _run_and_resume():
        sync_all_students(force=True)
        scheduler.resume()
    threading.Thread(target=_run_and_resume, daemon=True).start()
    return {"ok": True, "message": "Favqulodda sinxronizatsiya boshlandi"}

@app.post("/api/sync-now", dependencies=[Depends(require_admin)])
def sync_now():
    threading.Thread(target=sync_all_students, kwargs={"force": True}, daemon=True).start()
    return {"status": "started"}

# --- CLASSES ---
@app.get("/api/classes")
def api_list_classes(activeOnly: bool = True): return list_classes(activeOnly)

@app.get("/api/classes/{class_id}")
def api_get_class(class_id: str):
    c = get_class(class_id)
    return c or {"ok": False, "message": "Topilmadi"}

@app.post("/api/classes/create")
def api_create_class(req: ClassCreateRequest, user=Depends(require_role(["bosh_admin", "director"]))):
    return create_class(req.classId, user["id"], user["role"], req.description, req.classTeacher.model_dump() if req.classTeacher else None, req.classAdmin.model_dump() if req.classAdmin else None)

@app.post("/api/classes/update")
def api_update_class(req: ClassCreateRequest, user=Depends(require_role(["bosh_admin", "director"]))):
    return update_class(req.classId, user["role"], req.description, req.classTeacher.model_dump() if req.classTeacher else None, req.classAdmin.model_dump() if req.classAdmin else None)

@app.post("/api/classes/delete")
def api_delete_class(req: ClassDeleteRequest, user=Depends(require_role(["bosh_admin"]))):
    return delete_class(req.classId, user["role"])

@app.post("/api/classes/toggle")
def api_toggle_class(req: ClassToggleRequest, user=Depends(require_role(["bosh_admin", "director"]))):
    return toggle_active(req.classId, user["role"])

# --- USERS ---
@app.get("/api/users")
def api_list_users(role: str = "", classId: str = "", search: str = "", status: str = "", limit: int = 500, user=Depends(require_role(["bosh_admin", "director"]))):
    return list_users(role, classId, search, status, limit)

@app.get("/api/users/{user_id}")
def api_get_user(user_id: str, user=Depends(require_role(["bosh_admin", "director"]))):
    return get_user_details(user_id)

@app.post("/api/users/role")
def api_update_role(req: RoleUpdateRequest, user=Depends(require_role(["bosh_admin"]))):
    return update_user_role(req.userId, req.newRole, user["role"])

@app.post("/api/users/promote-class-admin")
def api_promote_class_admin(req: PromoteClassAdminRequest, user=Depends(require_role(["bosh_admin"]))):
    return promote_to_class_admin(req.studentId, user["role"])

@app.post("/api/users/delete")
def api_delete_user(req: RoleUpdateRequest, user=Depends(require_role(["bosh_admin"]))):
    return delete_user(req.userId, user["role"])

@app.get("/api/class-admin/students/{class_id}")
def api_class_students(class_id: str, year: int = 0, user=Depends(require_user)):
    if not year: year = datetime.now(timezone.utc).year
    return class_students(class_id, year)

@app.get("/api/students/{student_id}")
def api_student_detail(student_id: str, user=Depends(require_user)):
    return get_student_detail(student_id)

@app.get("/api/students/{student_id}/grades")
def api_student_grades(student_id: str, limit: int = 30, offset: int = 0, user=Depends(require_user)):
    return get_student_grades_paginated(student_id, limit, offset)

@app.post("/api/students/update")
def api_student_update(req: StudentUpdateRequest, user=Depends(require_role(["class_admin", "director", "bosh_admin"]))):
    payload = req.model_dump(exclude={"studentId"}, exclude_none=True)
    return update_student(req.studentId, payload, user["role"])

@app.post("/api/students/delete")
def api_student_delete(req: StudentUpdateRequest, user=Depends(require_role(["director", "bosh_admin"]))):
    return delete_student(req.studentId, user["role"])

# --- DASHBOARD ---
@app.get("/api/dashboard/student/{user_id}")
def api_student_dashboard(user_id: str, user=Depends(require_user)):
    if user["id"] != user_id and user["role"] not in ("bosh_admin", "director", "class_admin", "teacher", "parent"):
        raise HTTPException(403, "Ruxsat yo'q")
    return student_dashboard(user_id)

@app.get("/api/dashboard/parent/{user_id}")
def api_parent_dashboard(user_id: str, user=Depends(require_user)):
    if user["id"] != user_id and user["role"] not in ("bosh_admin", "director"): raise HTTPException(403, "Ruxsat yo'q")
    return parent_dashboard(user_id)

@app.get("/api/dashboard/teacher/{user_id}")
def api_teacher_dashboard(user_id: str, user=Depends(require_user)):
    if user["id"] != user_id and user["role"] not in ("bosh_admin", "director"): raise HTTPException(403, "Ruxsat yo'q")
    return teacher_dashboard(user_id)

@app.get("/api/dashboard/director")
def api_director_dashboard(schoolId: str = "", user=Depends(require_role(["director", "bosh_admin"]))):
    return director_dashboard(schoolId)

@app.get("/api/dashboard/bosh-admin")
def api_bosh_admin_dashboard(user=Depends(require_role(["bosh_admin"]))):
    return bosh_admin_dashboard()

# --- CHAT ---
@app.post("/api/chat/send")
def api_send_message(req: SendMessageRequest, user=Depends(require_user)):
    return send_message(user["id"], req.classId or user.get("classId", ""), req.text)

@app.get("/api/chat/messages")
def api_list_messages(classId: str = "", limit: int = 50, user=Depends(require_user)):
    return list_messages(classId or user.get("classId", ""), limit)

@app.delete("/api/chat/{message_id}")
def api_delete_message(message_id: str, user=Depends(require_user)):
    return delete_chat_msg(message_id, user["role"])

# --- NEWS & COMMENTS ---
@app.post("/api/news")
def api_create_news(req: NewsCreateRequest, user=Depends(require_user)):
    return create_news(user["id"], user["role"], req.title, req.content, req.category, req.priority, req.imageUrl, req.pinned)

@app.post("/api/news/update")
def api_update_news(req: NewsUpdateRequest, user=Depends(require_user)):
    updates = req.model_dump(exclude={"newsId", "authorId", "authorRole"}, exclude_none=True)
    return update_news(req.newsId, user["id"], user["role"], **updates)

@app.get("/api/news")
def api_list_news(limit: int = 20, category: str = ""):
    return list_news(limit, category)

@app.get("/api/news/{news_id}")
def api_get_news(news_id: str):
    n = get_news(news_id)
    return n or {"ok": False, "message": "Topilmadi"}

@app.delete("/api/news/{news_id}")
def api_delete_news(news_id: str, user=Depends(require_user)):
    return delete_news(news_id, user["id"], user["role"])

@app.post("/api/news/{news_id}/comment")
def api_add_comment(news_id: str, req: CommentRequest, user=Depends(require_user)):
    return add_comment(news_id, user["id"], req.text)

@app.get("/api/news/{news_id}/comments")
def api_list_comments(news_id: str, limit: int = 50):
    return list_comments(news_id, limit)

@app.delete("/api/comments/{comment_id}")
def api_delete_comment(comment_id: str, user=Depends(require_user)):
    return delete_comment(comment_id, user["id"], user["role"])

# --- PAYMENTS ---
@app.post("/api/payments/mark-paid")
def api_mark_paid(req: MarkPaidRequest, user=Depends(require_role(["class_admin", "director", "bosh_admin"]))):
    return mark_paid(req.studentId, req.year, user["id"], req.notes)

@app.post("/api/payments/mark-paid/undo", dependencies=[Depends(require_admin)])
def api_unmark_paid(req: MarkPaidRequest):
    return unmark_paid(req.studentId, req.year, req.collectedBy, req.notes)

@app.get("/api/payments/class/{class_id}")
def api_class_report(class_id: str, year: int, user=Depends(require_user)):
    return class_report(class_id, year)

@app.post("/api/payments/submit-money")
def api_submit_money(req: SubmitMoneyRequest, user=Depends(require_role(["class_admin"]))):
    return submit_collected_money(req.classId, req.year, req.week, user["id"])

@app.post("/api/payments/receive", dependencies=[Depends(require_admin)])
def api_receive(req: ReceiveSubmissionRequest):
    return receive_submission(req.submissionId, req.receivedBy)

# --- WEEKLY REPORTS ---
@app.post("/api/reports/weekly/submit")
def api_submit_weekly(req: WeeklyReportRequest, user=Depends(require_role(["class_admin"]))):
    return submit_weekly_report(req.classId, req.year, req.week, user["id"], req.notes)

@app.get("/api/reports/weekly/list")
def api_list_weekly(year: int = 0, classId: str = "", user=Depends(require_user)):
    return list_weekly_reports(year, classId)

# --- PRIZES ---
@app.get("/api/prizes/class/{class_id}/ranking")
def api_class_ranking(class_id: str, year: int, month: int):
    return compute_class_ranking(class_id, year, month)

@app.get("/api/prizes/school/ranking")
def api_school_ranking(year: int, month: int):
    return compute_school_ranking(year, month)

@app.post("/api/prizes/choose")
def api_choose_prize(req: ChoosePrizeRequest, user=Depends(require_user)):
    return choose_prize(req.prizeId, req.choice, req.telegramUsername)

@app.get("/api/prizes/awaiting/{student_id}")
def api_awaiting(student_id: str, user=Depends(require_user)):
    return list_awaiting_choice(student_id)

@app.get("/api/prizes/pending", dependencies=[Depends(require_admin)])
def api_pending():
    return list_pending_prizes()

@app.post("/api/prizes/give", dependencies=[Depends(require_admin)])
def api_give(req: MarkPrizeGivenRequest):
    return mark_prize_given(req.prizeId, req.givenBy, req.notes)

# --- SCHEDULE ---
@app.post("/api/schedule/save")
def api_save_schedule(req: ScheduleRequest, user=Depends(require_role(["class_admin", "director", "bosh_admin"]))):
    return save_class_schedule(req.classId, req.days, user["id"])

@app.get("/api/schedule/{class_id}")
def api_get_schedule(class_id: str):
    return get_class_schedule(class_id) or {"ok": False, "message": "Topilmadi"}

# --- TASKS ---
@app.post("/api/tasks/seed", dependencies=[Depends(require_admin)])
def api_seed_tasks(force: bool = False):
    return seed_default_tasks(force)

@app.get("/api/tasks")
def api_list_tasks():
    return list_tasks()

@app.get("/api/tasks/user/{user_id}")
def api_user_tasks(user_id: str, user=Depends(require_user)):
    return get_user_tasks(user_id)

@app.get("/api/tasks/user/{user_id}/next")
def api_next_task(user_id: str, user=Depends(require_user)):
    return get_next_task(user_id) or {"ok": False, "message": "Barchasi bajarilgan"}

@app.post("/api/tasks/complete")
def api_complete_task(req: CompleteTaskRequest, user=Depends(require_user)):
    return complete_task(req.userId, req.taskId, req.proof)

@app.get("/api/tasks/user/{user_id}/score")
def api_user_score(user_id: str, user=Depends(require_user)):
    return get_user_total_score(user_id)

# --- TESTS ---
@app.post("/api/tests/seed", dependencies=[Depends(require_admin)])
def api_seed_tests(force: bool = False):
    return seed_tests(force)

@app.get("/api/tests/class/{class_id}")
def api_tests_for_class(class_id: str, user=Depends(require_user)):
    return list_tests_for_class(class_id)

@app.get("/api/tests/{test_id}")
def api_get_test(test_id: str, user=Depends(require_user)):
    t = get_test(test_id)
    return t or {"ok": False, "message": "Topilmadi"}

@app.post("/api/tests/submit")
def api_submit_test(req: SubmitTestRequest, user=Depends(require_user)):
    return submit_test(req.userId, req.testId, req.answers)

@app.get("/api/tests/user/{user_id}/attempts")
def api_user_attempts(user_id: str, limit: int = 20, user=Depends(require_user)):
    return get_user_attempts(user_id, limit)

@app.get("/api/tests/user/{user_id}/stats")
def api_user_test_stats(user_id: str, user=Depends(require_user)):
    return get_user_test_stats(user_id)

# --- BOT ---
@app.get("/api/bot/status")
def api_bot_status(classId: str = "", user=Depends(require_user)):
    return get_bot_status_overview(classId or "")

@app.get("/api/bot/users/pending")
def api_bot_pending(classId: str = "", user=Depends(require_user)):
    return list_pending(classId or None)

@app.get("/api/bot/users/blocked")
def api_bot_blocked(classId: str = "", user=Depends(require_user)):
    return list_blocked(classId or None)

@app.get("/api/bot/users/class/{class_id}")
def api_bot_class(class_id: str, status: str = "", user=Depends(require_user)):
    return list_by_class(class_id, status or None)

@app.get("/api/bot/users/unregistered/{class_id}")
def api_bot_unregistered(class_id: str, user=Depends(require_user)):
    return list_unregistered_students(class_id)

@app.get("/api/bot/users/by-user/{user_id}")
def api_bot_by_user(user_id: str, user=Depends(require_user)):
    u = get_by_user_id(user_id)
    return u or {"ok": False, "message": "Topilmadi"}

@app.post("/api/bot/groups/set")
def api_set_group(req: SetGroupRequest, user=Depends(require_role(["class_admin", "director", "bosh_admin"]))):
    return set_class_group(req.classId, req.groupId, req.groupName, req.setBy)

@app.get("/api/bot/groups/{class_id}")
def api_get_group(class_id: str, user=Depends(require_user)):
    g = get_class_group(class_id)
    return g or {"ok": False, "message": "Guruh ulanmagan"}

@app.get("/api/bot/groups")
def api_list_groups(user=Depends(require_user)):
    return list_all_groups()

# --- ACCOUNT DELETION ---
@app.post("/api/account/delete-request")
def api_delete_request(req: DeletionRequest, user=Depends(require_user)):
    if not req.reason or len(req.reason.strip()) < 10:
        raise HTTPException(400, "Sabab kamida 10 belgi")
    c = db()
    now = datetime.now(timezone.utc)
    c.collection("deletion_requests").document(user["id"]).set({
        "userId": user["id"], "fullName": user["fullName"], "classId": user.get("classId", ""),
        "reason": req.reason.strip(), "requestedAt": now, "status": "pending", "reviewedBy": None, "reviewedAt": None, "notes": "",
    })
    c.collection("super_admin_inbox").add({
        "type": "deletion_request", "userId": user["id"], "fullName": user["fullName"], "reason": req.reason.strip(), "timestamp": now, "read": False,
    })
    return {"ok": True, "message": "So'rov yuborildi"}

@app.get("/api/account/delete-requests")
def api_list_delete_requests(status: str = "pending", user=Depends(require_role(["bosh_admin"]))):
    docs = (db().collection("deletion_requests").where("status", "==", status).stream())
    return [{"id": d.id, **d.to_dict()} for d in docs]

@app.post("/api/account/delete-decision")
def api_delete_decision(req: DeletionDecision, user=Depends(require_role(["bosh_admin"]))):
    c = db()
    now = datetime.now(timezone.utc)
    if req.decision not in ("approved", "rejected"): raise HTTPException(400, "decision: approved yoki rejected")
    c.collection("deletion_requests").document(req.userId).set({
        "status": req.decision, "reviewedBy": user["id"], "reviewedAt": now, "notes": req.notes,
    }, merge=True)
    if req.decision == "approved":
        c.collection("students").document(req.userId).set({"status": "deleted", "deletedAt": now}, merge=True)
        c.collection("users").document(req.userId).set({"status": "deleted", "deletedAt": now}, merge=True)
    return {"ok": True}

# --- DEBUG ---
@app.get("/api/debug/users")
def api_debug_users():
    users = []
    for u in db().collection("users").stream():
        d = u.to_dict()
        users.append({"id": u.id, "fullName": d.get("fullName"), "role": d.get("role"), "phone": d.get("phone"), "hasHash": bool(d.get("passwordHash"))})
    return {"count": len(users), "users": users}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))