import logging
import os
import qbittorrentapi
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("qbit-bot")

# --- Config ---
QBIT_URL = os.getenv("QBIT_URL", "http://192.168.0.43:7282")
QBIT_USER = os.getenv("QBIT_USERNAME", "admin")
QBIT_PASS = os.getenv("QBIT_PASSWORD", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHATS = [int(x) for x in os.getenv("TELEGRAM_ALLOWED_CHATS", "").split(",") if x.strip()]

CATEGORIES = [c.strip() for c in os.getenv("DEFAULT_CATEGORIES", "docus,peliculas,series,varios,conciertos,musica").split(",") if c.strip()]

if not TELEGRAM_TOKEN:
    raise SystemExit("Falta TELEGRAM_BOT_TOKEN")
if not ALLOWED_CHATS:
    log.warning("No hay TELEGRAM_ALLOWED_CHATS; el bot no responderá a nadie hasta configurarlo.")

# --- qBittorrent client ---
qbt = qbittorrentapi.Client(host=QBIT_URL, username=QBIT_USER, password=QBIT_PASS)
last_ok = True

def allowed(chat_id: int) -> bool:
    return (not ALLOWED_CHATS) or (chat_id in ALLOWED_CHATS)

# --- Commands ---
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_chat.id): return
    await update.message.reply_text("🤖 Bot de qBittorrent listo. Usa /help para comandos.")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_chat.id): return
    await update.message.reply_text(
        "Comandos:\n"
        "/status – estado de qBittorrent\n"
        "/list [categoria] – lista torrents (máx 20)\n"
        "/add <magnet|url> [categoria] – añade torrent\n"
        "/pause <hash>|all – pausa\n"
        "/resume <hash>|all – reanuda\n"
        "/category <hash> <categoria> – asigna categoría\n"
        "/categories – muestra categorías disponibles"
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_chat.id): return
    try:
        ver = qbt.app_version()
        transfer = qbt.transfer_info
        text = (f"✅ qBittorrent v{ver}\n"
                f"⬇ {transfer.dl_info_speed/1024/1024:.2f} MB/s  ⬆ {transfer.up_info_speed/1024/1024:.2f} MB/s")
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"❌ No se pudo conectar: {e}")

async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_chat.id): return
    try:
        cats = list(qbt.torrent_categories.categories.keys())
        if not cats:
            await update.message.reply_text("No hay categorías en qBittorrent.")
            return
        await update.message.reply_text("Categorías:\n- " + "\n- ".join(cats))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_chat.id): return
    try:
        category = context.args[0] if context.args else None
        torrents = qbt.torrents_info(category=category) if category else qbt.torrents_info()
        torrents = sorted(torrents, key=lambda t: getattr(t, "added_on", 0), reverse=True)[:20]
        if not torrents:
            await update.message.reply_text("No hay torrents.")
            return
        lines = []
        for t in torrents:
            prog = int(t.progress * 100) if t.progress is not None else 0
            lines.append(f"• [{prog:3d}%] {t.name[:60]}\n  {t.state}  {t.category or ''}  {t.hash[:8]}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Error listando: {e}")

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_chat.id): return
    if not context.args:
        await update.message.reply_text("Uso: /add <magnet|url> [categoria]")
        return
    url = context.args[0]
    category = context.args[1] if len(context.args) > 1 else None
    try:
        if category and category not in CATEGORIES:
            await update.message.reply_text(f"Categoría no permitida. Usa: {', '.join(CATEGORIES)}")
            return
        qbt.torrents_add(urls=url, category=category)
        await update.message.reply_text(f"✅ Añadido{f' en {category}' if category else ''}")
    except Exception as e:
        await update.message.reply_text(f"Error añadiendo: {e}")

async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_chat.id): return
    if not context.args:
        await update.message.reply_text("Uso: /pause <hash>|all")
        return
    arg = context.args[0].lower()
    if arg == "all":
        hashes = [t.hash for t in qbt.torrents_info()]
    else:
        hashes = [arg]
    qbt.torrents_pause(hashes="|".join(hashes))
    await update.message.reply_text("⏸️ Pausado.")

async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_chat.id): return
    if not context.args:
        await update.message.reply_text("Uso: /resume <hash>|all")
        return
    arg = context.args[0].lower()
    if arg == "all":
        hashes = [t.hash for t in qbt.torrents_info()]
    else:
        hashes = [arg]
    qbt.torrents_resume(hashes="|".join(hashes))
    await update.message.reply_text("▶️ Reanudado.")

async def cmd_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_chat.id): return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /category <hash> <categoria>")
        return
    h, cat = context.args[0], context.args[1]
    if cat not in CATEGORIES:
        await update.message.reply_text(f"Categoría no permitida. Usa: {', '.join(CATEGORIES)}")
        return
    qbt.torrents_set_category(hashes=h, category=cat)
    await update.message.reply_text(f"🏷️ Asignada categoría {cat} a {h[:8]}.")

# --- Monitor ---
async def monitor(app: Application):
    global last_ok
    for chat_id in ALLOWED_CHATS:
        try:
            _ = qbt.app_version()
            if not last_ok:
                await app.bot.send_message(chat_id, "✅ qBittorrent ha vuelto a responder.")
            last_ok = True
        except Exception:
            if last_ok:
                await app.bot.send_message(chat_id, "⚠️ qBittorrent no responde (¿apagado/caído?).")
            last_ok = False

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("category", cmd_category))

    sched = AsyncIOScheduler()
    sched.add_job(lambda: monitor(app), "interval", seconds=int(os.getenv("HEALTH_INTERVAL", "30")))
    sched.start()

    app.run_polling()

if __name__ == "__main__":
    main()
