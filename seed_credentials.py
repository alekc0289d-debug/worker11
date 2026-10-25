"""credentials.json dan Firestore'ga emaktab login/parol yuklash.

credentials.json formati:
[
  {"student_id": "student_abc123", "login": "AB12345", "password": "xxxxx"},
  {"student_id": "student_def456", "login": "CD67890", "password": "yyyyy"}
]

Yoki bitta obyekt:
{"student_id": "student_abc123", "login": "AB12345", "password": "xxxxx"}

Ishlatish:
    python seed_credentials.py                      # credentials.json
    python seed_credentials.py path/to/file.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from firebase_client import save_credentials

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("seed_credentials")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("path", nargs="?", default="credentials.json",
                   help="JSON fayl yo'li (default: credentials.json)")
    a = p.parse_args()

    path = Path(a.path)
    if not path.exists():
        log.error("Fayl topilmadi: %s", path)
        sys.exit(1)

    try:
        with open(path, encoding="utf-8") as f:
            recs = json.load(f)
    except json.JSONDecodeError as e:
        log.error("JSON formati xato: %s", e)
        sys.exit(1)

    if isinstance(recs, dict):
        recs = [recs]

    if not isinstance(recs, list):
        log.error("JSON massiv yoki obyekt bo'lishi kerak")
        sys.exit(1)

    ok = 0
    errors = 0
    for i, r in enumerate(recs, 1):
        try:
            sid = r["student_id"]
            login = r["login"]
            password = r["password"]
        except KeyError as e:
            log.warning("%s-qator: majburiy maydon yo'q: %s", i, e)
            errors += 1
            continue

        try:
            save_credentials(sid, login, password, [])
            log.info("OK %s (login: %s)", sid, login)
            ok += 1
        except Exception as e:
            log.error("%s (%s) xato: %s", sid, login, e)
            errors += 1

    log.info("=" * 50)
    log.info("Yakun: %s OK, %s xato (jami %s)", ok, errors, len(recs))


if __name__ == "__main__":
    main()