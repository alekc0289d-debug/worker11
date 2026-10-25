"""Bot cron scheduler — 07:00, 13:00, 18:00, Shanba 20:00."""

import logging
from datetime import datetime, timezone, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from firebase_client import db
from bot_users import list_by_class, get_class_group

log = logging.getLogger("bot_scheduler")

TASHKENT_TZ = timezone(timedelta(hours=5))


async def send_daily_schedule(bot: Bot):
    """07:00 — bugungi jadval barcha sinf guruhlariga."""
    now = datetime.now(TASHKENT_TZ)
    day_names = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
    day_name = day_names[now.weekday()]

    groups = list(db().collection("bot_groups").where("active", "==", True).stream())

    for gdoc in groups:
        g = gdoc.to_dict()
        group_id = g.get("groupId")
        class_id = g.get("classId")

        if not group_id or not class_id:
            continue

        if day_name == "Yakshanba":
            text = "🌅 <b>Xayrli tong!</b>\n\nBugun yakshanba — dam oling! 🎉\n\n<b>Maktabim+</b>"
        else:
            sched = db().collection("class_schedules").document(class_id).get()
            if not sched.exists:
                continue
            lessons = sched.to_dict().get("days", {}).get(day_name, [])

            text = f"🌅 <b>Xayrli tong!</b>\n\n📅 <b>{day_name}</b> — dars jadvali:\n\n"

            if not lessons:
                text += "Bugun dars yo&apos;q 🎉"
            else:
                for l in lessons:
                    text += f"{l['lessonNumber']}. <b>{l['subject']}</b>\n"
                    text += f"   ⏰ {l['startTime']}–{l['endTime']} · {l.get('room', '')}\n"
                    text += f"   👨‍🏫 {l.get('teacher', '')}\n\n"

            text += f"\n<b>Maktabim+</b> · {class_id}"

        try:
            await bot.send_message(group_id, text, parse_mode="HTML")
            log.info("[SCHED] %s ga jadval yuborildi", class_id)
        except Exception as e:
            log.error("[SCHED] Xato %s: %s", class_id, e)


async def send_daily_warnings(bot: Bot):
    """Har kuni — botga ulanmagan va bloklaganlarni guruhga ogohlantirish."""
    groups = list(db().collection("bot_groups").where("active", "==", True).stream())

    for gdoc in groups:
        g = gdoc.to_dict()
        group_id = g.get("groupId")
        class_id = g.get("classId")
        if not group_id or not class_id:
            continue

        # Ulanganlarni olish
        connected = set()
        for b in db().collection("bot_users").where("classId", "==", class_id).stream():
            bd = b.to_dict()
            if bd.get("status") == "connected":
                connected.add(bd.get("userId"))

        # Barcha o'quvchilar
        students = list(db().collection("students").where("classId", "==", class_id).stream())

        not_connected = []
        blocked = []

        for s in students:
            if s.id not in connected:
                sd = s.to_dict()
                bot_doc = db().collection("bot_users").document(s.id).get()
                if bot_doc.exists and bot_doc.to_dict().get("status") == "blocked":
                    blocked.append(sd.get("fullName"))
                else:
                    not_connected.append(sd.get("fullName"))

        if not not_connected and not blocked:
            continue

        text = f"⚠️ <b>Diqqat! {class_id} sinfi</b>\n\n"

        if not_connected:
            text += f"🔴 <b>Botga ulanmaganlar ({len(not_connected)}):</b>\n"
            for n in not_connected[:10]:
                text += f"  • {n}\n"
            if len(not_connected) > 10:
                text += f"  ... va {len(not_connected) - 10} ta\n"
            text += "\n"

        if blocked:
            text += f"🚫 <b>Botni bloklaganlar ({len(blocked)}):</b>\n"
            for n in blocked[:5]:
                text += f"  • {n}\n"
            text += "\n"

        text += "📱 Iltimos, botga ulaning: @maktabim65_bot\n\n<b>Maktabim+</b>"

        try:
            await bot.send_message(group_id, text, parse_mode="HTML")
        except Exception as e:
            log.error("[WARN] Xato %s: %s", class_id, e)


