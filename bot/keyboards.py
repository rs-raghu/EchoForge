from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def build_main_dashboard(jobs):
    """Builds the /start Main Menu showing the queue and active jobs."""
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