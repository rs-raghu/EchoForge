import asyncio
import os
import re
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from dotenv import load_dotenv
import master_controller
import auto_discovery
import db_manager

# --- CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SECRET_PASSWORD = os.getenv("SECRET_PASSWORD")

if not BOT_TOKEN:
    raise ValueError("❌ No TELEGRAM_BOT_TOKEN found in .env file!")

WAITING_FOR_ACTION, WAITING_FOR_EDIT_ARTIST, WAITING_FOR_LINK, WAITING_FOR_TITLE, WAITING_FOR_ARTIST = range(5)


# ============================================================
# MARKDOWN SAFETY HELPER
# ============================================================

def _md(text: str) -> str:
    """
    Escapes all characters that Telegram's legacy Markdown parser treats as
    special: _ * ` [
    Call this on EVERY piece of user-supplied data (song titles, artist names,
    file paths, error messages) before embedding it in a parse_mode='Markdown'
    message.  Static strings you write yourself don't need escaping.
    """
    if not isinstance(text, str):
        text = str(text)
    return re.sub(r'([_*`\[])', r'\\\1', text)


# ============================================================
# PIPELINE TRIGGER
# ============================================================

async def trigger_pipeline(message_obj, context, song_data):
    """Runs the master controller and handles all return signals."""
    await message_obj.reply_text(
        "⚙️ **Master Controller Engaged!** Starting the pipeline...\n*(Check your console for live logs)*",
        parse_mode='Markdown'
    )

    try:
        result = await asyncio.to_thread(master_controller.run_pipeline, song_data)

        if result is True:
            await message_obj.reply_text(
                f"🎉 **Pipeline Complete!** Processing for `{_md(song_data['title'])}` has finished.",
                parse_mode='Markdown'
            )

        elif result == "UNAVAILABLE":
            await message_obj.reply_text(
                f"⛔ **Video Unavailable:** `{_md(song_data['title'])}` is blocked or removed.\n"
                f"⏭️ Auto-skipping to the next song...",
                parse_mode='Markdown'
            )
            context.user_data['skip_count'] = context.user_data.get('skip_count', 0) + 1
            msg = await message_obj.reply_text("🔍 Fetching next valid song from charts...")
            await fetch_and_present_song(context, msg)

        elif result == "NEEDS_MANUAL_LYRICS":
            context.user_data['stalled_song'] = song_data
            await message_obj.reply_text(
                f"⚠️ **Lyrics Fetch Failed for** `{_md(song_data['title'])}`\n\n"
                f"The automated scrapers couldn't find the lyrics.\n"
                f"📎 Please upload a `.lrc` or `.txt` file here to continue.",
                parse_mode='Markdown'
            )

        else:
            await message_obj.reply_text(
                f"❌ **Pipeline Failed** for `{_md(song_data['title'])}`. Check the console logs.",
                parse_mode='Markdown'
            )

    except Exception as e:
        await message_obj.reply_text(
            f"❌ **Fatal Pipeline Error:** `{_md(e)}`",
            parse_mode='Markdown'
        )


# ============================================================
# FILE UPLOAD HANDLER
# ============================================================

