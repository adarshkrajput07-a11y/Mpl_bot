"""
Matrix Premier League - Captain Registration Bot
Library: python-telegram-bot >= 20  ->  pip install "python-telegram-bot>=20"
Run:     python mpl_bot.py

Admin commands:
  /addfile welcome   reply to a photo (or send a photo with this caption)
  /setgroup          run inside the tour group, or /setgroup @name | -100id
  /setchannel        run inside the tour channel, or /setchannel @name | -100id
  /setlog            run inside the log channel/group, or /setlog @name | -100id
  /setteamlogo MI    reply to a photo (or photo caption) to set a team logo
  /teams             list registered teams
  /unregister MI     remove ALL captains of a team (or /unregister <user_id> for one)
Bot must be ADMIN in the group, channel and log chat.
"""
import os, json, re, html, logging
from datetime import datetime
from telegram import (Update, InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)

# ---------------------------------------------------------------- config
BOT_TOKEN = os.environ.get("BOT_TOKEN", "9076293140:AAGZ93vTCYuD4ibguxdW_1EFljMDJdk0_fM")
OWNER_ID = int(os.environ.get("OWNER_ID", "8632603116"))
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "Suiiiiiii_0007").lstrip("@")
ADMIN_IDS = {OWNER_ID} | {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}
DB_FILE = "mpl_data.json"

IPL = ["MI", "CSK", "RCB", "KKR", "PBKS", "RR", "SRH", "LSG", "DC", "GT"]
SA20 = ["JSK", "MICT", "PR", "PC", "DSG"]
TEAMS = IPL + SA20
MAX_PER_TEAM = 2   # a team locks after this many captains

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mpl")

# ---------------------------------------------------------------- small-caps font
_SC = dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"))
def sc(t):   return "".join(_SC.get(c, _SC.get(c.lower(), c)) if c.isalpha() else c for c in t)
def B(t):    return f"<b>{sc(t)}</b>"          # bold + small caps
def esc(s):  return html.escape(str(s))
def is_admin(uid): return uid in ADMIN_IDS

# ---------------------------------------------------------------- storage
def load():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"welcome": None, "group": None, "channel": None, "log": None, "regs": {}}

def save(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)

DB = load()
DB.setdefault("logos", {})

def team_counts():
    c = {}
    for r in DB["regs"].values():
        c[r["team"]] = c.get(r["team"], 0) + 1
    return c

def locked_teams():
    return {t for t, n in team_counts().items() if n >= MAX_PER_TEAM}

# ---------------------------------------------------------------- keyboards
def main_kb():
    return Markup([[Btn(sc("🏏 captain registration"), callback_data="reg")],
                   [Btn(sc("👑 owner"), callback_data="owner")]])

def back_kb():
    return Markup([[Btn(sc("⬅️ back"), callback_data="home")]])

def team_kb():
    counts = team_counts()
    def b(t):
        n = counts.get(t, 0)
        if n >= MAX_PER_TEAM:
            return Btn(f"🔒 {t}", callback_data="taken")
        return Btn(f"{t} ({n}/{MAX_PER_TEAM})" if n else t, callback_data=f"team:{t}")
    rows, row = [], []
    for t in TEAMS:
        row.append(b(t))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    return Markup(rows)

def verify_kb():
    rows = []
    if DB["group"]:   rows.append([Btn(sc("👥 join tour group"), url=DB["group"]["link"])])
    if DB["channel"]: rows.append([Btn(sc("📢 join channel"), url=DB["channel"]["link"])])
    rows.append([Btn(sc("✅ verify"), callback_data="verify")])
    return Markup(rows)

async def show(q, text, kb=None):
    """Edit a message whether it is a photo (caption) or plain text."""
    try:
        if q.message.photo:
            await q.edit_message_caption(caption=text, reply_markup=kb, parse_mode=ParseMode.HTML)
        else:
            await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception as e:
        log.debug("edit failed: %s", e)

WELCOME = (f"🏆 {B('welcome to matrix premier league!')}\n\n"
           f"{B('captains, register your team here.')}\n{B('choose an option below')} 👇")
