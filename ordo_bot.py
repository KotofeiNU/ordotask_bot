#!/usr/bin/env python3
"""ORDO Tasks & Reports Bot — Tashkent UTC+5"""

import json, os, logging, asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
TZ = ZoneInfo("Asia/Tashkent")
DATA_FILE = "/home/claude/ordo_data.json"

(TASK_TITLE, TASK_ASSIGNEE, TASK_DEADLINE, TASK_PRIORITY, TASK_REPEAT,
 REPORT_TYPE, REPORT_FILL, DONE_COMMENT) = range(8)

REPORT_TEMPLATES = {
    "mp_l1l2": {"name": "📑 МП Л1/Л2", "fields": ["Новые лиды","Исходящие звонки","Аудит","Демо","Оплаты"]},
    "target_l1l2": {"name": "🎯 Таргет Л1/Л2", "fields": ["CPA (тг)","CPA ($)","Начатые сообщения","Начатые сообщения ($)","Потраченный бюджет"]},
    "target_abonement": {"name": "🎯 Таргет Абонементы", "fields": ["Адрес садика","CPA (тг)","CPA ($)","Начатые сообщения","Начатые сообщения ($)","Потраченный бюджет"]},
    "abonement": {"name": "📑 Отчёт Абонементы", "fields": ["Адрес садика","Новые лиды","Экскурсии","Пробный день","Зачисления","Отчисления","Жалобы"]},
    "mp_franchise": {"name": "📑 МП Франшиза", "fields": ["Новые лиды","Исходящие звонки","Митинг","Договор","Оплаты"]},
    "target_franchise": {"name": "🎯 Таргет Франшиза", "fields": ["CPA (тг)","CPA ($)","Начатые сообщения","Начатые сообщения ($)","Потраченный бюджет"]},
}

def load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f: return json.load(f)
    return {"tasks":[], "reports":[], "fines":[], "owner_id":None, "chat_id":None, "members":{}}

def save(d):
    with open(DATA_FILE,"w") as f: json.dump(d,f,ensure_ascii=False,indent=2)

def now_tz(): return datetime.now(TZ)

# ── /start ────────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = load()
    u = update.effective_user
    c = update.effective_chat
    d["members"][u.username or str(u.id)] = u.id
    if c.type in ("group","supergroup"): d["chat_id"] = c.id
    if not d["owner_id"]: d["owner_id"] = u.id
    save(d)
    await update.message.reply_text(
        f"👋 Привет, {u.first_name}!\n\n"
        "/newtask — создать задачу\n/mytasks — мои задачи\n/alltasks — все задачи\n"
        "/overdue — просроченные\n/report — заполнить отчёт\n/stats — статистика\n"
        "/fines — штрафы\n/report_week — аналитика за неделю"
    )

# ── /newtask ──────────────────────────────────────────────────────────────────
async def new_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Название задачи:")
    return TASK_TITLE

async def task_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["task"] = {"title": update.message.text}
    await update.message.reply_text("👤 Исполнитель (username без @, несколько — через запятую):")
    return TASK_ASSIGNEE

