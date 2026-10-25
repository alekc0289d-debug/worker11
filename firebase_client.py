import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import firebase_admin
from firebase_admin import credentials, firestore

from config import settings
from crypto import encrypt
import os
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GCP_GRPC_ENABLE_GRPC_KEEPALIVE", "true")

log = logging.getLogger(__name__)
_db = None


def _load_credentials():
    raw = (settings.firebase_credentials_json or settings.firebase_credentials or "").strip()
    if not raw:
        raise RuntimeError(
            "FIREBASE_CREDENTIALS yoki FIREBASE_CREDENTIALS_JSON "
            "o'rnatilmagan — Railway Variables bo'limini tekshiring"
        )
    if raw.startswith("{"):
        try:
            return credentials.Certificate(json.loads(raw))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"FIREBASE_CREDENTIALS JSON noto'g'ri: {e}") from e
    return credentials.Certificate(raw)


def db():
    global _db
    if _db is None:
        if not firebase_admin._apps:
            cred = _load_credentials()
            firebase_admin.initialize_app(cred, {
                "http": {"timeout": 30},
            })
        _db = firestore.client()
    return _db


class BatchWriter:
    LIMIT = 400

    def __init__(self, client):
        self._c = client
        self._b = client.batch()
        self._n = 0

    def _tick(self):
        self._n += 1
        if self._n >= self.LIMIT:
            self.flush()

    def set(self, ref, data, merge=False):
        self._b.set(ref, data, merge=merge)
        self._tick()

    def delete(self, ref):
        self._b.delete(ref)
        self._tick()

    def flush(self):
        if self._n:
            self._b.commit()
        self._b = self._c.batch()
        self._n = 0


def _login_hash(login):
    return hashlib.sha256(login.lower().strip().encode()).hexdigest()


def check_login_exists(login):
    h = _login_hash(login)
    result = list(
        db().collection("emaktab_creds")
        .where("loginHash", "==", h)
        .limit(1)
        .stream()
    )
    return len(result) > 0


def save_credentials(sid, login, password, cookies):
    db().collection("emaktab_creds").document(sid).set({
        "login": login,
        "loginHash": _login_hash(login),
        "passwordEncrypted": encrypt(password),
        "cookiesEncrypted": encrypt(json.dumps(cookies)),
        "status": "active",
        "lastSync": firestore.SERVER_TIMESTAMP,
        "expiresAt": datetime.now(timezone.utc) + timedelta(days=30),
    }, merge=True)


def save_cookies(sid, cookies):
    db().collection("emaktab_creds").document(sid).set({
        "cookiesEncrypted": encrypt(json.dumps(cookies)),
        "status": "active",
        "lastSync": firestore.SERVER_TIMESTAMP,
        "expiresAt": datetime.now(timezone.utc) + timedelta(days=30),
    }, merge=True)


def read_credentials(sid):
    s = db().collection("emaktab_creds").document(sid).get()
    if not s.exists:
        raise KeyError(f"Cred yoq: {sid}")
    return s.to_dict()


