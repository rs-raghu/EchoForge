import asyncio
import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from dotenv import load_dotenv

import auto_discovery 

# --- CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SECRET_PASSWORD = os.getenv("SECRET_PASSWORD")

if not BOT_TOKEN:
    raise ValueError("❌ No TELEGRAM_BOT_TOKEN found in .env file!")

# Added a new state for editing the artist
WAITING_FOR_ACTION, WAITING_FOR_EDIT_ARTIST, WAITING_FOR_LINK, WAITING_FOR_TITLE, WAITING_FOR_ARTIST = range(5)

async def fetch_and_present_song(context: ContextTypes.DEFAULT_TYPE, message_obj):
    skip_count = context.user_data.get('skip_count', 0)
    top_song = await asyncio.to_thread(auto_discovery.get_top_song, skip_count) 
    
    if top_song:
        context.user_data['current_song'] = top_song
        
        text = (
            f"🏆 **Valid Song #{skip_count + 1} Found!**\n\n"
            f"🗣️ **Artist:** {top_song['artist']}\n"
            f"🎶 **Title:** {top_song['title']}\n"
            f"🔗 **URL:** {top_song['url']}\n\n"
            f"What would you like to do?"
        )
        # Added the Edit Artist button here
        keyboard = [
            [InlineKeyboardButton("✅ Continue", callback_data='continue'),
             InlineKeyboardButton("✏️ Edit Artist", callback_data='edit_artist')],
            [InlineKeyboardButton("⏭️ Select Next Song", callback_data='next_song')],
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
        workspace_dir = auto_discovery.create_workspace(song)
        song['workspace_dir'] = workspace_dir
        
        await query.edit_message_text(
            f"✅ **Confirmed!**\n"
            f"Workspace staged at: `{workspace_dir}`\n"
            f"📄 `metadata.json` generated.\n\n"
            f"*(Next steps of the pipeline will be triggered here!)*", 
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    # --- NEW: Edit Artist Logic ---
    elif query.data == 'edit_artist':
        await query.edit_message_text(
            f"✏️ **Editing Artist Name**\n"
            f"Current: `{song['artist']}`\n\n"
            f"Please type the clean artist name you want to save:"
        )
        return WAITING_FOR_EDIT_ARTIST

    elif query.data == 'next_song':
        context.user_data['skip_count'] += 1
        await query.edit_message_text("⏭️ Fetching the next valid song from the charts...")
        return await fetch_and_present_song(context, query.message)

    elif query.data == 'manual':
        await query.edit_message_text("🔗 **Step 1/3:** Please send the YouTube Link for the song:")
        return WAITING_FOR_LINK

# --- NEW: Process the edited artist ---
async def handle_edit_artist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_artist = update.message.text.strip()
    song = context.user_data.get('current_song')
    
    # Overwrite the messy scraped artist with your clean input
    song['artist'] = new_artist
    
    # Now create the folder and save the metadata
    workspace_dir = auto_discovery.create_workspace(song)
    song['workspace_dir'] = workspace_dir

    await update.message.reply_text(
        f"✅ **Artist Updated & Confirmed!**\n"
        f"🗣️ **New Artist:** {song['artist']}\n"
        f"Workspace staged at: `{workspace_dir}`\n"
        f"📄 `metadata.json` generated.\n\n"
        f"*(Next steps of the pipeline will be triggered here!)*",
        parse_mode='Markdown'
    )
    return ConversationHandler.END

# --- MANUAL ENTRY STEPS ---
async def handle_manual_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['manual_url'] = update.message.text.strip()
    await update.message.reply_text("🎵 **Step 2/3:** Great! Now send the Song Title:")
    return WAITING_FOR_TITLE

async def handle_manual_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['manual_title'] = update.message.text.strip()
    await update.message.reply_text("🗣️ **Step 3/3:** Perfect! Finally, send the Artist Name:")
    return WAITING_FOR_ARTIST

async def handle_manual_artist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    artist = update.message.text.strip()
    title = context.user_data['manual_title']
    url = context.user_data['manual_url']
    
    video_id = "MANUAL_ID"
    if "v=" in url:
        video_id = url.split("v=")[-1].split("&")[0]
    elif "youtu.be/" in url:
        video_id = url.split("youtu.be/")[-1].split("?")[0]
        
    song_data = {
        "title": title,
        "artist": artist,
        "url": url,
        "video_id": video_id,
        "rank": 0,
        "weekly_views": 0,
        "search_query": f"{artist} {title} official audio"
    }
    
    workspace_dir = auto_discovery.create_workspace(song_data)
    song_data['workspace_dir'] = workspace_dir

    await update.message.reply_text(
        f"✅ **Manual entry saved & Workspace created!**\n"
        f"🎵 **Title:** {song_data['title']}\n"
        f"🗣️ **Artist:** {song_data['artist']}\n"
        f"🔗 **URL:** {song_data['url']}\n"
        f"📁 **Folder:** `{workspace_dir}`\n"
        f"📄 `metadata.json` generated.\n\n"
        f"*(Next steps of the pipeline will be triggered here!)*",
        parse_mode='Markdown'
    )
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
            WAITING_FOR_ACTION: [CallbackQueryHandler(action_handler)],
            WAITING_FOR_EDIT_ARTIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_artist)],
            WAITING_FOR_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_link)],
            WAITING_FOR_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_title)],
            WAITING_FOR_ARTIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_artist)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    print("✅ Bot is online and listening!")
    app.run_polling()

if __name__ == "__main__":
    main()