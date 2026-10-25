import base64 as _b64
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import settings
from captcha_solver import solve_captcha

log = logging.getLogger(__name__)

TASHKENT_TZ = timezone(timedelta(hours=5))


class CaptchaRequired(RuntimeError):
    def __init__(self, msg, captcha_image=None, cookies=None,
                 hidden_fields=None, login=None, password=None,
                 captcha_input_selector=None):
        super().__init__(msg)
        self.captcha_image = captcha_image
        self.cookies = cookies or []
        self.hidden_fields = hidden_fields or {}
        self.login = login
        self.password = password
        self.captcha_input_selector = captcha_input_selector


class LoginFailed(RuntimeError):
    pass


@dataclass
class LoginResult:
    cookies: list
    method: str


def create_driver():
    o = Options()
    if settings.headless:
        o.add_argument("--headless=new")
    o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage")
    o.add_argument("--window-size=1440,1000")
    o.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=o)


def _hc(d):
    try:
        imgs = d.find_elements(
            By.CSS_SELECTOR, 'img[id*="captcha"], img[src*="captcha"]'
        )
        return any(
            i.is_displayed() and i.size.get("height", 0) > 0 for i in imgs
        )
    except Exception:
        return False


def _slow(el, v):
    for c in v:
        el.send_keys(c)
        time.sleep(0.1)


def login(login, password, driver=None):
    own = driver is None
    d = driver or create_driver()
    try:
        d.get(settings.emaktab_login_url)
        WebDriverWait(d, 20).until(
            EC.presence_of_element_located((By.NAME, "login"))
        )

        hf = {}
        try:
            for el in d.find_elements(
                By.CSS_SELECTOR, 'form input[type="hidden"]'
            ):
                n = el.get_attribute("name")
                v = el.get_attribute("value") or ""
                if n:
                    hf[n] = v
        except Exception:
            pass

        _slow(d.find_element(By.NAME, "login"), login)
        _slow(d.find_element(By.NAME, "password"), password)

        if _hc(d):
            log.info("CAPTCHA")
            cb64 = None
            try:
                img = d.find_element(
                    By.CSS_SELECTOR,
                    'img[id*="captcha"], img[src*="captcha"]'
                )
                cb64 = _b64.b64encode(img.screenshot_as_png).decode()
            except Exception:
                pass

            sol = None
            if cb64:
                try:
                    sol = solve_captcha(_b64.b64decode(cb64))
                except Exception:
                    pass

            if sol:
                log.info("dddd: %s", sol)
                try:
                    inp = d.find_element(
                        By.CSS_SELECTOR,
                        'input[name="Captcha.Input"], '
                        'input[id*="captcha"], input[name="captcha"]'
                    )
                    inp.clear()
                    inp.send_keys(sol)
                    d.find_element(
                        By.CSS_SELECTOR,
                        'button[type="submit"], input[type="submit"]'
                    ).click()
                    WebDriverWait(d, 30).until(
                        lambda x: "login.emaktab.uz" not in x.current_url
                    )
                    return LoginResult(d.get_cookies(), "login")
                except Exception:
                    pass

            if not settings.headless:
                print("=" * 60)
                print("CAPTCHA QOLDA - Brauzerda kiriting va ENTER bosing")
                print("=" * 60)
                input(">>> ENTER: ")
                if "login.emaktab.uz" not in d.current_url:
                    return LoginResult(d.get_cookies(), "login")
                try:
                    WebDriverWait(d, 30).until(
                        lambda x: "login.emaktab.uz" not in x.current_url
                    )
                    return LoginResult(d.get_cookies(), "login")
                except TimeoutException:
                    pass

            raise CaptchaRequired(
                "Captcha",
                captcha_image=cb64,
                cookies=d.get_cookies(),
                hidden_fields=hf,
                login=login,
                password=password,
                captcha_input_selector='input[name="Captcha.Input"]'
            )

        d.find_element(
            By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]'
        ).click()
        WebDriverWait(d, 30).until(
            lambda x: "login.emaktab.uz" not in x.current_url
        )
        return LoginResult(d.get_cookies(), "login")

    except TimeoutException as e:
        if _hc(d):
            raise CaptchaRequired("Captcha xato") from e
        raise LoginFailed("Login timeout") from e
    finally:
        if own:
            d.quit()