VERIFY_TXT = (f"🔐 {B('step 1 — verification')}\n\n"
              f"{B('join the tournament group and channel, then tap verify.')}")

# ---------------------------------------------------------------- /start
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return await update.message.reply_text(sc("please use me in dm."))
    ctx.user_data.clear()
    fid = DB.get("welcome")
    if fid:
        await update.message.reply_photo(fid, caption=WELCOME, reply_markup=main_kb(),
                                         parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(WELCOME, reply_markup=main_kb(), parse_mode=ParseMode.HTML)

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(sc("registration cancelled. send /start to begin again."))

# ---------------------------------------------------------------- admin cmds
async def addfile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = update.message
    if not is_admin(update.effective_user.id): return
    args = ctx.args or (m.caption or "").split()[1:]
    if not args or args[0].lower() != "welcome":
        return await m.reply_text(sc("usage: reply to a photo with /addfile welcome"))
    photo = m.photo[-1] if m.photo else (m.reply_to_message.photo[-1]
            if m.reply_to_message and m.reply_to_message.photo else None)
    if not photo:
        return await m.reply_text(sc("reply to a photo with /addfile welcome"))
    DB["welcome"] = photo.file_id; save(DB)
    await m.reply_text(sc("✅ welcome image saved."))

async def resolve_chat(update, ctx):
    if ctx.args:
        arg = ctx.args[0]
        return await ctx.bot.get_chat(int(arg) if re.fullmatch(r"-?\d+", arg) else arg)
    return update.effective_chat

async def link_for(ctx, chat):
    if chat.username: return f"https://t.me/{chat.username}"
    if chat.invite_link: return chat.invite_link
    return await ctx.bot.export_chat_invite_link(chat.id)

def setter(key, label, needs_link=True):
    async def handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id): return
        try:
            chat = await resolve_chat(update, ctx)
            entry = {"id": chat.id, "title": chat.title}
            if needs_link: entry["link"] = await link_for(ctx, chat)
            DB[key] = entry; save(DB)
            await update.effective_message.reply_text(f"✅ {sc(label + ' set')}: {chat.title} ({chat.id})")
        except Exception as e:
            await update.effective_message.reply_text(
                f"❌ {sc('failed')}: {e}\n{sc('make the bot admin there and try again.')}")
    return handler

async def setteamlogo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = update.message
    if not is_admin(update.effective_user.id): return
    args = ctx.args or (m.caption or "").split()[1:]
    photo = m.photo[-1] if m.photo else (m.reply_to_message.photo[-1]
            if m.reply_to_message and m.reply_to_message.photo else None)
    team = args[0].upper() if args else None
    if not team or team not in TEAMS or not photo:
        done = [t for t in TEAMS if t in DB["logos"]]
        miss = [t for t in TEAMS if t not in DB["logos"]]
        return await m.reply_text(
            f"{sc('usage: reply to a photo with /setteamlogo mi')}\n\n"
            f"{sc('teams')}: {', '.join(TEAMS)}\n✅ {sc('logo set')}: {', '.join(done) or '—'}\n"
            f"⬜ {sc('missing')}: {', '.join(miss) or '—'}")
    DB["logos"][team] = photo.file_id; save(DB)
    await m.reply_text(f"✅ {sc('logo saved for')} {team}.")

async def teams_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    lines = []
    for t in TEAMS:
        caps = [r["captain"] for r in DB["regs"].values() if r["team"] == t]
        icon = "🔒" if len(caps) >= MAX_PER_TEAM else ("🟡" if caps else "⬜")
        lines.append(f"{icon} {t} ({len(caps)}/{MAX_PER_TEAM})" + (f" — {', '.join(caps)}" if caps else ""))
    total = len(DB["regs"])
    await update.message.reply_text(f"{sc('total registrations')}: {total}\n\n" + "\n".join(lines))

