"""Test o'quvchilar yaratish — Firestore'ga."""

import argparse
import logging
from datetime import datetime, timezone

from firebase_client import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("create_students")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--class", dest="class_id", default="9-A",
                   help="Sinf (default: 9-A)")
    p.add_argument("--count", type=int, default=10,
                   help="Nechta o'quvchi (default: 10)")
    p.add_argument("--prefix", default="Test",
                   help="Ism prefiksi (default: Test)")
    a = p.parse_args()

    now = datetime.now(timezone.utc)
    c = db()

    names = [
        "Ozodbek Karimov", "Ali Valiyev", "Laylo Rahimova",
        "Jasur Toshmatov", "Dilnoza Yusupova", "Sardor Aliyev",
        "Madina Tursunova", "Bobur Karimov", "Nilufar Sattorova",
        "Rustam Abdullayev", "Sevinch Nazarova", "Aziz Ergashev",
        "Zulfiya Yusupova", "Sanjar Boboyev", "Kamola Rashidova",
    ]

    created = 0
    for i in range(a.count):
        sid = f"student_{a.class_id.lower().replace('-','')}_{i+1:03d}"
        full_name = names[i % len(names)]

        c.collection("students").document(sid).set({
            "fullName": full_name,
            "classId": a.class_id,
            "phone": f"+9989012345{i:02d}",
            "motherPhone": f"+9989012346{i:02d}",
            "fatherPhone": f"+9989012347{i:02d}",
            "status": "active",
            "createdAt": now,
            "updatedAt": now,
        }, merge=True)
        log.info("OK %s — %s", sid, full_name)
        created += 1

    log.info("JAMI: %s ta o'quvchi '%s' sinfiga yozildi", created, a.class_id)


if __name__ == "__main__":
    main()