def _ex(h, m):
    p = h.find(m)
    if p < 0:
        raise ValueError("State yoq")
    s = h.find("{", p)
    if s < 0:
        raise ValueError("JSON yoq")
    dep, ins, esc = 0, False, False
    for i in range(s, len(h)):
        c = h[i]
        if ins:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                ins = False
        elif c == '"':
            ins = True
        elif c == "{":
            dep += 1
        elif c == "}":
            dep -= 1
            if dep == 0:
                return json.loads(h[s:i + 1])
    raise ValueError("Yopilmagan")


def _d(ts):
    try:
        dt = datetime.fromtimestamp(int(ts), tz=TASHKENT_TZ)
        date_str = dt.date().isoformat()
        days = [
            "Dushanba", "Seshanba", "Chorshanba",
            "Payshanba", "Juma", "Shanba", "Yakshanba",
        ]
        return date_str, days[dt.weekday()]
    except Exception:
        return None, None


def _sc(raw, mx):
    raw = str(raw).strip()
    if raw.upper() in {"OZ", "Н", "НБ", "НБА", ""}:
        return None, None, False
    if "/" in raw:
        p = raw.split("/", 1)
        try:
            n, dn = float(p[0]), float(p[1])
            if dn > 0:
                return round(n / dn * 100), dn, True
        except Exception:
            return None, None, False
    try:
        s = float(raw) if "." in raw else int(raw)
    except ValueError:
        return None, None, False
    m = None
    if mx is not None:
        try:
            m = float(mx) if "." in str(mx) else int(mx)
        except Exception:
            m = None
    p = bool(m and m > 10)
    return (round(s / m * 100), m, True) if p else (s, m, False)


def parse_state(html):
    st = _ex(html, "__USER__START__PAGE__INITIAL__STATE__")
    ctx = st.get("userContextInfo", {})
    ch = st.get("userMarks", {}).get("children", [])
    gs = []
    subjects_map = {}

    for c in ch:
        for mk in c.get("marks", []):
            sb = mk.get("subject", {})
            subject_name = sb.get("name", "N/A")
            subject_id = sb.get("id")
            if subject_id:
                subjects_map[subject_id] = {
                    "id": subject_id,
                    "name": subject_name,
                }

            date_str, day_name = _d(
                mk.get("lessonDate") or mk.get("date")
            )
            mark_type = (
                mk.get("shortMarkTypeText") or mk.get("markTypeText")
            )
            is_final = bool(mk.get("isFinal"))

            for it in mk.get("marks", []):
                raw = it.get("value", "")
                s, m, p = _sc(raw, it.get("maxValue"))
                gs.append({
                    "emaktabId": it.get("id"),
                    "subject": subject_name,
                    "subjectId": subject_id,
                    "score": s,
                    "rawValue": str(raw),
                    "maxValue": m,
                    "isPercent": p,
                    "date": date_str,
                    "dayOfWeek": day_name,
                    "markType": mark_type,
                    "isFinal": is_final,
                    "mood": it.get("mood"),
                })

    for key in ("subjects", "userSubjects", "subjectList", "allSubjects"):
        raw_subjects = st.get(key)
        if isinstance(raw_subjects, list):
            for s in raw_subjects:
                if isinstance(s, dict):
                    sid = s.get("id")
                    sname = s.get("name")
                    if sid and sname:
                        subjects_map[sid] = {"id": sid, "name": sname}

    return {
        "student": {
            "personId": ctx.get("personId"),
            "userId": ctx.get("userId"),
            "firstName": ctx.get("firstName"),
            "lastName": ctx.get("lastName"),
            "schoolId": ctx.get("schoolId"),
            "groupId": ctx.get("groupId"),
        },
        "grades": gs,
        "subjects": list(subjects_map.values()),
        "subjectsCount": len(subjects_map),
    }


DAY_NAMES = {
    "dushanba": "Dushanba", "душанба": "Dushanba", "понедельник": "Dushanba",
    "seshanba": "Seshanba", "сешанба": "Seshanba", "вторник": "Seshanba",
    "chorshanba": "Chorshanba", "чоршанба": "Chorshanba", "среда": "Chorshanba",
    "payshanba": "Payshanba", "пайшанба": "Payshanba", "четверг": "Payshanba",
    "juma": "Juma", "жума": "Juma", "пятница": "Juma",
    "shanba": "Shanba", "шанба": "Shanba", "суббота": "Shanba",
    "yakshanba": "Yakshanba", "якшанба": "Yakshanba", "воскресенье": "Yakshanba",
}


