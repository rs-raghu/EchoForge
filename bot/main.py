import os
import sys
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
)
from dotenv import load_dotenv

# Ensure the root directory is in the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db_manager
# We will create this file next to handle the background scraping!
try:
    from discovery import chart_scraper
except ImportError:
    chart_scraper = None

from utils.logger import get_logger

log = get_logger(__name__)
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Conversation States
WAITING_FOR_NATIVE_LYRICS = 1

# --- UI GENERATORS ---

def build_main_dashboard():
    """Builds the /start Main Menu showing the queue and active jobs."""
    jobs = db_manager.get_active_jobs()
    
    text = "🎛️ *EchoForge Master Control*\n\n*Active Jobs:*\n"
    keyboard = []
    
    if not jobs:
        text += "_No active jobs. Everything is caught up!_\n"
    else:
        for job in jobs:
            macro = job['macro']
            title = job['title']
            text += f"• `[{macro}]` {title}\n"
            keyboard.append([InlineKeyboardButton(f"⚙️ Open: {title}", callback_data=f"open_panel:{job['video_id']}")])
            
    text += "\n*Actions:*"
    keyboard.append([InlineKeyboardButton("▶️ Fetch Next from Queue", callback_data="fetch_next")])
    keyboard.append([InlineKeyboardButton("🔍 Run Chart Scraper", callback_data="run_scraper")])
    keyboard.append([InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="refresh_main")])
    
    return text, InlineKeyboardMarkup(keyboard)

def build_song_panel(song):
    """Builds the dynamic Control Panel for a specific song."""
    title = song['title']
    macro = song['current_macro_state']
    micro = song['current_micro_state']
    target = song['target_macro_state']
    
    text = (
        f"🎵 *{title}*\n"
        f"👤 {song['artist']}\n"
        f"────────────────\n"
        f"🎯 *Target:* `{target}`\n"
        f"📊 *Status:* `{macro}`\n"
        f"🔍 *Activity:* `{micro}`\n\n"
    )

    keyboard = []

    # Dynamic Buttons based on State
    if macro in ['STAGED', 'PAUSED']:
        text += "_Ready to proceed. Select a target state:_"
        keyboard.append([
            InlineKeyboardButton("▶️ Run Full (To Publish)", callback_data=f"set_target:{song['video_id']}:PUBLISHED"),
            InlineKeyboardButton("🛠️ Prepare Assets Only", callback_data=f"set_target:{song['video_id']}:ASSETS_READY")
        ])
    
    elif macro == 'LYRICS_REVIEW_PENDING':
        text += "⚠️ *Action Required: Review fetched lyrics.*"
        keyboard.append([InlineKeyboardButton("✅ Approve Lyrics", callback_data=f"approve_lyrics:{song['video_id']}")])
        keyboard.append([InlineKeyboardButton("✏️ Edit Natively", callback_data=f"edit_lyrics_native:{song['video_id']}")])
        
    elif macro == 'PREVIEW_PENDING':
        text += "🎬 *Video Rendered! Ready for upload.*"
        keyboard.append([InlineKeyboardButton("🚀 Upload to YouTube", callback_data=f"set_target:{song['video_id']}:PUBLISHED")])
        
    elif macro == 'FAILED':
        text += "❌ *The pipeline crashed. Check the logs.*"
        keyboard.append([InlineKeyboardButton("🔄 Retry Phase", callback_data=f"set_target:{song['video_id']}:{target}")])

    # Universal Buttons (Always available if it's currently running)
    if macro not in ['PAUSED', 'STAGED', 'LYRICS_REVIEW_PENDING', 'PREVIEW_PENDING', 'FAILED', 'DISCARDED']:
        keyboard.append([InlineKeyboardButton("🛑 ABORT (Kill Process)", callback_data=f"abort:{song['video_id']}")])
        keyboard.append([InlineKeyboardButton("⏸️ Pause at Checkpoint", callback_data=f"pause:{song['video_id']}")])

    keyboard.append([InlineKeyboardButton("🗑️ Discard Song", callback_data=f"discard:{song['video_id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_main")])

    return text, InlineKeyboardMarkup(keyboard)

# --- LIVE UPDATER ---

async def live_panel_updater(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, video_id: str):
    """Refreshes the song panel every 3 seconds to show micro-state changes."""
    last_micro = ""
    while True:
        await asyncio.sleep(3)
        song = db_manager.get_song(video_id)
        if not song:
            break
            
        # Only edit if state changed to save Telegram API calls
        if song['current_micro_state'] != last_micro or song['current_macro_state'] in ['PAUSED', 'LYRICS_REVIEW_PENDING', 'PREVIEW_PENDING']:
            last_micro = song['current_micro_state']
            text, markup = build_song_panel(song)
            try:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="Markdown", reply_markup=markup)
            except Exception:
                pass 

        # Stop the background watcher if it reaches a resting state
        if song['current_macro_state'] in ['PAUSED', 'LYRICS_REVIEW_PENDING', 'PREVIEW_PENDING', 'PUBLISHED', 'FAILED', 'DISCARDED']:
            break

# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db_manager.init_db()
    text, markup = build_main_dashboard()
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
    return ConversationHandler.END

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")
    cmd = data[0]
    video_id = data[1] if len(data) > 1 else None

    # --- MAIN MENU LOGIC ---
    if cmd in ["back_to_main", "refresh_main"]:
        text, markup = build_main_dashboard()
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        return ConversationHandler.END

    if cmd == "run_scraper":
        await query.edit_message_text("🔍 *Scraping global charts...* This might take a minute.", parse_mode="Markdown")
        try:
            if chart_scraper:
                # Assuming our scraper will return a list of dictionaries
                songs = await asyncio.to_thread(chart_scraper.scrape_top_charts, limit=20)
                if songs:
                    added = db_manager.add_discovered_songs(songs)
                    await query.message.reply_text(f"✅ *Scraper finished!* Added {added} new unique songs to the queue.", parse_mode="Markdown")
                else:
                    await query.message.reply_text("⚠️ Scraper finished, but no songs were found.")
            else:
                await query.message.reply_text("❌ `discovery/chart_scraper.py` is not built yet!")
        except Exception as e:
            await query.message.reply_text(f"❌ Scraper failed: {e}")
            
        text, markup = build_main_dashboard()
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
        return ConversationHandler.END

    if cmd == "fetch_next":
        song = db_manager.pop_next_queued_song()
        if not song:
            await query.edit_message_text("📭 The queue is empty! Click 'Run Chart Scraper' first.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]]))
            return ConversationHandler.END
        
        full_song = db_manager.get_song(song['video_id'])
        text, markup = build_song_panel(full_song)
        msg = await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        return ConversationHandler.END

    if cmd == "open_panel":
        song = db_manager.get_song(video_id)
        text, markup = build_song_panel(song)
        msg = await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        
        if song['current_macro_state'] not in ['PAUSED', 'STAGED', 'LYRICS_REVIEW_PENDING', 'PREVIEW_PENDING', 'FAILED']:
             asyncio.create_task(live_panel_updater(context, query.message.chat_id, msg.message_id, video_id))
        return ConversationHandler.END

    # --- PROCESS CONTROL LOGIC ---
    if cmd == "set_target":
        target = data[2]
        db_manager.set_target_state(video_id, target)
        song = db_manager.get_song(video_id)
        text, markup = build_song_panel(song)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        
        # Start the watcher—the Orchestrator is about to pick this up!
        asyncio.create_task(live_panel_updater(context, query.message.chat_id, query.message.message_id, video_id))

    elif cmd == "abort":
        db_manager.request_abort(video_id)
        await query.answer("🛑 Kill signal sent to Orchestrator!")

    elif cmd == "pause":
        db_manager.set_target_state(video_id, "PAUSED")
        await query.answer("⏸️ Pausing at next safe checkpoint...")

    elif cmd == "discard":
        db_manager.update_state(video_id, macro='DISCARDED', micro='IDLE')
        await query.edit_message_text("🗑️ Song discarded.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="back_to_main")]]))

    # --- LYRICS REVIEW LOGIC ---
    elif cmd == "approve_lyrics":
        db_manager.update_state(video_id, macro='LYRICS_APPROVED', micro='IDLE')
        song = db_manager.get_song(video_id)
        text, markup = build_song_panel(song)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)

    elif cmd == "edit_lyrics_native":
        song = db_manager.get_song(video_id)
        workspace = song['workspace_dir']
        # If workspace isn't set, default to a fallback
        if not workspace:
            workspace = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'workspaces', video_id)
        
        lyrics_path = os.path.join(workspace, "lyrics.txt")
        
        try:
            with open(lyrics_path, "r", encoding="utf-8") as f:
                lyrics_text = f.read()
        except Exception:
            lyrics_text = "No lyrics found. Type your lyrics here."

        await query.message.reply_text(f"✏️ *Editing Lyrics for {song['title']}*\n\nCopy the text below, fix the errors, and reply to this message:\n\n`{lyrics_text}`", parse_mode="Markdown")
        
        context.user_data['editing_video_id'] = video_id
        context.user_data['editing_path'] = lyrics_path
        return WAITING_FOR_NATIVE_LYRICS

    return ConversationHandler.END

# --- NATIVE TEXT EDITOR HANDLER ---

async def handle_native_lyrics_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_lyrics = update.message.text
    lyrics_path = context.user_data.get('editing_path')
    video_id = context.user_data.get('editing_video_id')

    if not lyrics_path or not video_id:
        await update.message.reply_text("❌ Context lost. Please click 'Edit Natively' again.")
        return ConversationHandler.END

    os.makedirs(os.path.dirname(lyrics_path), exist_ok=True)
    with open(lyrics_path, "w", encoding="utf-8") as f:
        f.write(new_lyrics)

    db_manager.update_state(video_id, macro='LYRICS_APPROVED', micro='IDLE')
    
    await update.message.reply_text("✅ *Lyrics saved and approved!*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_to_main")]]))
    
    context.user_data.clear()
    return ConversationHandler.END

# --- APP BOOTSTRAP ---

def main():
    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN missing in .env file!")
        return

    log.info("🤖 EchoForge Telegram Dashboard Booting...")
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_router)
        ],
        states={
            WAITING_FOR_NATIVE_LYRICS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_native_lyrics_reply)]
        },
        fallbacks=[CommandHandler("start", start)]
    )

    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()