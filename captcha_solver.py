import base64
import logging
import os
import time

log = logging.getLogger(__name__)

_i = None


def _get():
    global _i
    if _i is None:
        try:
            import ddddocr
            _i = ddddocr.DdddOcr(show_ad=False)
        except Exception as e:
            log.warning("ddddocr: %s", e)
    return _i


def _dddd(b):
    o = _get()
    if o is None:
        return None
    try:
        r = o.classification(b)
        return r.strip().replace(" ", "") if r else None
    except Exception as e:
        log.warning("dddd: %s", e)
        return None


def _2c(b):
    k = os.getenv("TWOCAPTCHA_API_KEY", "").strip()
    if not k:
        return None
    try:
        import requests
        e = base64.b64encode(b).decode()
        s = requests.post(
            "https://2captcha.com/in.php",
            data={
                "key": k,
                "method": "base64",
                "body": e,
                "json": 1,
                "numeric": 1,
                "min_len": 4,
                "max_len": 6,
            },
            timeout=30,
        ).json()
        if s.get("status") != 1:
            return None
        cid = s["request"]
        for _ in range(20):
            time.sleep(5)
            r = requests.get(
                "https://2captcha.com/res.php",
                params={"key": k, "action": "get", "id": cid, "json": 1},
                timeout=30,
            ).json()
            if r.get("status") == 1:
                return r["request"]
            if r.get("request") != "CAPCHA_NOT_READY":
                return None
    except Exception as e:
        log.warning("2cap: %s", e)
    return None


def solve_captcha(b):
    r = _dddd(b)
    return r if r else _2c(b)