def save_sync(sid, result, method):
    c = db()
    w = BatchWriter(c)
    now = datetime.now(timezone.utc)

    w.set(
        c.collection("students").document(sid),
        {
            "emaktab": result["student"],
            "gradesCount": len(result["grades"]),
            "subjectsCount": result.get("subjectsCount", 0),
            "updatedAt": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )

    existing_ids = set()
    for d in (
        c.collection("grades")
        .where("studentId", "==", sid)
        .where("source", "==", "emaktab")
        .stream()
    ):
        key = d.to_dict().get("emaktabId")
        if key:
            existing_ids.add(key)

    new_count = 0
    for g in result["grades"]:
        emaktab_id = g.get("emaktabId")
        if not emaktab_id or emaktab_id in existing_ids:
            continue
        doc_id = f"{sid}_{emaktab_id}"
        w.set(
            c.collection("grades").document(doc_id),
            {
                "studentId": sid,
                **g,
                "source": "emaktab",
                "syncedAt": firestore.SERVER_TIMESTAMP,
                "createdAt": firestore.SERVER_TIMESTAMP,
            },
        )
        new_count += 1

    schedule = result.get("schedule", [])
    if schedule:
        for o in c.collection("schedule").where("studentId", "==", sid).stream():
            w.delete(o.reference)

        for lesson in schedule:
            w.set(c.collection("schedule").document(), {
                "studentId": sid,
                "classId": settings.class_id,
                **lesson,
                "source": "emaktab",
                "syncedAt": firestore.SERVER_TIMESTAMP,
            })

    for sub in result.get("subjects", []):
        if not sub.get("id"):
            continue
        w.set(
            c.collection("subjects").document(f"{sid}_{sub['id']}"),
            {
                "studentId": sid,
                "classId": settings.class_id,
                "subjectId": sub["id"],
                "name": sub["name"],
                "source": "emaktab",
                "syncedAt": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )

    w.set(
        c.collection("emaktab_queue").document(sid),
        {
            "studentId": sid,
            "nextAttempt": now + timedelta(hours=1),
            "lastAttempt": firestore.SERVER_TIMESTAMP,
            "attempts": 0,
            "lastResult": "success",
            "errorMessage": "",
        },
        merge=True,
    )

    w.set(
        c.collection("emaktab_creds").document(sid),
        {
            "status": "active",
            "lastSync": firestore.SERVER_TIMESTAMP,
            "errorMessage": "",
        },
        merge=True,
    )

    w.set(
        c.collection("emaktab_sync_log").document(),
        {
            "studentId": sid,
            "status": "success",
            "method": method,
            "gradesCount": new_count,
            "scheduleCount": len(schedule),
            "totalGrades": len(result["grades"]),
            "timestamp": firestore.SERVER_TIMESTAMP,
        },
    )

    w.flush()
    return new_count


def mark_error(sid, status, error):
    c = db()
    now = datetime.now(timezone.utc)
    upd = {"lastAttempt": firestore.SERVER_TIMESTAMP, "errorMessage": error}
    if status in ("captcha_required", "expired"):
        upd["status"] = status
    c.collection("emaktab_creds").document(sid).set(upd, merge=True)

    attempts = 1
    try:
        q = c.collection("emaktab_queue").document(sid).get()
        if q.exists:
            attempts = (q.to_dict().get("attempts") or 0) + 1
    except Exception:
        pass

    bo = min(2 ** (attempts - 1), 24)
    c.collection("emaktab_queue").document(sid).set({
        "studentId": sid,
        "nextAttempt": now + timedelta(hours=bo),
        "lastAttempt": firestore.SERVER_TIMESTAMP,
        "attempts": attempts,
        "lastResult": status,
        "errorMessage": error,
    }, merge=True)

    m = "captcha" if status == "captcha_required" else "login"
    c.collection("emaktab_sync_log").add({
        "studentId": sid,
        "status": status,
        "method": m,
        "error": error,
        "timestamp": firestore.SERVER_TIMESTAMP,
    })


def next_queue(limit=40, class_id=None):
    now = datetime.now(timezone.utc)
    fetch = limit * 5 if class_id else limit
    docs = list(
        db().collection("emaktab_queue")
        .where("nextAttempt", "<=", now)
        .order_by("nextAttempt")
        .limit(fetch)
        .stream()
    )
    if not class_id:
        return docs
    cl = db()
    res = []
    for d in docs:
        s = cl.collection("students").document(d.id).get()
        if s.exists and s.to_dict().get("classId") == class_id:
            res.append(d)
            if len(res) >= limit:
                break
    return res


def save_captcha_to_queue(sid, captcha_image_base64, cookies, hidden_fields,
                          login, password, captcha_input_selector=None):
    db().collection("emaktab_captcha_queue").document(sid).set({
        "studentId": sid,
        "captchaImage": captcha_image_base64,
        "cookiesEncrypted": encrypt(json.dumps(cookies)),
        "hiddenFields": hidden_fields,
        "login": login,
        "passwordEncrypted": encrypt(password),
        "captchaInputSelector": captcha_input_selector,
        "status": "pending",
        "attempts": 0,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    db().collection("emaktab_sync_log").add({
        "studentId": sid,
        "status": "captcha_required",
        "method": "captcha",
        "error": "Captcha navbatga",
        "timestamp": firestore.SERVER_TIMESTAMP,
    })


def get_captcha_queue():
    return list(
        db().collection("emaktab_captcha_queue")
        .where("status", "==", "pending")
        .order_by("createdAt")
        .stream()
    )


def get_answered_captchas(limit=10):
    return list(
        db().collection("emaktab_captcha_queue")
        .where("status", "==", "answered")
        .limit(limit)
        .stream()
    )


def get_captcha_item(sid):
    d = db().collection("emaktab_captcha_queue").document(sid).get()
    return d.to_dict() if d.exists else None


def update_captcha_status(sid, status, error=None):
    upd = {"status": status, "updatedAt": firestore.SERVER_TIMESTAMP}
    if error:
        upd["errorMessage"] = error
    db().collection("emaktab_captcha_queue").document(sid).set(upd, merge=True)


def increment_captcha_attempts(sid):
    d = db().collection("emaktab_captcha_queue").document(sid).get()
    n = 1
    if d.exists:
        n = (d.to_dict().get("attempts") or 0) + 1
    db().collection("emaktab_captcha_queue").document(sid).set(
        {"attempts": n, "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True)
    return n


def delete_from_captcha_queue(sid):
    db().collection("emaktab_captcha_queue").document(sid).delete()