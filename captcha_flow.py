"""Admin panelda javobi kiritilgan captchalarni qayta ishlash."""

import json
import logging

from crypto import decrypt
from emaktab import LoginFailed, login_with_captcha_answer
from firebase_client import (
    db,
    delete_from_captcha_queue,
    get_answered_captchas,
    increment_captcha_attempts,
    save_cookies,
    update_captcha_status,
)

log = logging.getLogger("captcha_flow")

MAX_ATTEMPTS = 3


def process_answered(sync_one=None):
    done = 0
    for doc in get_answered_captchas():
        sid = doc.id
        item = doc.to_dict()
        answer = (item.get("answer") or "").strip()
        if not answer:
            update_captcha_status(sid, "pending", "Javob bo'sh")
            continue
        try:
            cookies = (
                json.loads(decrypt(item["cookiesEncrypted"]))
                if item.get("cookiesEncrypted") else []
            )
            lr = login_with_captcha_answer(
                item["login"],
                decrypt(item["passwordEncrypted"]),
                answer,
                cookies,
                item.get("hiddenFields"),
                item.get("captchaInputSelector"),
            )
        except LoginFailed as e:
            n = increment_captcha_attempts(sid)
            log.warning("[%s] captcha xato (%s/%s): %s", sid, n, MAX_ATTEMPTS, e)
            if n >= MAX_ATTEMPTS:
                update_captcha_status(sid, "failed", str(e))
            else:
                update_captcha_status(sid, "pending", str(e))
            continue
        except Exception as e:
            log.exception("[%s] captcha jarayonida xato", sid)
            update_captcha_status(sid, "pending", type(e).__name__)
            continue

        save_cookies(sid, lr.cookies)
        db().collection("emaktab_creds").document(sid).set(
            {"status": "active", "errorMessage": ""}, merge=True
        )
        delete_from_captcha_queue(sid)
        log.info("[%s] captcha yechildi", sid)
        done += 1
        if sync_one:
            sync_one(sid)
    return done