async def handle_lyrics_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catches document uploads and resumes the stalled pipeline."""
    stalled_song = context.user_data.get('stalled_song')

    if not stalled_song:
        return

    document = update.message.document
    file_name = document.file_name.lower()

    if not (file_name.endswith('.lrc') or file_name.endswith('.txt')):
        await update.message.reply_text("❌ Invalid format. Please upload a `.lrc` or `.txt` file.")
        return

    await update.message.reply_text("📥 Downloading lyrics file...")

    try:
        file = await context.bot.get_file(document.file_id)
        workspace = stalled_song['workspace_dir']
        video_id  = stalled_song['video_id']

        file_ext  = file_name.split('.')[-1]
        save_path = os.path.join(workspace, f"lyrics.{file_ext}")
        await file.download_to_drive(save_path)

        if file_ext == 'lrc':
            db_manager.update_song_status(video_id, "LYRICS_READY")
        else:
            db_manager.update_song_status(video_id, "LYRICS_FETCHED")

        await update.message.reply_text(
            f"✅ Lyrics saved!\n🔄 Resuming pipeline for `{_md(stalled_song['title'])}`...",
            parse_mode='Markdown'
        )

        context.user_data['stalled_song'] = None
        asyncio.create_task(trigger_pipeline(update.message, context, stalled_song))

    except Exception as e:
        await update.message.reply_text(f"❌ Failed to process upload: {_md(e)}")


# ============================================================
# STANDARD MENU LOGIC
# ============================================================

async def fetch_and_present_song(context: ContextTypes.DEFAULT_TYPE, message_obj):
    skip_count = context.user_data.get('skip_count', 0)
    top_song   = await asyncio.to_thread(auto_discovery.get_top_song, skip_count)

    if top_song:
        context.user_data['current_song'] = top_song

        text = (
            f"🏆 **Valid Song \\#{skip_count + 1} Found\\!**\n\n"
            f"🗣️ **Artist:** {_md(top_song['artist'])}\n"
            f"🎶 **Title:** {_md(top_song['title'])}\n"
            f"🔗 **URL:** {top_song['url']}\n\n"
            f"What would you like to do?"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Continue",            callback_data='continue'),
             InlineKeyboardButton("✏️ Edit Artist",         callback_data='edit_artist')],
            [InlineKeyboardButton("⏭️ Select Next Song",    callback_data='next_song')],
            [InlineKeyboardButton("✍️ Manual Entry Instead", callback_data='manual')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message_obj.edit_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        return WAITING_FOR_ACTION
    else:
        await message_obj.edit_text("❌ No more valid songs found in the charts.")
        return ConversationHandler.END


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == SECRET_PASSWORD:
        msg = await update.message.reply_text("✅ Password verified. Fetching the top trending song...")
        context.user_data['skip_count'] = 0
        return await fetch_and_present_song(context, msg)
    else:
        await update.message.reply_text("❌ Unauthorized. Invalid or missing password.")
        return ConversationHandler.END


async def action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    song = context.user_data.get('current_song')

    if query.data == 'continue':
        workspace_dir       = auto_discovery.create_workspace(song)
        song['workspace_dir'] = workspace_dir
        await query.edit_message_text(
            f"✅ **Confirmed\\!**\n"
            f"Workspace staged at: `{_md(workspace_dir)}`\n"
            f"📄 `metadata.json` generated.",
            parse_mode='Markdown'
        )
        asyncio.create_task(trigger_pipeline(query.message, context, song))
        return ConversationHandler.END

    elif query.data == 'edit_artist':
        await query.edit_message_text(
            "✏️ **Editing Artist Name**\n\nPlease type the clean artist name you want to save:"
        )
        return WAITING_FOR_EDIT_ARTIST

    elif query.data == 'next_song':
        context.user_data['skip_count'] += 1
        await query.edit_message_text("⏭️ Fetching the next valid song from the charts...")
        return await fetch_and_present_song(context, query.message)

    elif query.data == 'manual':
        await query.edit_message_text("🔗 **Step 1/3:** Please send the YouTube Link for the song:")
        return WAITING_FOR_LINK


async def handle_edit_artist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_artist            = update.message.text.strip()
    song                  = context.user_data.get('current_song')
    song['artist']        = new_artist
    workspace_dir         = auto_discovery.create_workspace(song)
    song['workspace_dir'] = workspace_dir
    await update.message.reply_text(
        f"✅ **Artist Updated & Confirmed\\!**\n"
        f"🗣️ **New Artist:** {_md(song['artist'])}\n"
        f"Workspace staged at: `{_md(workspace_dir)}`",
        parse_mode='Markdown'
    )
    asyncio.create_task(trigger_pipeline(update.message, context, song))
    return ConversationHandler.END


async def handle_manual_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['manual_url'] = update.message.text.strip()
    await update.message.reply_text("🎵 **Step 2/3:** Great\\! Now send the Song Title:", parse_mode='Markdown')
    return WAITING_FOR_TITLE


async def handle_manual_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['manual_title'] = update.message.text.strip()
    await update.message.reply_text("🗣️ **Step 3/3:** Perfect\\! Finally, send the Artist Name:", parse_mode='Markdown')
    return WAITING_FOR_ARTIST


async def handle_manual_artist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    artist = update.message.text.strip()
    title  = context.user_data['manual_title']
    url    = context.user_data['manual_url']

    video_id = "MANUAL_ID"
    if "v=" in url:
        video_id = url.split("v=")[-1].split("&")[0]
    elif "youtu.be/" in url:
        video_id = url.split("youtu.be/")[-1].split("?")[0]

    song_data = {
        "title": title, "artist": artist, "url": url,
        "video_id": video_id, "rank": 0, "weekly_views": 0,
        "search_query": f"{artist} {title} official audio"
    }

    workspace_dir             = auto_discovery.create_workspace(song_data)
    song_data['workspace_dir'] = workspace_dir

    await update.message.reply_text(
        f"✅ **Manual entry saved & Workspace created\\!**\n"
        f"🎵 **Title:** {_md(song_data['title'])}",
        parse_mode='Markdown'
    )
    asyncio.create_task(trigger_pipeline(update.message, context, song_data))
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operation canceled.")
    return ConversationHandler.END


def main():
    print("🤖 Telegram Bot is booting up...")
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FOR_ACTION:      [CallbackQueryHandler(action_handler)],
            WAITING_FOR_EDIT_ARTIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_artist)],
            WAITING_FOR_LINK:        [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_link)],
            WAITING_FOR_TITLE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_title)],
            WAITING_FOR_ARTIST:      [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_artist)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_lyrics_upload))

    print("✅ Bot is online and listening!")
    app.run_polling()


if __name__ == "__main__":
    main()