async def task_assignee(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["task"]["assignee"] = update.message.text.strip()
    await update.message.reply_text("📅 Срок (ДД.ММ ЧЧ:ММ), например: 05.06 17:00")
    return TASK_DEADLINE

async def task_deadline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        yr = now_tz().year
        dt = datetime.strptime(f"{yr} {update.message.text.strip()}", "%Y %d.%m %H:%M").replace(tzinfo=TZ)
        ctx.user_data["task"]["deadline"] = dt.isoformat()
        ctx.user_data["task"]["deadline_fmt"] = update.message.text.strip()
    except:
        await update.message.reply_text("❌ Формат: 05.06 17:00"); return TASK_DEADLINE
    kb = [[InlineKeyboardButton("🔴 Срочно",callback_data="p_urgent"),InlineKeyboardButton("🟡 Важно",callback_data="p_important")],
          [InlineKeyboardButton("🟢 Обычная",callback_data="p_normal")]]
    await update.message.reply_text("⚡ Приоритет:", reply_markup=InlineKeyboardMarkup(kb))
    return TASK_PRIORITY

async def task_priority(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["task"]["priority"] = {"p_urgent":"🔴 Срочно","p_important":"🟡 Важно","p_normal":"🟢 Обычная"}[q.data]
    kb = [[InlineKeyboardButton("Нет",callback_data="r_no")],[InlineKeyboardButton("Ежедневно",callback_data="r_daily")],
          [InlineKeyboardButton("Еженедельно (пн)",callback_data="r_weekly")],[InlineKeyboardButton("Каждую пятницу",callback_data="r_friday")]]
    await q.edit_message_text("🔁 Повтор?", reply_markup=InlineKeyboardMarkup(kb))
    return TASK_REPEAT

async def task_repeat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["task"]["repeat"] = {"r_no":"нет","r_daily":"ежедневно","r_weekly":"еженедельно","r_friday":"каждую пятницу"}[q.data]
    d = load()
    t = ctx.user_data["task"]
    t.update({"id": len(d["tasks"])+1, "created_by": update.effective_user.username or str(update.effective_user.id),
               "created_at": now_tz().isoformat(), "status":"active", "comment":"", "completed_at":""})
    d["tasks"].append(t); save(d)
    await q.edit_message_text(
        f"✅ Задача #{t['id']} создана!\n\n📝 {t['title']}\n👤 @{t['assignee']}\n📅 {t['deadline_fmt']}\n{t['priority']}\n🔁 {t['repeat']}"
    )
    for u in [x.strip() for x in t["assignee"].split(",")]:
        uid = d["members"].get(u)
        if uid:
            try:
                await ctx.bot.send_message(uid, f"📌 Тебе задача #{t['id']}\n\n{t['title']}\n📅 {t['deadline_fmt']}\n{t['priority']}\n\nВыполни: /done_{t['id']}")
            except: pass
    return ConversationHandler.END

# ── /done_N ───────────────────────────────────────────────────────────────────
async def done_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = int(update.message.text.replace("/done_",""))
    ctx.user_data["done_id"] = tid
    await update.message.reply_text(f"Задача #{tid} — добавь комментарий (или «-»):")
    return DONE_COMMENT

async def done_comment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = load(); now = now_tz()
    tid = ctx.user_data["done_id"]
    uname = update.effective_user.username or str(update.effective_user.id)
    for t in d["tasks"]:
        if t["id"] == tid:
            deadline = datetime.fromisoformat(t["deadline"])
            t["status"] = "done"; t["comment"] = update.message.text; t["completed_at"] = now.isoformat()
            late = now > deadline
            if late:
                d["fines"].append({"username":uname,"task_id":tid,"type":"опоздание","amount":10000,
                                    "date":now.isoformat(),"desc":f"Задача #{tid} выполнена с опозданием"})
                await update.message.reply_text(f"✅ Задача #{tid} выполнена.\n⚠️ Опоздание — штраф 10 000 тг")
            else:
                await update.message.reply_text(f"✅ Задача #{tid} выполнена вовремя! 🎉")
            break
    save(d); return ConversationHandler.END

# ── Views ─────────────────────────────────────────────────────────────────────
async def my_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = load(); u = update.effective_user.username or str(update.effective_user.id)
    tasks = [t for t in d["tasks"] if u in t["assignee"] and t["status"]=="active"]
    if not tasks: await update.message.reply_text("✅ Нет активных задач!"); return
    msg = "📋 Твои задачи:\n\n"
    for t in tasks: msg += f"#{t['id']} {t['priority']} {t['title']}\n📅 {t['deadline_fmt']}\n/done_{t['id']}\n\n"
    await update.message.reply_text(msg)

async def all_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = load(); tasks = [t for t in d["tasks"] if t["status"]=="active"]
    if not tasks: await update.message.reply_text("✅ Нет активных задач!"); return
    msg = "📋 Все задачи:\n\n"
    for t in tasks: msg += f"#{t['id']} {t['priority']} {t['title']}\n👤 @{t['assignee']} | 📅 {t['deadline_fmt']}\n\n"
    await update.message.reply_text(msg)

async def overdue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = load(); now = now_tz()
    tasks = [t for t in d["tasks"] if t["status"]=="active" and datetime.fromisoformat(t["deadline"])<now]
    if not tasks: await update.message.reply_text("✅ Просроченных нет!"); return
    msg = "🚨 Просроченные:\n\n"
    for t in tasks: msg += f"#{t['id']} {t['title']}\n👤 @{t['assignee']} | 📅 {t['deadline_fmt']}\n\n"
    await update.message.reply_text(msg)

# ── /report ───────────────────────────────────────────────────────────────────
async def report_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(v["name"], callback_data=f"rep_{k}")] for k,v in REPORT_TEMPLATES.items()]
    await update.message.reply_text("📊 Выбери тип отчёта:", reply_markup=InlineKeyboardMarkup(kb))
    return REPORT_TYPE