def _parse_time(text):
    tm = re.search(
        r"(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})", text
    )
    if tm:
        return tm.group(1), tm.group(2)
    tm = re.search(r"(\d{1,2}:\d{2})", text)
    if tm:
        return tm.group(1), None
    return None, None


def _parse_lesson_cell(text):
    if not text or len(text.strip()) < 2:
        return None
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if not parts:
        return None

    subject = teacher = room = None
    start_time = end_time = None

    for p in parts:
        st, et = _parse_time(p)
        if st:
            start_time = st
            end_time = et
            continue
        if "xona" in p.lower() or "каб" in p.lower():
            room = p
            continue
        if subject is None:
            subject = p
        elif teacher is None:
            teacher = p

    if not subject:
        return None

    return {
        "subject": subject,
        "teacher": teacher,
        "startTime": start_time,
        "endTime": end_time,
        "room": room,
    }


def parse_timetable(html):
    lessons = []

    # JSON state
    for marker in (
        "__USER__START__PAGE__INITIAL__STATE__",
        "__INITIAL_STATE__",
        "__NUXT__",
    ):
        if marker in html:
            try:
                st = _ex(html, marker)
                tt = (
                    st.get("timetable")
                    or st.get("schedule")
                    or (st.get("data") or {}).get("timetable")
                    or []
                )
                if isinstance(tt, dict):
                    days = tt.get("days") or tt.get("week") or []
                    for day in days:
                        if not isinstance(day, dict):
                            continue
                        day_name = day.get("dayName") or day.get("name")
                        for i, l in enumerate(day.get("lessons", [])):
                            subj = l.get("subject") or {}
                            tchr = l.get("teacher") or {}
                            rm = l.get("room") or {}
                            lessons.append({
                                "dayOfWeek": day_name,
                                "lessonNumber": l.get("number") or (i + 1),
                                "startTime": l.get("startTime") or l.get("time"),
                                "endTime": l.get("endTime"),
                                "subject": subj.get("name") if isinstance(subj, dict) else l.get("subjectName"),
                                "subjectId": subj.get("id") if isinstance(subj, dict) else None,
                                "teacher": tchr.get("fullName") if isinstance(tchr, dict) else l.get("teacherName"),
                                "room": rm.get("name") if isinstance(rm, dict) else l.get("roomName"),
                            })
                if lessons:
                    return lessons
            except Exception:
                pass

    # HTML table
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return lessons

    tables = soup.find_all("table")

    for table in tables:
        header_cells = table.find_all("th")
        day_names = []
        for th in header_cells:
            text = th.get_text(strip=True).lower()
            day = DAY_NAMES.get(text)
            if day:
                day_names.append(day)

        if len(day_names) < 2:
            first_row = table.find("tr")
            if first_row:
                for cell in first_row.find_all(["td", "th"]):
                    text = cell.get_text(strip=True).lower()
                    day = DAY_NAMES.get(text)
                    if day:
                        day_names.append(day)

        if len(day_names) < 2:
            continue

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            num_text = cells[0].get_text(strip=True)
            num_match = re.search(r"\d+", num_text)
            if not num_match:
                continue
            num = int(num_match.group())

            for i, cell in enumerate(cells[1:]):
                if i >= len(day_names):
                    break
                cell_text = cell.get_text("\n", strip=True)
                parsed = _parse_lesson_cell(cell_text)
                if not parsed:
                    continue
                lessons.append({
                    "dayOfWeek": day_names[i],
                    "lessonNumber": num,
                    **parsed,
                })

    if lessons:
        return lessons

    # Div-based
    day_elements = []
    for el in soup.find_all(["div", "h3", "h4", "span", "th", "td"]):
        text = el.get_text(strip=True).lower()
        day = DAY_NAMES.get(text)
        if day:
            day_elements.append((el, day))

    if day_elements:
        for el, day in day_elements:
            parent = el.find_parent()
            if not parent:
                continue
            container = parent.find_parent() or parent
            cards = container.find_all(
                ["div", "article"],
                class_=re.compile(r"lesson|card|subject|item|cell", re.I),
            )
            for idx, card in enumerate(cards):
                text = card.get_text("\n", strip=True)
                parsed = _parse_lesson_cell(text)
                if parsed:
                    lessons.append({
                        "dayOfWeek": day,
                        "lessonNumber": idx + 1,
                        **parsed,
                    })

    return lessons


