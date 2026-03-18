import asyncio
import threading
import os
import subprocess
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
    Escapes all characters that Telegram MarkdownV2 treats as special.
    Must be called on every piece of dynamic data (song titles, artist names,
    file paths, error messages) before embedding it in a MarkdownV2 message.

    MarkdownV2 special characters: _ * [ ] ( ) ~ ` > # + - = | { } . !
    Note: content placed inside backtick code spans is rendered literally —
    you can use the raw value there and skip _md() entirely.
    """
    if not isinstance(text, str):
        text = str(text)
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\-\\])', r'\\\1', text)


# ============================================================
# PROGRESS HEARTBEAT
# ============================================================

# Messages fired every 90 s while the pipeline runs in a background thread.
# Sequence mirrors the real phase order: download -> Demucs -> Whisper -> render.
# Each string is already MarkdownV2-safe (special chars manually escaped).
_HEARTBEAT_MESSAGES = [
    "🎵 *Phase 1:* Downloading and extracting audio\\.\\.\\.",
    "🎙️ *Phase 2:* Demucs is isolating vocals — this takes 5–20 min on CPU\\.",
    "🎙️ *Still isolating\\.\\.\\.* Hang tight, Demucs is thorough\\.",
    "🧠 *Phase 3:* Whisper is force\\-aligning lyrics to vocals\\.",
    "🧠 *Still aligning\\.\\.\\.* Whisper on CPU is slow but accurate\\.",
    "⏳ *Still running\\.\\.\\.* Whisper alignment can take up to 40 min\\.",
    "⏳ *Almost there?* If it feels stuck, check the console for errors\\.",
    "🎬 *Phase 4:* Remotion is rendering the final video — nearly done\\!",
]
_HEARTBEAT_INTERVAL = 90   # seconds between messages


async def _heartbeat(message_obj):
    """
    Sends a progress update every _HEARTBEAT_INTERVAL seconds.
    Works through _HEARTBEAT_MESSAGES in order, then repeats the last one
    indefinitely for unexpectedly long runs.
    Designed to be run as an asyncio task and cancelled externally.
    """
    for text in _HEARTBEAT_MESSAGES:
        await asyncio.sleep(_HEARTBEAT_INTERVAL)
        try:
            await message_obj.reply_text(text, parse_mode='MarkdownV2')
        except Exception:
            pass  # non-fatal — a single failed send doesn't stop the loop

    # All phase messages sent; keep pinging on very long runs.
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL)
        try:
            await message_obj.reply_text(
                "⏳ *Still running\\.\\.\\.* Check the console if concerned\\.",
                parse_mode='MarkdownV2'
            )
        except Exception:
            pass


async def _run_pipeline_with_heartbeat(message_obj, song_data, context):
    """
    Runs master_controller.run_pipeline() in a worker thread while
    _heartbeat() fires progress messages on the async event loop.

    Stores the active asyncio Task and a threading.Event cancel flag in
    context.bot_data so the /cancel command can reach them from anywhere.

    The heartbeat and bot_data are cleaned up in finally so they always
    stop, whether the pipeline succeeded, failed, or was cancelled.
    """
    # Fresh cancel event for this run — cleared so any previous cancel is gone
    cancel_event = threading.Event()
    context.bot_data["cancel_event"] = cancel_event

    heartbeat_task = asyncio.create_task(_heartbeat(message_obj))
    # Store a reference to the current asyncio task so /cancel can cancel it
    context.bot_data["active_pipeline_task"] = asyncio.current_task()

    try:
        result = await asyncio.to_thread(
            master_controller.run_pipeline, song_data, cancel_event
        )
        return result
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass  # expected — task was cancelled cleanly
        # Clear the active task reference so /cancel knows nothing is running
        context.bot_data.pop("active_pipeline_task", None)
        context.bot_data.pop("cancel_event", None)


# ============================================================
# PIPELINE TRIGGER
# ============================================================

async def trigger_pipeline(message_obj, context, song_data):
    """Runs the master controller and handles all return signals."""
    await message_obj.reply_text(
        "⚙️ *Master Controller Engaged\\!* Starting the pipeline\\.\\.\\.\n"
        "_\\(Check your console for live logs\\)_",
        parse_mode='MarkdownV2'
    )

    try:
        # _run_pipeline_with_heartbeat replaces the bare asyncio.to_thread call.
        # It runs the blocking pipeline in a thread while sending progress pings
        # every 90 s so the user knows the bot is alive during Demucs + Whisper.
        result = await _run_pipeline_with_heartbeat(message_obj, song_data, context)

        if isinstance(result, tuple) and result[0] == "PREVIEW_READY":
            _, video_path = result
            await _send_preview(message_obj, context, song_data, video_path)

        elif result is True:
            await message_obj.reply_text(
                f"🎉 *Pipeline Complete\\!* Processing for `{song_data['title']}` has finished\\.",
                parse_mode='MarkdownV2'
            )

        elif result == "UNAVAILABLE":
            await message_obj.reply_text(
                f"⛔ *Video Unavailable:* `{song_data['title']}` is blocked or removed\\.\n"
                f"⏭️ Auto\\-skipping to the next song\\.\\.\\.",
                parse_mode='MarkdownV2'
            )
            context.user_data['skip_count'] = context.user_data.get('skip_count', 0) + 1
            msg = await message_obj.reply_text("🔍 Fetching next valid song from charts\\.", parse_mode='MarkdownV2')
            await fetch_and_present_song(context, msg)

        elif result == "NEEDS_MANUAL_LYRICS":
            context.user_data['stalled_song'] = song_data
            await message_obj.reply_text(
                f"⚠️ *Lyrics Fetch Failed for* `{song_data['title']}`\n\n"
                f"The automated scrapers couldn't find the lyrics\\.\n"
                f"📎 Please upload a `.lrc` or `.txt` file here to continue\\.",
                parse_mode='MarkdownV2'
            )

        elif result == "CANCELLED":
            await message_obj.reply_text(
                f"🛑 *Pipeline cancelled* for `{song_data['title']}`\\. "
                "Progress has been saved \\— run /start to resume from where it stopped\\.",
                parse_mode='MarkdownV2'
            )

        else:
            await message_obj.reply_text(
                f"❌ *Pipeline Failed* for `{song_data['title']}`\\. Check the console logs\\.",
                parse_mode='MarkdownV2'
            )

    except Exception as e:
        await message_obj.reply_text(
            f"❌ *Fatal Pipeline Error:* `{str(e)}`",
            parse_mode='MarkdownV2'
        )


# ============================================================
# SAFE TASK WRAPPER
# ============================================================

async def _safe_pipeline_task(message_obj, context, song_data):
    """
    Thin wrapper around trigger_pipeline for use with asyncio.create_task().

    asyncio.create_task() is fire-and-forget: if the coroutine raises an
    unhandled exception, Python emits a "Task exception was never retrieved"
    warning to stderr and the user sees nothing.  This wrapper catches any
    exception that escapes trigger_pipeline (including errors from the opening
    reply_text call, which sits outside trigger_pipeline's own try/except),
    notifies the user with a plain-text fallback message, then re-raises so
    the full traceback still appears in the console log.
    """
    try:
        await trigger_pipeline(message_obj, context, song_data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await message_obj.reply_text(
                f"❌ *Background task crashed:* `{str(e)}`\n"
                f"Check the console for the full traceback\\.",
                parse_mode='MarkdownV2'
            )
        except Exception:
            # If even the error message fails (e.g. Telegram connection lost),
            # there is nothing more we can do — the traceback is already on stdout.
            pass
        raise


# ============================================================
# /status COMMAND
# ============================================================

# Emoji badge per pipeline status — used in the job list.
_STATUS_EMOJI = {
    "PENDING":        "🟡",
    "AUDIO_FETCHED":  "🎵",
    "LYRICS_FETCHED": "📝",
    "LYRICS_READY":   "✅",
    "ASSETS_READY":   "🎨",
    "VIDEO_CREATED":  "🎬",
    "UPLOADED":       "🚀",
    "UNAVAILABLE":    "⛔",
    "FAILED":         "❌",
}


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /status — no password required. Shows:
      - One-line count summary of every status currently in the DB.
      - The 15 most recently updated jobs, newest first.

    Example output:
      📊 Pipeline Status

      🚀 UPLOADED x3   🎬 VIDEO_CREATED x1   🟡 PENDING x1

      Recent jobs (newest first):
      🚀 Die With A Smile
         Lady Gaga & Bruno Mars · UPLOADED · 2026-03-01 14:22:00
    """
    db_manager.init_db()

    counts = db_manager.get_status_counts()   # {status: count}
    jobs   = db_manager.get_recent_jobs(limit=15)

    if not jobs:
        await update.message.reply_text(
            "📭 No jobs in the database yet\\. Run /start to kick off the pipeline\\.",
            parse_mode='MarkdownV2'
        )
        return

    # ── Summary line: "🚀 UPLOADED x3   🎬 VIDEO_CREATED x1" ─────────────────
    # Statuses are all-caps alphanumeric — safe without _md().
    # Counts are ints — safe. The separator is a plain space — safe.
    summary_parts = [
        f"{_STATUS_EMOJI.get(s, '?')} {s} x{c}"
        for s, c in counts.items()
    ]
    summary_line = _md("   ".join(summary_parts))

    # ── Job rows ──────────────────────────────────────────────────────────────
    # title / artist pass through _md() — may contain any user-entered chars.
    # status is all-caps alphanumeric, updated is a date string — both safe in
    # backtick code spans which Telegram renders literally.
    msg_lines = [
        "📊 *Pipeline Status*",
        "",
        summary_line,
        "",
        "*Recent jobs \\(newest first\\):*",
    ]
    for job in jobs:
        emoji = _STATUS_EMOJI.get(job["status"], "?")
        msg_lines.append(f"{emoji} *{_md(job['title'])}*")
        # \u00b7 is the middle dot · separator — a safe Unicode literal
        msg_lines.append(
            f"    {_md(job['artist'])} \u00b7 `{job['status']}` \u00b7 `{job['updated']}`"
        )

    await update.message.reply_text(
        "\n".join(msg_lines),
        parse_mode='MarkdownV2'
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
        await update.message.reply_text(
            "❌ Invalid format\\. Please upload a `.lrc` or `.txt` file\\.",
            parse_mode='MarkdownV2'
        )
        return

    await update.message.reply_text("📥 Downloading lyrics file\\.\\.\\.", parse_mode='MarkdownV2')

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
            f"✅ Lyrics saved\\!\n🔄 Resuming pipeline for `{stalled_song['title']}`\\.\\.\\.",
            parse_mode='MarkdownV2'
        )

        context.user_data['stalled_song'] = None
        asyncio.create_task(_safe_pipeline_task(update.message, context, stalled_song))

    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed to process upload: `{str(e)}`",
            parse_mode='MarkdownV2'
        )


# ============================================================
# STANDARD MENU LOGIC
# ============================================================

async def fetch_and_present_song(context: ContextTypes.DEFAULT_TYPE, message_obj):
    skip_count = context.user_data.get('skip_count', 0)
    top_song   = await asyncio.to_thread(auto_discovery.get_top_song, skip_count)

    if top_song:
        context.user_data['current_song'] = top_song

        text = (
            f"🏆 *Valid Song \\#{skip_count + 1} Found\\!*\n\n"
            f"🗣️ *Artist:* {_md(top_song['artist'])}\n"
            f"🎶 *Title:* {_md(top_song['title'])}\n"
            f"🔗 *URL:* `{top_song['url']}`\n\n"
            f"What would you like to do?"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Continue",            callback_data='continue'),
             InlineKeyboardButton("✏️ Edit Artist",         callback_data='edit_artist')],
            [InlineKeyboardButton("⏭️ Select Next Song",    callback_data='next_song')],
            [InlineKeyboardButton("✍️ Manual Entry Instead", callback_data='manual')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message_obj.edit_text(text, parse_mode='MarkdownV2', reply_markup=reply_markup)
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
            f"✅ *Confirmed\\!*\n"
            f"Workspace staged at: `{workspace_dir}`\n"
            f"📄 `metadata.json` generated\\.",
            parse_mode='MarkdownV2'
        )
        asyncio.create_task(_safe_pipeline_task(query.message, context, song))
        return ConversationHandler.END

    elif query.data == 'edit_artist':
        await query.edit_message_text(
            "✏️ Editing Artist Name\n\nPlease type the clean artist name you want to save:"
        )
        return WAITING_FOR_EDIT_ARTIST

    elif query.data == 'next_song':
        context.user_data['skip_count'] += 1
        await query.edit_message_text("⏭️ Fetching the next valid song from the charts...")
        return await fetch_and_present_song(context, query.message)

    elif query.data == 'manual':
        await query.edit_message_text("🔗 Step 1/3: Please send the YouTube Link for the song:")
        return WAITING_FOR_LINK


async def handle_edit_artist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_artist            = update.message.text.strip()
    song                  = context.user_data.get('current_song')
    song['artist']        = new_artist
    workspace_dir         = auto_discovery.create_workspace(song)
    song['workspace_dir'] = workspace_dir
    await update.message.reply_text(
        f"✅ *Artist Updated & Confirmed\\!*\n"
        f"🗣️ *New Artist:* {_md(song['artist'])}\n"
        f"Workspace staged at: `{workspace_dir}`",
        parse_mode='MarkdownV2'
    )
    asyncio.create_task(_safe_pipeline_task(update.message, context, song))
    return ConversationHandler.END


async def handle_manual_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['manual_url'] = update.message.text.strip()
    await update.message.reply_text(
        "🎵 *Step 2/3:* Great\\! Now send the Song Title:",
        parse_mode='MarkdownV2'
    )
    return WAITING_FOR_TITLE


async def handle_manual_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['manual_title'] = update.message.text.strip()
    await update.message.reply_text(
        "🗣️ *Step 3/3:* Perfect\\! Finally, send the Artist Name:",
        parse_mode='MarkdownV2'
    )
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
        f"✅ *Manual entry saved & Workspace created\\!*\n"
        f"🎵 *Title:* {_md(song_data['title'])}",
        parse_mode='MarkdownV2'
    )
    asyncio.create_task(_safe_pipeline_task(update.message, context, song_data))
    return ConversationHandler.END



# ============================================================
# VIDEO PREVIEW
# ============================================================

# Telegram bot API hard limit for video uploads.
# We leave a 5 MB margin so borderline clips don't fail mid-send.
_PREVIEW_MAX_BYTES   = 45 * 1024 * 1024   # 45 MB
_PREVIEW_DURATION_S  = 35                  # seconds of footage to include


async def _make_preview_clip(video_path: str) -> str | None:
    """
    Uses ffmpeg to produce a compressed 35-second preview clip from the
    rendered video.

    Encoding choices:
      - First 35 s covers the 5 s intro screen + first 30 s of lyrics —
        enough to verify sync quality.
      - Scale to 720p so the file stays well under Telegram's 50 MB limit.
      - CRF 28 + preset fast: visually acceptable quality at small file size.
      - AAC 128 kbps: preserves enough audio to judge sync accuracy.

    Returns the path to the preview file, or None if ffmpeg failed.
    """
    preview_path = video_path.replace(".mp4", "_preview.mp4")

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "ffmpeg", "-y",
                "-i", video_path,
                "-t", str(_PREVIEW_DURATION_S),
                "-vf", "scale=-2:720",
                "-c:v", "libx264", "-crf", "28", "-preset", "fast",
                "-c:a", "aac", "-b:a", "128k",
                preview_path,
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"⚠️  ffmpeg preview failed:\n{result.stderr}")
            return None

        size = os.path.getsize(preview_path)
        if size > _PREVIEW_MAX_BYTES:
            print(f"⚠️  Preview clip is {size // (1024*1024)} MB — over limit, skipping video send.")
            return None

        print(f"✅ Preview clip ready: {preview_path} ({size // (1024*1024)} MB)")
        return preview_path

    except Exception as e:
        print(f"⚠️  Preview generation crashed: {e}")
        return None


async def _send_preview(
    message_obj,
    context: ContextTypes.DEFAULT_TYPE,
    song_data: dict,
    video_path: str,
):
    """
    Sends a compressed preview clip (or a text fallback if ffmpeg fails) with
    Upload / Discard inline buttons.

    Stores (song_data, video_path) in context.user_data so the decision
    callback can act on them regardless of which button is pressed.
    """
    title  = song_data.get("title", "")
    artist = song_data.get("artist", "")

    # Persist the pending upload state — the callback handler reads this
    context.user_data["pending_upload"] = {
        "song_data":  song_data,
        "video_path": video_path,
    }

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Upload to YouTube", callback_data="preview_upload"),
        InlineKeyboardButton("❌ Discard",           callback_data="preview_discard"),
    ]])

    await message_obj.reply_text(
        (
            f"🎬 *Render complete for* `{_md(title)}`\\!\\n"
            f"_Generating a {_PREVIEW_DURATION_S}\\-second preview clip\\.\\.\\._"
        ),
        parse_mode="MarkdownV2",
    )

    preview_path = await _make_preview_clip(video_path)

    if preview_path:
        caption = (
            f"🎵 *{_md(title)}* — {_md(artist)}\\n"
            f"First {_PREVIEW_DURATION_S}s preview\\. Does the sync look good?"
        )
        try:
            with open(preview_path, "rb") as vf:
                await message_obj.reply_video(
                    video=vf,
                    caption=caption,
                    parse_mode="MarkdownV2",
                    reply_markup=keyboard,
                    read_timeout=120,
                    write_timeout=120,
                )
            return
        except Exception as e:
            print(f"⚠️  Failed to send preview video: {e} — falling back to text prompt.")

    # Fallback: ffmpeg failed or file too large — show buttons without video
    await message_obj.reply_text(
        f"🎬 *Render complete for* `{_md(title)}`\\!\n"
        f"_\\(Preview unavailable \\— ffmpeg error or file too large\\.\\)_\n\n"
        f"Upload to YouTube or discard?",
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )


async def preview_decision_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """
    Handles the Upload / Discard buttons shown after a render completes.

    preview_upload : runs Phase 4 (YouTube upload) via master_controller.run_upload_only.
    preview_discard: marks the song as DISCARDED in the DB and auto-skips
                     to the next valid chart entry.
    """
    query = update.callback_query
    await query.answer()

    pending = context.user_data.pop("pending_upload", None)
    if not pending:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⚠️ No pending upload found\\. It may have already been handled\\.", parse_mode="MarkdownV2")
        return

    song_data  = pending["song_data"]
    video_path = pending["video_path"]
    title      = song_data.get("title", "")
    video_id   = song_data.get("video_id")

    # Remove buttons immediately so the user can't double-tap
    await query.edit_message_reply_markup(reply_markup=None)

    if query.data == "preview_upload":
        await query.message.reply_text(
            f"📤 *Uploading* `{_md(title)}` *to YouTube\\.\\.\\.*",
            parse_mode="MarkdownV2",
        )

        success = await asyncio.to_thread(
            master_controller.run_upload_only, song_data, video_path
        )

        if success:
            await query.message.reply_text(
                f"🚀 *Uploaded\\!* `{_md(title)}` is now live on YouTube\\.",
                parse_mode="MarkdownV2",
            )
        else:
            await query.message.reply_text(
                f"❌ *Upload failed* for `{_md(title)}`\\. Check the console logs\\.",
                parse_mode="MarkdownV2",
            )

    elif query.data == "preview_discard":
        db_manager.update_song_status(video_id, "DISCARDED")
        await query.message.reply_text(
            f"🗑️ *Discarded* `{_md(title)}`\\. The rendered video is kept in Output/ "
            f"but the song will be skipped in future chart runs\\.",
            parse_mode="MarkdownV2",
        )
        # Auto-advance to the next valid song
        context.user_data["skip_count"] = context.user_data.get("skip_count", 0) + 1
        msg = await query.message.reply_text("🔍 Fetching next valid song from charts\\.", parse_mode="MarkdownV2")
        await fetch_and_present_song(context, msg)



# ============================================================
# /cancel COMMAND
# ============================================================

async def cancel_pipeline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /cancel — stops the currently running pipeline at the next safe phase
    boundary (between phases, never mid-subprocess).

    How it works:
      1. Sets the threading.Event that master_controller checks between phases.
         The running thread sees this on its next check and returns "CANCELLED".
      2. Cancels the asyncio Task wrapping the thread so the heartbeat and
         trigger_pipeline coroutine also stop cleanly.

    The DB status is left at the last successfully COMPLETED phase, so the
    pipeline can be resumed later with /start — it will pick up right where
    it stopped rather than starting from scratch.

    If no pipeline is running, the command says so clearly.
    """
    cancel_event = context.bot_data.get("cancel_event")
    active_task  = context.bot_data.get("active_pipeline_task")

    if not active_task or active_task.done():
        await update.message.reply_text(
            "ℹ️ No pipeline is currently running\\.",
            parse_mode='MarkdownV2'
        )
        return

    await update.message.reply_text(
        "🛑 *Cancellation requested\\.*\n"
        "The pipeline will stop at the next safe checkpoint between phases\\.\n"
        "_\\(Current subprocess will finish first \\— Demucs\\/Whisper cannot be interrupted mid\\-run\\.\\)_",
        parse_mode='MarkdownV2'
    )

    # Signal the worker thread — master_controller checks this between phases
    if cancel_event:
        cancel_event.set()

    # Cancel the asyncio task — stops the heartbeat and trigger_pipeline coroutine
    active_task.cancel()


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
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(preview_decision_handler, pattern="^preview_"))
    app.add_handler(CommandHandler("cancel", cancel_pipeline_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_lyrics_upload))

    print("✅ Bot is online and listening!")
    app.run_polling()


if __name__ == "__main__":
    main()