async def unregister(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/unregister MI -> removes all captains of MI | /unregister <user_id> -> removes one registration"""
    if not is_admin(update.effective_user.id): return
    if not ctx.args:
        return await update.message.reply_text(sc("usage: /unregister mi  or  /unregister user_id"))
    arg = ctx.args[0]
    if arg in DB["regs"]:
        team = DB["regs"].pop(arg)["team"]; save(DB)
        return await update.message.reply_text(f"✅ {sc('removed one registration from')} {team}.")
    team = arg.upper()
    ids = [u for u, r in DB["regs"].items() if r["team"] == team]
    if not ids: return await update.message.reply_text(sc("nothing found to remove."))
    for u in ids: del DB["regs"][u]
    save(DB)
    await update.message.reply_text(f"✅ {team} {sc('reset — all registrations removed.')}")

# ---------------------------------------------------------------- membership
async def is_member(bot, chat_id, user_id):
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
                            ChatMemberStatus.OWNER) or (m.status == ChatMemberStatus.RESTRICTED and m.is_member)
    except Exception as e:
        log.warning("member check failed for %s: %s", chat_id, e)
        return False

# ---------------------------------------------------------------- callbacks
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data

    if data == "taken":
        return await q.answer(sc("🔒 this team is locked! pick another."), show_alert=True)

    if data == "home":
        await q.answer(); ctx.user_data.clear()
        return await show(q, WELCOME, main_kb())

    if data == "owner":
        await q.answer()
        name, bio = None, None
        try:
            c = await ctx.bot.get_chat(OWNER_ID)
            name, bio = c.full_name, getattr(c, "bio", None)
        except Exception as e:
            log.debug("owner fetch failed: %s", e)
        text = (f"👑 {B('owner profile')}\n\n"
                + (f"{B('name')}: {esc(name)}\n" if name else "")
                + f"{B('username')}: @{esc(OWNER_USERNAME)}\n"
                + f"{B('id')}: <code>{OWNER_ID}</code>\n"
                + (f"{B('bio')}: {esc(bio)}\n" if bio else "")
                + f"\n{B('for any queries, contact the owner.')}")
        kb = Markup([[Btn(sc("💬 contact owner"), url=f"https://t.me/{OWNER_USERNAME}")],
                     [Btn(sc("⬅️ back"), callback_data="home")]])
        return await show(q, text, kb)

    if data == "reg":
        await q.answer()
        if str(uid) in DB["regs"]:
            r = DB["regs"][str(uid)]
            return await show(q, f"✅ {B('you already registered')} <b>{esc(r['team'])}</b>.", back_kb())
        if not (DB["group"] and DB["channel"]):
            return await show(q, f"⚠️ {B('registration is not open yet. please try later.')}", back_kb())
        ctx.user_data["step"] = "verify"
        return await show(q, VERIFY_TXT, verify_kb())

    if data == "verify":
        ok_g = await is_member(ctx.bot, DB["group"]["id"], uid)
        ok_c = await is_member(ctx.bot, DB["channel"]["id"], uid)
        if not (ok_g and ok_c):
            miss = " & ".join(n for n, ok in (("group", ok_g), ("channel", ok_c)) if not ok)
            return await q.answer(sc(f"❌ you haven't joined the {miss} yet!"), show_alert=True)
        await q.answer(sc("✅ verified!"))
        ctx.user_data["step"] = "team"
        return await show(q, f"✅ {B('verified!')}\n\n🏏 {B('step 2 — select your team')}\n"
                             f"{B('(🔒 = locked • max ' + str(MAX_PER_TEAM) + ' per team)')}", team_kb())

    if data.startswith("team:"):
        if ctx.user_data.get("step") != "team":
            return await q.answer(sc("send /start and begin again."), show_alert=True)
        team = data.split(":")[1]
        if team in locked_teams():
            await q.answer(sc("🔒 team just got locked! pick another."), show_alert=True)
            return await show(q, f"🏏 {B('select your team')}\n{B('(🔒 = locked • max ' + str(MAX_PER_TEAM) + ' per team)')}", team_kb())
        await q.answer()
        ctx.user_data.update(team=team, step="captain")
        return await show(q, f"{B('team')}: <b>{team}</b> ✅\n\n👤 {B('step 3 — send the captain username')}\n"
                             f"{B('example')}: <code>@username</code>")

# ---------------------------------------------------------------- text flow
UNAME = re.compile(r"^@?[A-Za-z0-9_]{5,32}$")
PROMPTS = {"captain": ("vice", f"🧑‍🤝‍🧑 {B('step 4 — send the vice-captain username')}"),
           "vice": ("retention", f"🔁 {B('step 5 — send the retention username')}")}

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": return
    step = ctx.user_data.get("step")
    if step not in ("captain", "vice", "retention"):
        return
    txt = update.message.text.strip()
    if not UNAME.match(txt):
        return await update.message.reply_text(f"❌ {sc('invalid username. send like @username')}")
    ctx.user_data[step] = "@" + txt.lstrip("@")

    if step in PROMPTS:
        nxt, prompt = PROMPTS[step]
        ctx.user_data["step"] = nxt
        return await update.message.reply_text(prompt, parse_mode=ParseMode.HTML)

    d, u = ctx.user_data, update.effective_user
    if d["team"] in locked_teams():
        d["step"] = "team"
        return await update.message.reply_text(
            f"⚠️ {sc('sorry, that team just got locked. pick another:')}", reply_markup=team_kb())
    reg = {"team": d["team"], "captain": d["captain"], "vice": d["vice"],
           "retention": d["retention"], "by_id": u.id,
           "by_name": u.full_name, "by_username": u.username,
           "time": datetime.now().strftime("%d %b %Y, %H:%M")}
    DB["regs"][str(u.id)] = reg; save(DB)
    ctx.user_data.clear()

    await update.message.reply_text(
        f"🎉 {B('registration complete!')}\n\n"
        f"🏏 {B('team')}: <b>{reg['team']}</b>\n"
        f"👤 {B('captain')}: {esc(reg['captain'])}\n"
        f"🧑‍🤝‍🧑 {B('vice-captain')}: {esc(reg['vice'])}\n"
        f"🔁 {B('retention')}: {esc(reg['retention'])}", parse_mode=ParseMode.HTML)

    if DB["log"]:
        by = f"@{esc(u.username)}" if u.username else f'<a href="tg://user?id={u.id}">{esc(u.full_name)}</a>'
        msg = (f"📋 {B('new team registration')}\n━━━━━━━━━━━━━━━━\n"
               f"🏏 {B('team')}: <b>{reg['team']}</b>\n"
               f"👤 {B('captain')}: {esc(reg['captain'])}\n"
               f"🧑‍🤝‍🧑 {B('vice-captain')}: {esc(reg['vice'])}\n"
               f"🔁 {B('retention')}: {esc(reg['retention'])}\n━━━━━━━━━━━━━━━━\n"
               f"🙋 {B('registered by')}: {by} (<code>{u.id}</code>)\n🕒 {reg['time']}")
        logo = DB["logos"].get(reg["team"])
        try:
            if logo:
                await ctx.bot.send_photo(DB["log"]["id"], logo, caption=msg, parse_mode=ParseMode.HTML)
            else:
                await ctx.bot.send_message(DB["log"]["id"], msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.error("log send failed: %s", e)
    else:
        log.warning("Log chat not set (/setlog)")

# ---------------------------------------------------------------- main
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("addfile", addfile))
    app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r"^/addfile"), addfile))
    app.add_handler(CommandHandler("setgroup", setter("group", "tour group")))
    app.add_handler(CommandHandler("setchannel", setter("channel", "tour channel")))
    app.add_handler(CommandHandler("setlog", setter("log", "log chat", needs_link=False)))
    app.add_handler(CommandHandler("setteamlogo", setteamlogo))
    app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r"^/setteamlogo"), setteamlogo))
    app.add_handler(CommandHandler("teams", teams_cmd))
    app.add_handler(CommandHandler("unregister", unregister))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_text))
    log.info("MPL bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