def fetch_data(cookies, driver=None, status_cb=None, fetch_grades=True):
    if fetch_grades:
        log_step("📊 Baholar yuklanmoqda...", 45)
        d.get(f"{settings.emaktab_home_url.rstrip('/')}/marks")
        time.sleep(3)
    own = driver is None
    d = driver or create_driver()

    def log_step(msg, progress):
        log.info(msg)
        if status_cb:
            try:
                status_cb(msg, progress)
            except Exception:
                pass

    try:
        log_step("Asosiy sahifa ochilmoqda...", 12)
        d.get(settings.emaktab_home_url)
        time.sleep(2)

        log_step("Cookie'lar qo'shilmoqda...", 18)
        for c in cookies:
            try:
                d.add_cookie({
                    k: c[k]
                    for k in ("name", "value", "domain", "path", "expiry")
                    if k in c
                })
            except Exception:
                pass

        log_step("Cookie bilan qayta yuklash...", 22)
        d.get(settings.emaktab_home_url)
        time.sleep(3)

        if "login.emaktab.uz" in d.current_url:
            raise LoginFailed("Cookie tugagan")

        log_step("📔 Kundalik yuklanmoqda...", 30)
        d.get(f"{settings.emaktab_home_url.rstrip('/')}/userfeed")
        time.sleep(3)

        log_step("📊 Baholar yuklanmoqda...", 45)
        d.get(f"{settings.emaktab_home_url.rstrip('/')}/marks")
        time.sleep(3)

        log_step("📅 Jadval yuklanmoqda...", 60)
        d.get("https://schools.emaktab.uz/v2/children/timetable")
        time.sleep(5)
        try:
            WebDriverWait(d, 20).until(
                lambda x: len(x.page_source) > 15000
            )
        except Exception:
            pass
        time.sleep(3)

        try:
            d.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            d.execute_script("window.scrollTo(0, 0);")
            time.sleep(2)
        except Exception:
            pass

        timetable_html = d.page_source

        if settings.debug_html:
            try:
                os.makedirs("debug", exist_ok=True)
                with open("debug/timetable.html", "w", encoding="utf-8") as f:
                    f.write(timetable_html)
            except Exception:
                pass

        log_step("🏠 Asosiy sahifa (JSON)...", 75)
        d.get(settings.emaktab_home_url)
        time.sleep(3)

        log_step("📊 Ma'lumotlar tahlil qilinmoqda...", 85)
        result = parse_state(d.page_source)

        try:
            lessons = parse_timetable(timetable_html)
            result["schedule"] = lessons
        except Exception:
            result["schedule"] = []

        log_step(
            f"✅ {len(result.get('grades', []))} ta baho, "
            f"{len(result.get('schedule', []))} ta dars",
            90,
        )
        return result

    finally:
        if own:
            d.quit()


def login_with_captcha_answer(login_name, password, answer, cookies,
                              hidden_fields=None, input_selector=None):
    d = create_driver()
    try:
        d.get(settings.emaktab_login_url)
        for c in cookies or []:
            try:
                d.add_cookie({
                    k: c[k]
                    for k in ("name", "value", "domain", "path", "expiry")
                    if k in c
                })
            except Exception:
                pass
        d.get(settings.emaktab_login_url)
        WebDriverWait(d, 20).until(
            EC.presence_of_element_located((By.NAME, "login"))
        )

        for name, value in (hidden_fields or {}).items():
            d.execute_script(
                "var e=document.querySelector("
                "'input[type=\"hidden\"][name=\"'+arguments[0]+'\"]');"
                "if(e){e.value=arguments[1];}",
                name, value,
            )

        _slow(d.find_element(By.NAME, "login"), login_name)
        _slow(d.find_element(By.NAME, "password"), password)

        inp = d.find_element(
            By.CSS_SELECTOR, input_selector or 'input[name="Captcha.Input"]'
        )
        inp.clear()
        inp.send_keys(answer)
        d.find_element(
            By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]'
        ).click()

        WebDriverWait(d, 30).until(
            lambda x: "login.emaktab.uz" not in x.current_url
        )
        return LoginResult(d.get_cookies(), "captcha")
    except TimeoutException as e:
        raise LoginFailed("Captcha javobi noto'g'ri") from e
    finally:
        d.quit()