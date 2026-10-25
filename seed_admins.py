"""Default adminlarni (Bosh admin + Direktor) yaratish.

.env dan o'qib, Firestore'ga yozadi.
Bir marta ishga tushiriladi.
"""

import argparse
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# .env yuklash
load_dotenv(Path(__file__).parent / ".env")

from firebase_client import db
from auth import _hash_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("seed_admins")


def _create_user(phone: str, password: str, full_name: str, role: str, **extra) -> str | None:
    """Foydalanuvchi yaratish yoki yangilash."""
    if not phone or not password or not full_name:
        log.warning("To'liq ma'lumot yo'q: phone=%s, name=%s", phone, full_name)
        return None

    c = db()
    now = datetime.now(timezone.utc)

    # Telefon band emasligini tekshirish
    existing = list(c.collection("users").where("phone", "==", phone).limit(1).stream())

    if existing:
        doc_id = existing[0].id
        log.info("Allaqachon mavjud: %s (%s)", phone, full_name)
        # Parol va rolni yangilab qo'yamiz
        c.collection("users").document(doc_id).set({
            "passwordHash": _hash_password(password),
            "fullName": full_name,
            "role": role,
            "status": "active",
            "updatedAt": now,
            **extra,
        }, merge=True)
        log.info("  → yangilandi (parol + rol)")
        return doc_id

    # Yangi yaratish
    user_id = f"{role}_{uuid.uuid4().hex[:12]}"
    c.collection("users").document(user_id).set({
        "fullName": full_name,
        "phone": phone,
        "passwordHash": _hash_password(password),
        "role": role,
        "status": "active",
        "timezone": "Asia/Tashkent",
        "totalScore": 0,
        "createdAt": now,
        "updatedAt": now,
        **extra,
    })

    log.info("✅ Yaratildi: %s — %s (%s)", phone, full_name, role)
    return user_id


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true",
                   help="Mavjudlarni ham yangilash")
    args = p.parse_args()

    # Bosh admin
    bosh_phone = os.getenv("DEFAULT_BOSH_ADMIN_PHONE", "").strip()
    bosh_password = os.getenv("DEFAULT_BOSH_ADMIN_PASSWORD", "").strip()
    bosh_name = os.getenv("DEFAULT_BOSH_ADMIN_NAME", "Bosh Admin").strip()

    if not bosh_phone or not bosh_password:
        log.error("DEFAULT_BOSH_ADMIN_PHONE/PASSWORD .env da yo'q")
        sys.exit(1)

    bosh_id = _create_user(
        phone=bosh_phone,
        password=bosh_password,
        full_name=bosh_name,
        role="bosh_admin",
    )

    # Direktor
    dir_phone = os.getenv("DEFAULT_DIRECTOR_PHONE", "").strip()
    dir_password = os.getenv("DEFAULT_DIRECTOR_PASSWORD", "").strip()
    dir_name = os.getenv("DEFAULT_DIRECTOR_NAME", "Direktor").strip()
    dir_school = os.getenv("DEFAULT_DIRECTOR_SCHOOL", "65-maktab").strip()

    if not dir_phone or not dir_password:
        log.error("DEFAULT_DIRECTOR_PHONE/PASSWORD .env da yo'q")
        sys.exit(1)

    dir_id = _create_user(
        phone=dir_phone,
        password=dir_password,
        full_name=dir_name,
        role="director",
        schoolId=dir_school,
    )

    log.info("=" * 60)
    log.info("TAYYOR!")
    log.info("=" * 60)
    log.info("👑 Bosh admin:")
    log.info("   Telefon:  %s", bosh_phone)
    log.info("   Parol:    %s", bosh_password)
    log.info("")
    log.info("📊 Direktor:")
    log.info("   Telefon:  %s", dir_phone)
    log.info("   Parol:    %s", dir_password)
    log.info("=" * 60)
    log.info("Endi http://localhost:3000/login da kiring")


if __name__ == "__main__":
    main()