async def send_grades_13(bot: Bot):
    """13:00 — 1-smena baholar (barcha shaxsiy chatlarga)."""
    await _send_grades_to_all(bot, shift=1)


async def send_grades_18(bot: Bot):
    """18:00 — 2-smena baholar."""
    await _send_grades_to_all(bot, shift=2)


async def _send_grades_to_all(bot: Bot, shift: int):
    """Baholarni barcha o'quvchilarga yuborish."""
    from dashboard_api import student_dashboard
    
    students = list(db().collection("students").stream())
    
    for sdoc in students:
        sid = sdoc.id
        try:
            # Botga ulanganlarni
            bot_doc = db().collection("bot_users").document(sid).get()
            if not bot_doc.exists:
                continue
            bd = bot_doc.to_dict()
            if bd.get("status") != "connected":
                continue
            
            telegram_id = bd.get("telegramId")
            if not telegram_id:
                continue
            
            # Baholarni olish
            dash = student_dashboard(sid)
            if not dash.get("ok"):
                continue
            
            # Oxirgi baholar
            recent = dash.get("recentGrades", [])[:5]
            if not recent:
                continue
            
            stats = dash.get("stats", {})
            
            text = (
                f"📊 <b>Bugungi baholaringiz</b>\n\n"
                f"O'rtacha: <b>{stats.get('avg', 0)}</b>\n"
                f"Reyting: <b>{stats.get('rank', 0)}</b> / {stats.get('totalStudents', 0)}\n\n"
                f"<b>Oxirgi baholar:</b>\n"
            )
            
            for g in recent:
                text += f"  {g['subject']}: <b>{g['score']}</b> ({g['date']})\n"
            
            text += "\n<b>Maktabim+</b>"
            
            await bot.send_message(telegram_id, text, parse_mode="HTML")
            
        except Exception as e:
            log.error("[GRADES] %s xato: %s", sid[:12], e)


async def send_weekly_ranking(bot: Bot):
    """Shanba 20:00 — haftalik reyting."""
    for gdoc in db().collection("bot_groups").where("active", "==", True).stream():
        g = gdoc.to_dict()
        group_id = g.get("groupId")
        class_id = g.get("classId")
        if not group_id or not class_id:
            continue
        
        from prizes import compute_class_ranking
        now = datetime.now(TASHKENT_TZ)
        ranking = compute_class_ranking(class_id, now.year, now.month)
        
        if not ranking:
            continue
        
        text = f"🏆 <b>Haftalik reyting — {class_id}</b>\n\n"
        for r in ranking[:10]:
            medal = "🥇" if r["rank"] == 1 else "🥈" if r["rank"] == 2 else "🥉" if r["rank"] == 3 else f"{r['rank']}."
            text += f"{medal} {r['fullName']} — {r['final']}\n"
        
        text += "\n<b>Maktabim+</b>"
        
        try:
            await bot.send_message(group_id, text, parse_mode="HTML")
        except Exception as e:
            log.error("[RANK] Xato: %s", e)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Barcha cron joblarni sozlash."""
    sched = AsyncIOScheduler(timezone="Asia/Tashkent")
    
    sched.add_job(send_daily_schedule, "cron", hour=7, minute=0, args=[bot])
    sched.add_job(send_daily_warnings, "cron", hour=12, minute=0, args=[bot])
    sched.add_job(send_grades_13, "cron", hour=13, minute=0, args=[bot])
    sched.add_job(send_grades_18, "cron", hour=18, minute=0, args=[bot])
    sched.add_job(send_weekly_ranking, "cron", day_of_week="sat", hour=20, minute=0, args=[bot])
    
    return sched