async def report_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    key = q.data.replace("rep_",""); tmpl = REPORT_TEMPLATES[key]
    ctx.user_data["rep"] = {"type":key,"name":tmpl["name"],"fields":tmpl["fields"],"values":{},"idx":0}
    await q.edit_message_text(f"{tmpl['name']}\n\n{tmpl['fields'][0]}:")
    return REPORT_FILL

async def report_fill(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rep = ctx.user_data["rep"]
    rep["values"][rep["fields"][rep["idx"]]] = update.message.text
    rep["idx"] += 1
    if rep["idx"] < len(rep["fields"]):
        await update.message.reply_text(f"{rep['fields'][rep['idx']]}:")
        return REPORT_FILL
    d = load()
    d["reports"].append({"id":len(d["reports"])+1,"type":rep["type"],"name":rep["name"],
                          "values":rep["values"],"username":update.effective_user.username or str(update.effective_user.id),
                          "created_at":now_tz().isoformat(),"date":now_tz().strftime("%d.%m.%Y")})
    save(d)
    msg = f"✅ {rep['name']} сохранён!\n\n"
    for k,v in rep["values"].items(): msg += f"• {k}: {v}\n"
    await update.message.reply_text(msg)
    return ConversationHandler.END

# ── /stats ────────────────────────────────────────────────────────────────────
async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = load(); now = now_tz()
    us = {}
    for t in d["tasks"]:
        for u in [x.strip() for x in t["assignee"].split(",")]:
            if u not in us: us[u] = {"done":0,"active":0,"overdue":0,"fines":0}
            if t["status"]=="done": us[u]["done"]+=1
            elif t["status"]=="active":
                us[u]["active"]+=1
                if datetime.fromisoformat(t["deadline"])<now: us[u]["overdue"]+=1
    for f in d["fines"]:
        u=f["username"]
        if u not in us: us[u]={"done":0,"active":0,"overdue":0,"fines":0}
        us[u]["fines"]+=f["amount"]
    srt = sorted(us.items(), key=lambda x:(-x[1]["done"],x[1]["overdue"]))
    msg = f"📊 Статистика\n\n✅ Всего выполнено: {sum(u['done'] for _,u in us.items())}\n\n🏆 Рейтинг:\n"
    emojis = ["🥇","🥈","🥉"]
    for i,(u,s) in enumerate(srt):
        e = emojis[i] if i<3 else "👤"
        msg += f"{e} @{u}: ✅{s['done']} 🔄{s['active']} 🚨{s['overdue']} 💸{s['fines']:,}тг\n"
    await update.message.reply_text(msg)

async def fines_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = load()
    if not d["fines"]: await update.message.reply_text("✅ Штрафов нет!"); return
    msg = "💸 Штрафы:\n\n"; total={}
    for f in d["fines"]:
        u=f["username"]; total[u]=total.get(u,0)+f["amount"]
        msg += f"@{u} — {f['amount']:,}тг\n{f['desc']}\n\n"
    msg += "─────\nИтого:\n"
    for u,a in total.items(): msg += f"@{u}: {a:,}тг\n"
    await update.message.reply_text(msg)

# ── Weekly report ─────────────────────────────────────────────────────────────
async def report_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _send_weekly(ctx.bot, update.effective_chat.id)

async def _send_weekly(bot, chat_id):
    d = load(); now = now_tz(); week_ago = now - timedelta(days=7)
    reps = [r for r in d["reports"] if datetime.fromisoformat(r["created_at"])>=week_ago]
    msg = f"📊 Аналитика за неделю ({week_ago.strftime('%d.%m')}–{now.strftime('%d.%m')})\n\n"
    for key, tmpl in REPORT_TEMPLATES.items():
        rs = [r for r in reps if r["type"]==key]
        if not rs: continue
        msg += f"{tmpl['name']} ({len(rs)} отчётов)\n"
        nums = {}
        for r in rs:
            for k,v in r["values"].items():
                try: nums[k] = nums.get(k,0)+float(v.replace(",",".").replace(" ",""))
                except: pass
        for k,v in nums.items(): msg += f"  • {k}: {v:,.0f}\n"
        # Conversions
        if key=="mp_l1l2" and nums.get("Новые лиды",0)>0:
            msg += f"  📈 Конверсия: {round(nums.get('Оплаты',0)/nums['Новые лиды']*100,1)}%\n"
        if key=="mp_franchise" and nums.get("Новые лиды",0)>0:
            msg += f"  📈 Конверсия: {round(nums.get('Договор',0)/nums['Новые лиды']*100,1)}%\n"
        if key=="abonement" and nums.get("Новые лиды",0)>0:
            msg += f"  📈 Конверсия: {round(nums.get('Зачисления',0)/nums['Новые лиды']*100,1)}%\n"
        msg += "\n"
    await bot.send_message(chat_id, msg)

# ── Scheduled ─────────────────────────────────────────────────────────────────
async def _reminder_1750(bot):
    d = load(); now = now_tz(); today = now.strftime("%d.%m.%Y")
    for uname, uid in d["members"].items():
        my_t = [t for t in d["tasks"] if uname in t.get("assignee","") and t["status"]=="active"
                and datetime.fromisoformat(t["deadline"]).strftime("%d.%m.%Y")==today]
        my_r = set(r["type"] for r in d["reports"] if r["username"]==uname and r["date"]==today)
        miss_r = set(REPORT_TEMPLATES)-my_r
        if my_t or miss_r:
            msg = "⏰ До 18:00 осталось 10 минут!\n\n"
            if my_t:
                msg += "📋 Незакрытые задачи:\n"
                for t in my_t: msg += f"  • #{t['id']} {t['title']}\n"
            if miss_r:
                msg += "\n📑 Незаполненные отчёты:\n"
                for r in miss_r: msg += f"  • {REPORT_TEMPLATES[r]['name']}\n"
                msg += "\nЗаполни: /report"
            try: await bot.send_message(uid, msg)
            except: pass

async def _fines_1801(bot):
    d = load(); now = now_tz(); today = now.strftime("%d.%m.%Y")
    new_fines = []
    for uname, uid in d["members"].items():
        my_r = set(r["type"] for r in d["reports"] if r["username"]==uname and r["date"]==today)
        for rt in set(REPORT_TEMPLATES)-my_r:
            f = {"username":uname,"type":"отчёт","amount":10000,"date":now.isoformat(),
                 "desc":f"Не сдал {REPORT_TEMPLATES[rt]['name']} до 18:00"}
            d["fines"].append(f); new_fines.append(f)
        # Task fines for tasks past deadline NOT done
        overdue_tasks = [t for t in d["tasks"] if uname in t.get("assignee","") and t["status"]=="active"
                         and datetime.fromisoformat(t["deadline"])<now]
        for t in overdue_tasks:
            f = {"username":uname,"task_id":t["id"],"type":"невыполнение","amount":30000,"date":now.isoformat(),
                 "desc":f"Задача #{t['id']} не выполнена"}
            d["fines"].append(f); new_fines.append(f)
            t["status"] = "overdue"
    save(d)
    if new_fines and d["owner_id"]:
        msg = f"🚨 Штрафы {today}:\n\n"; total={}
        for f in new_fines:
            u=f["username"]; total[u]=total.get(u,0)+f["amount"]
            msg += f"@{u} — {f['amount']:,}тг\n{f['desc']}\n\n"
        msg += "─────\n"
        for u,a in total.items(): msg += f"@{u}: {a:,}тг\n"
        try: await bot.send_message(d["owner_id"], msg)
        except: pass

async def _evening_1830(bot):
    d = load(); now = now_tz(); today = now.strftime("%d.%m.%Y")
    done_today = [t for t in d["tasks"] if t["status"]=="done" and t.get("completed_at","")[:10]==now.strftime("%Y-%m-%d")]
    active = [t for t in d["tasks"] if t["status"]=="active"]
    ov = [t for t in active if datetime.fromisoformat(t["deadline"])<now]
    us = {}
    for t in d["tasks"]:
        for u in [x.strip() for x in t["assignee"].split(",")]:
            if u not in us: us[u]={"done":0,"overdue":0,"fines":0}
            if t["status"]=="done": us[u]["done"]+=1
            elif t["status"] in ("active","overdue") and datetime.fromisoformat(t["deadline"])<now: us[u]["overdue"]+=1
    for f in d["fines"]:
        u=f["username"]
        if u not in us: us[u]={"done":0,"overdue":0,"fines":0}
        us[u]["fines"]+=f["amount"]
    srt = sorted(us.items(),key=lambda x:(-x[1]["done"],x[1]["overdue"]))
    msg = f"📊 Итоги дня — {today}\n\n✅ Выполнено: {len(done_today)}\n🔄 Активных: {len(active)}\n🚨 Просроченных: {len(ov)}\n"
    today_reps = [r for r in d["reports"] if r["date"]==today]
    msg += f"📑 Отчётов: {len(today_reps)}\n\n"
    best = [(u,s) for u,s in srt if s["overdue"]==0 and s["done"]>0]
    worst = [(u,s) for u,s in srt if s["overdue"]>0 or s["fines"]>0]
    if best:
        msg += "✨ Лучшие:\n"
        for u,s in best[:3]: msg += f"🏆 @{u} — {s['done']} задач\n"
    if worst:
        msg += "\n⚠️ Отстающие:\n"
        for u,s in worst[:3]: msg += f"💀 @{u} — {s['overdue']} просрочек, {s['fines']:,}тг\n"
    if d.get("chat_id"):
        try: await bot.send_message(d["chat_id"], msg)
        except: pass
    if d.get("owner_id"):
        today_f = [f for f in d["fines"] if f["date"][:10]==now.strftime("%Y-%m-%d")]
        owner_msg = msg + ("\n\n💸 Штрафы:\n"+"".join(f"@{f['username']}: {f['amount']:,}тг — {f['desc']}\n" for f in today_f) if today_f else "\n\n✅ Штрафов нет")
        try: await bot.send_message(d["owner_id"], owner_msg)
        except: pass

async def _sunday_weekly(bot):
    d = load()
    if d.get("chat_id"): await _send_weekly(bot, d["chat_id"])

async def scheduler_loop(bot):
    while True:
        now = now_tz()
        h, m = now.hour, now.minute
        if h==17 and m==50: await _reminder_1750(bot); await asyncio.sleep(70)
        elif h==18 and m==1: await _fines_1801(bot); await asyncio.sleep(70)
        elif h==18 and m==30: await _evening_1830(bot); await asyncio.sleep(70)
        elif h==10 and m==0 and now.weekday()==6: await _sunday_weekly(bot); await asyncio.sleep(70)
        else: await asyncio.sleep(30)

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено."); return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()

    task_conv = ConversationHandler(
        entry_points=[CommandHandler("newtask", new_task)],
        states={
            TASK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_title)],
            TASK_ASSIGNEE: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_assignee)],
            TASK_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_deadline)],
            TASK_PRIORITY: [CallbackQueryHandler(task_priority, pattern="^p_")],
            TASK_REPEAT: [CallbackQueryHandler(task_repeat, pattern="^r_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False
    )

    done_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^/done_\d+$"), done_start)],
        states={DONE_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, done_comment)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    report_conv = ConversationHandler(
        entry_points=[CommandHandler("report", report_cmd)],
        states={
            REPORT_TYPE: [CallbackQueryHandler(report_type, pattern="^rep_")],
            REPORT_FILL: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_fill)],
        },
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("mytasks", my_tasks))
    app.add_handler(CommandHandler("alltasks", all_tasks))
    app.add_handler(CommandHandler("overdue", overdue))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("fines", fines_cmd))
    app.add_handler(CommandHandler("report_week", report_week))
    app.add_handler(task_conv)
    app.add_handler(done_conv)
    app.add_handler(report_conv)

    async def post_init(application):
        asyncio.create_task(scheduler_loop(application.bot))

    app.post_init = post_init
    logger.info("🤖 ORDO Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
