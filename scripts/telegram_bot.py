"""
telegram_bot.py

Lightweight Telegram UI for EchoForge.

Changes / Features
──────────────────
• Bug 2   : asyncio.get_event_loop() → asyncio.get_running_loop()
• Bug 7   : Removed unused `from pathlib import Path` import
• Feature 5: Sync quality score displayed in lyrics preview header
• Feature 6: /queue command — shows up to 10 pending chart songs as inline
             buttons so user can pick by rank instead of skipping one-by-one
• Feature 7: /changebg command — pin a custom background image or reset to
             the default rank-based selection
• Feature 8: /description command — auto-generates a YouTube description via
             Claude for the current song, stored in metadata.json
• Feature 9: /retry command — re-run just the failed phase for a stalled song
             by video_id without manually touching the DB
• Feature 10: Error reasons from orchestrator checklist_cb are appended to
              the live checklist so failures are visible without opening console
"""

import asyncio
import glob
import json
import os
import re
import subprocess
import threading

import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import auto_discovery
import db_manager
import orchestrator
from config import ASSETS_DIR
from logger import get_logger

log = get_logger(__name__)

load_dotenv()
BOT_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN")
SECRET_PASSWORD = os.getenv("SECRET_PASSWORD")
ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY")
FONTS_DIR       = os.path.join(ASSETS_DIR, "Fonts")
BACKGROUNDS_DIR = os.path.join(ASSETS_DIR, "backgrounds")

if not BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN not set in .env!")

# ─── Conversation states ──────────────────────────────────────────────────────
(
    WAITING_FOR_ACTION,
    WAITING_FOR_EDIT_ARTIST,
    WAITING_FOR_LINK,
    WAITING_FOR_TITLE,
    WAITING_FOR_ARTIST,
    WAITING_FOR_FONT_ELEMENT,
    WAITING_FOR_FONT_CHOICE,
    WAITING_FOR_BG_CHOICE,
    WAITING_FOR_RETRY_ID,
) = range(9)


# ─── MarkdownV2 helpers ───────────────────────────────────────────────────────

def _md(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\-\\])', r'\\\1', text)


def _clean_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


# ─── Live Checklist ───────────────────────────────────────────────────────────

PHASE_EMOJI = {
    "pending": "⬜", "running": "⏳",
    "done":    "✅", "error":   "❌", "skipped": "⏭️",
}
ALL_PHASES = ["Audio", "Lyrics", "Sync", "Render", "Thumbnail", "Upload"]

PHASE_LABELS = {
    "Audio":     "Audio Download",
    "Lyrics":    "Lyrics Fetch",
    "Sync":      "Sync / Timestamps",
    "Render":    "Render Video",
    "Thumbnail": "Thumbnail",
    "Upload":    "Upload to YouTube",
}


def _build_checklist(title: str, artist: str, phase_states: dict, phase_reasons: dict) -> str:
    """
    Build the MarkdownV2 pipeline checklist.
    Feature 10: error reasons are appended inline so failures are visible
    without opening the console.
    """
    lines = [
        f"🎵 *Processing:* `{_md(title)}`",
        f"_{_md(artist)}_",
        "",
    ]
    for phase in ALL_PHASES:
        status = phase_states.get(phase, "pending")
        emoji  = PHASE_EMOJI.get(status, "⬜")
        label  = _md(PHASE_LABELS.get(phase, phase))
        # Feature 10: append reason on error
        reason = phase_reasons.get(phase, "")
        suffix = f" — _{_md(reason)}_" if reason and status == "error" else ""
        lines.append(f"{emoji} {label}{suffix}")
    return "\n".join(lines)


class LiveChecklist:
    """
    Maintains a single Telegram message edited in-place as pipeline phases change.
    Thread-safe: update() may be called from asyncio worker threads.
    """

    def __init__(self, bot, chat_id: int, title: str, artist: str,
                 loop: asyncio.AbstractEventLoop):
        self._bot     = bot
        self._chat    = chat_id
        self._title   = title
        self._artist  = artist
        self._loop    = loop
        self._msg_id: int | None = None
        self._states:  dict = {p: "pending" for p in ALL_PHASES}
        self._reasons: dict = {}                     # Feature 10: error reasons
        self._lock    = threading.Lock()

    async def _send_initial(self):
        text = _build_checklist(self._title, self._artist, self._states, self._reasons)
        msg  = await self._bot.send_message(
            chat_id=self._chat, text=text, parse_mode="MarkdownV2"
        )
        self._msg_id = msg.message_id

    async def _edit(self):
        if not self._msg_id:
            return
        text = _build_checklist(self._title, self._artist, self._states, self._reasons)
        try:
            await self._bot.edit_message_text(
                chat_id=self._chat, message_id=self._msg_id,
                text=text, parse_mode="MarkdownV2",
            )
        except Exception:
            pass

    def update(self, phase: str, status: str, reason: str = "") -> None:
        """Called by orchestrator.run_pipeline() via the checklist_cb."""
        with self._lock:
            self._states[phase] = status
            if reason:
                self._reasons[phase] = reason    # Feature 10
        future = asyncio.run_coroutine_threadsafe(self._edit(), self._loop)
        try:
            future.result(timeout=10)
        except Exception as exc:
            log.debug("LiveChecklist edit error (non-fatal): %s", exc)


# ─── Heartbeat ────────────────────────────────────────────────────────────────

_HEARTBEAT_MESSAGES = [
    "🎵 *Phase 1:* Downloading and extracting audio\\.\\.\\.",
    "🎙️ *Phase 2:* Demucs is isolating vocals — this takes 5–20 min on CPU\\.",
    "🎙️ *Still isolating\\.\\.\\.* Hang tight, Demucs is thorough\\.",
    "🧠 *Phase 3:* Whisper is force\\-aligning lyrics to vocals\\.",
    "🧠 *Still aligning\\.\\.\\.* Whisper on CPU is slow but accurate\\.",
    "⏳ *Still running\\.\\.\\.* Whisper alignment can take up to 40 min\\.",
    "🎬 *Rendering video* — nearly done\\!",
]
_HEARTBEAT_INTERVAL = 90


async def _heartbeat(message_obj) -> None:
    for text in _HEARTBEAT_MESSAGES:
        await asyncio.sleep(_HEARTBEAT_INTERVAL)
        try:
            await message_obj.reply_text(text, parse_mode="MarkdownV2")
        except Exception:
            pass
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL)
        try:
            await message_obj.reply_text(
                "⏳ *Still running\\.\\.\\.* Check the console if concerned\\.",
                parse_mode="MarkdownV2",
            )
        except Exception:
            pass


# ─── Pipeline runner ──────────────────────────────────────────────────────────

async def _run_pipeline_with_checklist(
    message_obj, song_data: dict,
    context: ContextTypes.DEFAULT_TYPE,
) -> object:
    # Bug 2 fix: use get_running_loop() inside an async context
    loop         = asyncio.get_running_loop()
    cancel_event = threading.Event()
    context.bot_data["cancel_event"] = cancel_event

    checklist = LiveChecklist(
        bot=context.bot,
        chat_id=message_obj.chat_id,
        title=song_data.get("title", ""),
        artist=song_data.get("artist", ""),
        loop=loop,
    )
    await checklist._send_initial()

    heartbeat_task = asyncio.create_task(_heartbeat(message_obj))
    context.bot_data["active_pipeline_task"] = asyncio.current_task()

    try:
        result = await asyncio.to_thread(
            orchestrator.run_pipeline,
            song_data,
            cancel_event,
            checklist.update,
        )
        return result
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        context.bot_data.pop("active_pipeline_task", None)
        context.bot_data.pop("cancel_event", None)


# ─── Pipeline trigger ─────────────────────────────────────────────────────────

async def trigger_pipeline(
    message_obj, context: ContextTypes.DEFAULT_TYPE, song_data: dict
) -> None:
    await message_obj.reply_text(
        "⚙️ *Master Controller Engaged\\!* Starting the pipeline\\.\\.\\.",
        parse_mode="MarkdownV2",
    )
    try:
        result = await _run_pipeline_with_checklist(message_obj, song_data, context)

        # Feature 5: LYRICS_PREVIEW_READY now carries a 4th element (quality score)
        if isinstance(result, tuple) and result[0] == "LYRICS_PREVIEW_READY":
            _, lyrics_path, lyrics_type, quality = result
            await _send_lyrics_preview(
                message_obj, context, song_data, lyrics_path, lyrics_type, quality
            )

        elif isinstance(result, tuple) and result[0] == "PREVIEW_READY":
            _, video_path = result
            await _send_preview(message_obj, context, song_data, video_path)

        elif result is True:
            await message_obj.reply_text(
                f"🎉 *Pipeline Complete\\!* `{_md(song_data['title'])}` finished\\.",
                parse_mode="MarkdownV2",
            )

        elif result == "UNAVAILABLE":
            await message_obj.reply_text(
                f"⛔ *Video Unavailable:* `{_md(song_data['title'])}` is blocked or removed\\.\n"
                "⏭️ Auto\\-skipping\\.\\.\\.",
                parse_mode="MarkdownV2",
            )
            context.user_data["skip_count"] = context.user_data.get("skip_count", 0) + 1
            msg = await message_obj.reply_text(
                "🔍 Fetching next valid song\\.", parse_mode="MarkdownV2"
            )
            await fetch_and_present_song(context, msg)

        elif result == "NEEDS_MANUAL_LYRICS":
            context.user_data["stalled_song"] = song_data
            await message_obj.reply_text(
                f"⚠️ *Lyrics Fetch Failed* for `{_md(song_data['title'])}`\\.\n\n"
                "📎 Upload a `.lrc` or `.txt` file to continue\\.",
                parse_mode="MarkdownV2",
            )

        elif result == "CANCELLED":
            await message_obj.reply_text(
                f"🛑 *Cancelled* `{_md(song_data['title'])}`\\. "
                "Run /start to resume\\.",
                parse_mode="MarkdownV2",
            )

        elif result == "LOW_DISK":
            await message_obj.reply_text(
                "💾 *Low Disk Space — Pipeline Paused*\n\n"
                "Free up space then run /start to resume\\.",
                parse_mode="MarkdownV2",
            )

        else:
            await message_obj.reply_text(
                f"❌ *Pipeline Failed* for `{_md(song_data['title'])}`\\. "
                "Check the console logs\\.",
                parse_mode="MarkdownV2",
            )

    except Exception as exc:
        await message_obj.reply_text(
            f"❌ *Fatal Error:* `{_md(str(exc))}`", parse_mode="MarkdownV2"
        )


async def _safe_pipeline_task(
    message_obj, context: ContextTypes.DEFAULT_TYPE, song_data: dict
) -> None:
    try:
        await trigger_pipeline(message_obj, context, song_data)
    except Exception as exc:
        log.exception("Background pipeline task crashed: %s", exc)
        try:
            await message_obj.reply_text(
                f"❌ *Background task crashed:* `{_md(str(exc))}`",
                parse_mode="MarkdownV2",
            )
        except Exception:
            pass
        raise


# ─── /status ──────────────────────────────────────────────────────────────────

_STATUS_EMOJI = {
    "PENDING": "🟡", "AUDIO_FETCHED": "🎵", "LYRICS_FETCHED": "📝",
    "LYRICS_READY": "✅", "ASSETS_READY": "🎨", "VIDEO_CREATED": "🎬",
    "UPLOADED": "🚀", "UNAVAILABLE": "⛔", "DISCARDED": "🗑️", "FAILED": "❌",
}


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_manager.init_db()
    counts = db_manager.get_status_counts()
    jobs   = db_manager.get_recent_jobs(limit=15)

    if not jobs:
        await update.message.reply_text(
            "📭 No jobs yet\\. Run /start to kick off the pipeline\\.",
            parse_mode="MarkdownV2",
        )
        return

    summary = "   ".join(f"{_STATUS_EMOJI.get(s,'?')} {s} x{c}" for s, c in counts.items())
    lines   = ["📊 *Pipeline Status*", "", _md(summary), "", "*Recent jobs:*"]
    for job in jobs:
        emoji = _STATUS_EMOJI.get(job["status"], "?")
        lines.append(f"{emoji} *{_md(job['title'])}*")
        lines.append(f"    {_md(job['artist'])} · `{job['status']}` · `{job['updated']}`")

    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


# ─── Feature 6: /queue command ────────────────────────────────────────────────

async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /queue — show up to 10 pending chart songs as inline buttons.
    User taps a song to select it directly instead of skipping one-by-one.
    """
    await update.message.reply_text(
        "🔍 Loading chart queue\\.\\.\\.", parse_mode="MarkdownV2"
    )
    queue = await asyncio.to_thread(auto_discovery.get_queue, 10)

    if not queue:
        await update.message.reply_text(
            "📭 No pending songs found in the charts right now\\.",
            parse_mode="MarkdownV2",
        )
        return

    lines    = ["🎵 *Pending Chart Songs*\n"]
    keyboard = []
    for song in queue:
        rank   = song.get("rank", "?")
        views  = f"{song.get('weekly_views', 0):,}"
        lines.append(
            f"*#{rank}* {_md(song['title'])} — {_md(song['artist'])}\n"
            f"    _{views} weekly views_"
        )
        keyboard.append([
            InlineKeyboardButton(
                f"#{rank} {song['title'][:30]}",
                callback_data=f"queue_pick:{song['video_id']}",
            )
        ])

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="queue_pick:__cancel__")])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def queue_pick_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles a song selection from the /queue inline keyboard."""
    query = update.callback_query
    await query.answer()

    video_id = query.data.split(":", 1)[1]
    if video_id == "__cancel__":
        await query.edit_message_reply_markup(reply_markup=None)
        return

    # Find the song in the cached chart data
    queue = await asyncio.to_thread(auto_discovery.get_queue, 50)
    song  = next((s for s in queue if s["video_id"] == video_id), None)

    if not song:
        await query.edit_message_text(
            "⚠️ Song no longer available in queue\\.", parse_mode="MarkdownV2"
        )
        return

    context.user_data["current_song"] = song
    workspace              = auto_discovery.create_workspace(song)
    song["workspace_dir"]  = workspace

    await query.edit_message_text(
        f"✅ *Selected from queue:*\n"
        f"🎶 `{_md(song['title'])}` by {_md(song['artist'])}\n"
        f"Workspace staged\\.",
        parse_mode="MarkdownV2",
    )
    asyncio.create_task(_safe_pipeline_task(query.message, context, song))


# ─── Feature 7: /changebg command ────────────────────────────────────────────

def _list_background_images() -> list[str]:
    """Return sorted list of image filenames in Assets/backgrounds/."""
    if not os.path.isdir(BACKGROUNDS_DIR):
        return []
    return sorted(
        f for f in os.listdir(BACKGROUNDS_DIR)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )


async def changebg_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /changebg — pin a specific background image or reset to rank-based selection.
    """
    images = _list_background_images()

    if not images:
        await update.message.reply_text(
            "❌ No images found in `Assets/backgrounds/`\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    # Build a 3-column grid of image buttons
    buttons: list[list] = []
    row: list = []
    for img in images[:30]:           # cap at 30 to stay inside Telegram limits
        row.append(InlineKeyboardButton(img, callback_data=f"bg_pick:{img}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton("🔄 Reset to auto (rank-based)", callback_data="bg_pick:__reset__"),
        InlineKeyboardButton("❌ Cancel",                     callback_data="bg_pick:__cancel__"),
    ])

    current = db_manager.get_setting("pinned_bg")
    current_label = (
        f"Currently pinned: `{_md(os.path.basename(current))}`"
        if current else "Currently using rank\\-based selection\\."
    )

    await update.message.reply_text(
        f"🖼️ *Background Manager*\n{current_label}\n\nChoose an image to pin:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return WAITING_FOR_BG_CHOICE


async def bg_choice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    choice = query.data.split(":", 1)[1]

    if choice == "__cancel__":
        await query.edit_message_reply_markup(reply_markup=None)
        return ConversationHandler.END

    db_manager.init_db()
    if choice == "__reset__":
        db_manager.delete_setting("pinned_bg")
        await query.edit_message_text(
            "🔄 *Background reset\\!* The renderer will now use rank\\-based selection\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    full_path = os.path.join(BACKGROUNDS_DIR, choice)
    db_manager.set_setting("pinned_bg", full_path)
    await query.edit_message_text(
        f"✅ *Background pinned\\!*\n"
        f"Image: `{_md(choice)}`\n"
        "_Applied on the next render\\._",
        parse_mode="MarkdownV2",
    )
    return ConversationHandler.END


# ─── Feature 8: /description command ─────────────────────────────────────────

async def description_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /description — generate a YouTube description for the current song via Claude.
    Saves the description into the song's metadata.json.
    """
    song = context.user_data.get("current_song")
    if not song:
        await update.message.reply_text(
            "⚠️ No song selected\\. Run /start first\\.", parse_mode="MarkdownV2"
        )
        return

    if not ANTHROPIC_KEY:
        await update.message.reply_text(
            "❌ `ANTHROPIC_API_KEY` not set in `.env`\\.", parse_mode="MarkdownV2"
        )
        return

    title  = song.get("title", "")
    artist = song.get("artist", "")
    rank   = song.get("rank", "?")
    views  = f"{song.get('weekly_views', 0):,}"

    await update.message.reply_text(
        f"🤖 Generating YouTube description for `{_md(title)}`\\.\\.\\.",
        parse_mode="MarkdownV2",
    )

    prompt = (
        f"Write a compelling 3-sentence YouTube description for a lyric video.\n"
        f"Song: \"{title}\" by {artist}\n"
        f"Chart position: #{rank} on the Global Weekly Charts with {views} weekly views.\n\n"
        "Requirements:\n"
        "- Sentence 1: Describe the mood/vibe of the song to hook the viewer.\n"
        "- Sentence 2: Mention the artist and any relevant style/genre.\n"
        "- Sentence 3: A call-to-action encouraging viewers to like, subscribe, "
        "  and check the original.\n"
        "Keep it under 300 characters total. No hashtags. No emoji."
    )

    try:
        resp = await asyncio.to_thread(
            requests.post,
            "https://api.anthropic.com/v1/messages",
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        description = resp.json()["content"][0]["text"].strip()
    except Exception as exc:
        await update.message.reply_text(
            f"❌ Description generation failed: `{_md(str(exc))}`",
            parse_mode="MarkdownV2",
        )
        return

    # Save into metadata.json if the workspace exists
    workspace = song.get("workspace_dir")
    if workspace:
        meta_path = os.path.join(workspace, "metadata.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)
                meta["youtube_description"] = description
                with open(meta_path, "w", encoding="utf-8") as fh:
                    json.dump(meta, fh, indent=4, ensure_ascii=False)
                song["youtube_description"] = description
                context.user_data["current_song"] = song
            except Exception as exc:
                log.warning("⚠️  Could not save description to metadata.json: %s", exc)

    await update.message.reply_text(
        f"✅ *Generated Description:*\n\n{_md(description)}\n\n"
        "_Saved to metadata\\.json \\— will be used on next upload\\._",
        parse_mode="MarkdownV2",
    )


# ─── Feature 9: /retry command ────────────────────────────────────────────────

_RETRY_STATUS_MAP = {
    "PENDING":        "PENDING",
    "AUDIO_FETCHED":  "PENDING",        # re-run from audio
    "LYRICS_FETCHED": "AUDIO_FETCHED",  # re-run lyrics fetch
    "LYRICS_READY":   "AUDIO_FETCHED",
    "ASSETS_READY":   "LYRICS_FETCHED", # re-run sync
    "VIDEO_CREATED":  "ASSETS_READY",   # re-run render
}


async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /retry — re-run the failed phase for a stalled song by video_id.
    Usage: /retry <video_id>
    If no video_id is given, asks the user to type one.
    """
    if context.args:
        return await _do_retry(update, context, context.args[0])

    await update.message.reply_text(
        "🔄 *Retry a stalled song*\n\nSend the YouTube video ID "
        "\\(e\\.g\\. `dQw4w9WgXcQ`\\):",
        parse_mode="MarkdownV2",
    )
    return WAITING_FOR_RETRY_ID


async def handle_retry_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _do_retry(update, context, update.message.text.strip())


async def _do_retry(
    update: Update, context: ContextTypes.DEFAULT_TYPE, video_id: str
) -> int:
    """Core retry logic: look up the job, roll back its status, and re-run."""
    db_manager.init_db()
    job = db_manager.get_job_details(video_id)

    if not job:
        await update.message.reply_text(
            f"❌ No job found for video ID `{_md(video_id)}`\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    current = job["status"]
    rollback_to = _RETRY_STATUS_MAP.get(current)

    if not rollback_to:
        await update.message.reply_text(
            f"ℹ️ Song `{_md(job['title'])}` has status `{current}` "
            "which cannot be retried from here\\.\n"
            "Use /start for UPLOADED or DISCARDED songs\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    # Find the workspace folder
    from config import ASSETS_DIR as _ASSETS
    safe = re.sub(r'[\\/*?:"<>|\[\]]', "", job["title"]).strip()
    folders = glob.glob(os.path.join(_ASSETS, f"*-{glob.escape(safe)}*"))
    workspace = max(folders, key=os.path.getmtime) if folders else None

    if not workspace:
        await update.message.reply_text(
            f"❌ Workspace folder not found for `{_md(job['title'])}`\\.\n"
            "Manual recovery required\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    # Roll back DB status
    db_manager.update_song_status(video_id, rollback_to)
    log.info("🔄 Retry: rolled back '%s' from %s → %s", job["title"], current, rollback_to)

    song_data = {
        "title":         job["title"],
        "artist":        job["artist"],
        "video_id":      video_id,
        "url":           f"https://www.youtube.com/watch?v={video_id}",
        "rank":          0,
        "weekly_views":  0,
        "workspace_dir": workspace,
    }

    await update.message.reply_text(
        f"🔄 *Retrying* `{_md(job['title'])}`\n"
        f"Status rolled back: `{current}` → `{rollback_to}`\n"
        "_Resuming pipeline now\\.\\.\\._",
        parse_mode="MarkdownV2",
    )
    asyncio.create_task(_safe_pipeline_task(update.message, context, song_data))
    return ConversationHandler.END


# ─── /changefont command ──────────────────────────────────────────────────────

def _list_fonts() -> list[str]:
    if not os.path.isdir(FONTS_DIR):
        return []
    return sorted(
        f for f in os.listdir(FONTS_DIR)
        if f.lower().endswith((".ttf", ".otf"))
    )


async def changefont_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[
        InlineKeyboardButton("🔤 Title",  callback_data="font_elem:title"),
        InlineKeyboardButton("🎤 Artist", callback_data="font_elem:artist"),
        InlineKeyboardButton("🎵 Lyrics", callback_data="font_elem:lyrics"),
    ]]
    await update.message.reply_text(
        "🎨 *Font Manager*\n\nWhich text element do you want to change?",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_FOR_FONT_ELEMENT


async def font_element_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query   = update.callback_query
    await query.answer()
    element = query.data.split(":")[1]
    context.user_data["font_element"] = element

    fonts = _list_fonts()
    if not fonts:
        await query.edit_message_text(
            "❌ No `.ttf` or `.otf` files found in `Assets/Fonts/`\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    font_buttons = []
    for i in range(0, min(len(fonts), 20), 2):
        row = [InlineKeyboardButton(fonts[i], callback_data=f"font_pick:{fonts[i]}")]
        if i + 1 < len(fonts):
            row.append(InlineKeyboardButton(fonts[i + 1], callback_data=f"font_pick:{fonts[i+1]}"))
        font_buttons.append(row)
    font_buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="font_pick:__cancel__")])

    label_map = {"title": "Title", "artist": "Artist", "lyrics": "Lyrics"}
    await query.edit_message_text(
        f"🔤 *Choose a font for* `{label_map.get(element, element)}`:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(font_buttons),
    )
    return WAITING_FOR_FONT_CHOICE


async def font_choice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query     = update.callback_query
    await query.answer()
    font_name = query.data.split(":", 1)[1]

    if font_name == "__cancel__":
        await query.edit_message_text("❌ Font change cancelled\\.", parse_mode="MarkdownV2")
        return ConversationHandler.END

    element  = context.user_data.get("font_element", "lyrics")
    font_abs = os.path.join(FONTS_DIR, font_name)
    db_manager.init_db()
    db_manager.set_setting(f"{element}_font", font_abs)

    label_map = {"title": "Title", "artist": "Artist", "lyrics": "Lyrics"}
    await query.edit_message_text(
        f"✅ *Font updated\\!*\n"
        f"Element: `{label_map.get(element, element)}`\n"
        f"Font: `{_md(font_name)}`\n"
        "_Applied on the next render\\._",
        parse_mode="MarkdownV2",
    )
    return ConversationHandler.END


# ─── Song discovery flow ──────────────────────────────────────────────────────

async def fetch_and_present_song(context: ContextTypes.DEFAULT_TYPE, message_obj) -> int:
    skip = context.user_data.get("skip_count", 0)
    song = await asyncio.to_thread(auto_discovery.get_top_song, skip)

    if song:
        context.user_data["current_song"] = song
        text = (
            f"🏆 *Valid Song \\#{skip + 1} Found\\!*\n\n"
            f"🗣️ *Artist:* {_md(song['artist'])}\n"
            f"🎶 *Title:* {_md(song['title'])}\n"
            f"📊 *Rank:* \\#{song.get('rank','?')} · "
            f"{song.get('weekly_views',0):,} weekly views\n"
            f"🔗 *URL:* `{song['url']}`\n\n"
            "What would you like to do?"
        )
        keyboard = [
            [
                InlineKeyboardButton("✅ Continue",           callback_data="continue"),
                InlineKeyboardButton("✏️ Edit Artist",        callback_data="edit_artist"),
            ],
            [InlineKeyboardButton("⏭️ Select Next Song",     callback_data="next_song")],
            [InlineKeyboardButton("✍️ Manual Entry Instead", callback_data="manual")],
        ]
        await message_obj.edit_text(
            text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return WAITING_FOR_ACTION

    await message_obj.edit_text(
        "❌ No more valid songs found in the charts\\.", parse_mode="MarkdownV2"
    )
    return ConversationHandler.END


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.args and context.args[0] == SECRET_PASSWORD:
        msg = await update.message.reply_text(
            "✅ Password verified\\. Fetching the top trending song\\.\\.\\.",
            parse_mode="MarkdownV2",
        )
        if not context.user_data.get("stalled_song"):
            context.user_data["skip_count"] = 0
        return await fetch_and_present_song(context, msg)
    await update.message.reply_text(
        "❌ Unauthorized\\. Invalid or missing password\\.", parse_mode="MarkdownV2"
    )
    return ConversationHandler.END


async def action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    song  = context.user_data.get("current_song")

    if query.data == "continue":
        workspace             = auto_discovery.create_workspace(song)
        song["workspace_dir"] = workspace
        await query.edit_message_text(
            f"✅ *Confirmed\\!* Workspace staged\\.\n`{_md(workspace)}`",
            parse_mode="MarkdownV2",
        )
        asyncio.create_task(_safe_pipeline_task(query.message, context, song))
        return ConversationHandler.END

    elif query.data == "edit_artist":
        await query.edit_message_text("✏️ Type the corrected artist name:")
        return WAITING_FOR_EDIT_ARTIST

    elif query.data == "next_song":
        context.user_data["skip_count"] = context.user_data.get("skip_count", 0) + 1
        await query.edit_message_text(
            "⏭️ Fetching the next valid song\\.\\.\\.", parse_mode="MarkdownV2"
        )
        return await fetch_and_present_song(context, query.message)

    elif query.data == "manual":
        await query.edit_message_text(
            "🔗 *Step 1/3:* Send the YouTube link:", parse_mode="MarkdownV2"
        )
        return WAITING_FOR_LINK


async def handle_edit_artist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_artist            = update.message.text.strip()
    song                  = context.user_data.get("current_song")
    song["artist"]        = new_artist
    workspace             = auto_discovery.create_workspace(song)
    song["workspace_dir"] = workspace
    await update.message.reply_text(
        f"✅ *Artist Updated\\!* `{_md(new_artist)}`\nWorkspace: `{_md(workspace)}`",
        parse_mode="MarkdownV2",
    )
    asyncio.create_task(_safe_pipeline_task(update.message, context, song))
    return ConversationHandler.END


async def handle_manual_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["manual_url"] = update.message.text.strip()
    await update.message.reply_text(
        "🎵 *Step 2/3:* Send the Song Title:", parse_mode="MarkdownV2"
    )
    return WAITING_FOR_TITLE


async def handle_manual_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["manual_title"] = update.message.text.strip()
    await update.message.reply_text(
        "🗣️ *Step 3/3:* Send the Artist Name:", parse_mode="MarkdownV2"
    )
    return WAITING_FOR_ARTIST


async def handle_manual_artist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    artist = update.message.text.strip()
    title  = context.user_data["manual_title"]
    url    = context.user_data["manual_url"]

    video_id = "MANUAL_ID"
    if "v=" in url:
        video_id = url.split("v=")[-1].split("&")[0]
    elif "youtu.be/" in url:
        video_id = url.split("youtu.be/")[-1].split("?")[0]

    song = {
        "title": title, "artist": artist, "url": url, "video_id": video_id,
        "rank": 0, "weekly_views": 0,
        "search_query": f"{artist} {title} official audio",
    }
    workspace             = auto_discovery.create_workspace(song)
    song["workspace_dir"] = workspace

    await update.message.reply_text(
        f"✅ *Manual Entry Saved\\!*\n🎵 `{_md(title)}`",
        parse_mode="MarkdownV2",
    )
    asyncio.create_task(_safe_pipeline_task(update.message, context, song))
    return ConversationHandler.END


# ─── File upload handler ──────────────────────────────────────────────────────

async def handle_lyrics_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    stalled = context.user_data.get("stalled_song")
    if not stalled:
        return

    doc       = update.message.document
    file_name = doc.file_name.lower()

    if not (file_name.endswith(".lrc") or file_name.endswith(".txt")):
        await update.message.reply_text(
            "❌ Invalid format\\. Upload a `.lrc` or `.txt` file\\.",
            parse_mode="MarkdownV2",
        )
        return

    await update.message.reply_text("📥 Downloading lyrics file\\.\\.\\.", parse_mode="MarkdownV2")
    try:
        file      = await context.bot.get_file(doc.file_id)
        workspace = stalled["workspace_dir"]
        video_id  = stalled["video_id"]
        ext       = file_name.split(".")[-1]
        save_path = os.path.join(workspace, f"lyrics.{ext}")
        await file.download_to_drive(save_path)

        db_manager.update_song_status(
            video_id, "LYRICS_READY" if ext == "lrc" else "LYRICS_FETCHED"
        )
        await update.message.reply_text(
            f"✅ Lyrics saved\\! Resuming pipeline for `{_md(stalled['title'])}`\\.\\.\\.",
            parse_mode="MarkdownV2",
        )
        context.user_data["stalled_song"] = None
        asyncio.create_task(_safe_pipeline_task(update.message, context, stalled))
    except Exception as exc:
        await update.message.reply_text(
            f"❌ Failed to process upload: `{_md(str(exc))}`", parse_mode="MarkdownV2"
        )


# ─── Lyrics review (P2 pause) ─────────────────────────────────────────────────

_LYRICS_SNIPPET_LINES = 10


def _read_lyrics_snippet(path: str, ltype: str) -> tuple[list[str], int]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except Exception as exc:
        return [f"(could not read: {exc})"], 0
    if ltype == "SYNCED":
        raw = re.sub(r"\[\d{2}:\d{2}[.:]\d{2,3}\]", "", raw)
    lines = [l.strip() for l in raw.split("\n") if l.strip()]
    return lines, len(lines)


async def _send_lyrics_preview(
    message_obj, context: ContextTypes.DEFAULT_TYPE,
    song_data: dict, lyrics_path: str, lyrics_type: str,
    sync_quality: float | None = None,   # Feature 5
) -> None:
    context.user_data["pending_lyrics"] = {
        "song_data": song_data, "lyrics_path": lyrics_path, "lyrics_type": lyrics_type,
    }
    lines, total = _read_lyrics_snippet(lyrics_path, lyrics_type)
    snippet      = "\n".join(_md(l) for l in lines[:_LYRICS_SNIPPET_LINES])
    remaining    = total - _LYRICS_SNIPPET_LINES

    type_label = (
        "pre\\-synced LRC \\(fast\\)" if lyrics_type == "SYNCED"
        else "plain text \\(Whisper sync needed\\)"
    )

    # Feature 5: append sync quality score if available
    quality_line = ""
    if sync_quality is not None:
        quality_pct  = int(sync_quality * 100)
        quality_icon = "🟢" if quality_pct >= 80 else ("🟡" if quality_pct >= 55 else "🔴")
        quality_line = f"\n{quality_icon} *Sync quality:* {quality_pct}%"

    header = (
        f"📝 *Lyrics ready for* `{_md(song_data['title'])}`\n"
        f"_{_md(song_data['artist'])} · {type_label} · {total} lines_"
        f"{quality_line}\n\n"
        f"*First {min(_LYRICS_SNIPPET_LINES, total)} lines:*\n{snippet}"
    )
    if remaining > 0:
        header += f"\n_\\.\\.\\. and {remaining} more \\(see attached\\)_"
    footer = "\n\n✅ *Approve* · ✏️ *Edit* · ❌ *Reject*"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data="lyrics_approve"),
        InlineKeyboardButton("✏️ Edit",    callback_data="lyrics_edit"),
        InlineKeyboardButton("❌ Reject",  callback_data="lyrics_reject"),
    ]])

    ext      = os.path.splitext(lyrics_path)[1] or ".txt"
    filename = (_clean_filename(song_data["title"]) or "lyrics") + ext
    try:
        with open(lyrics_path, "rb") as fh:
            await message_obj.reply_document(
                document=fh, filename=filename,
                caption=header + footer, parse_mode="MarkdownV2",
                reply_markup=keyboard,
            )
        return
    except Exception:
        pass
    await message_obj.reply_text(
        header + footer, parse_mode="MarkdownV2", reply_markup=keyboard
    )


async def lyrics_decision_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    pending = context.user_data.pop("pending_lyrics", None)

    if not pending:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "⚠️ No pending lyrics review found\\.", parse_mode="MarkdownV2"
        )
        return

    song_data   = pending["song_data"]
    lyrics_type = pending["lyrics_type"]
    title       = song_data.get("title", "")
    video_id    = song_data.get("video_id")
    await query.edit_message_reply_markup(reply_markup=None)

    if query.data == "lyrics_approve":
        next_step = (
            "Timestamp processing then render\\."
            if lyrics_type == "SYNCED"
            else "Vocal isolation \\+ Whisper alignment — this will take a while\\."
        )
        await query.message.reply_text(
            f"✅ *Lyrics approved\\!* Resuming `{_md(title)}`\\.\n_Next: {next_step}_",
            parse_mode="MarkdownV2",
        )
        asyncio.create_task(_safe_pipeline_task(query.message, context, song_data))

    elif query.data == "lyrics_edit":
        context.user_data["stalled_song"] = song_data
        await query.message.reply_text(
            f"✏️ *Edit Lyrics for* `{_md(title)}`\n\nUpload a `.lrc` or `.txt` replacement\\.",
            parse_mode="MarkdownV2",
        )

    elif query.data == "lyrics_reject":
        db_manager.update_song_status(video_id, "DISCARDED")
        await query.message.reply_text(
            f"🗑️ *Rejected* `{_md(title)}` — marked DISCARDED\\.", parse_mode="MarkdownV2"
        )
        context.user_data["skip_count"] = context.user_data.get("skip_count", 0) + 1
        msg = await query.message.reply_text(
            "🔍 Fetching next song\\.", parse_mode="MarkdownV2"
        )
        await fetch_and_present_song(context, msg)


# ─── Video preview ────────────────────────────────────────────────────────────

_PREVIEW_MAX_BYTES  = 45 * 1024 * 1024
_PREVIEW_DURATION_S = 35


async def _make_preview_clip(video_path: str) -> str | None:
    preview = video_path.replace(".mp4", "_preview.mp4")
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "ffmpeg", "-y", "-i", video_path,
                "-t", str(_PREVIEW_DURATION_S), "-vf", "scale=-2:720",
                "-c:v", "libx264", "-crf", "28", "-preset", "fast",
                "-c:a", "aac", "-b:a", "128k", preview,
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or os.path.getsize(preview) > _PREVIEW_MAX_BYTES:
            return None
        return preview
    except Exception:
        return None


async def _send_preview(
    message_obj, context: ContextTypes.DEFAULT_TYPE, song_data: dict, video_path: str,
) -> None:
    context.user_data["pending_upload"] = {"song_data": song_data, "video_path": video_path}
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Upload to YouTube", callback_data="preview_upload"),
        InlineKeyboardButton("❌ Discard",           callback_data="preview_discard"),
    ]])
    await message_obj.reply_text(
        f"🎬 *Render complete for* `{_md(song_data['title'])}`\\!\n"
        f"_Generating {_PREVIEW_DURATION_S}\\-second preview\\.\\.\\._",
        parse_mode="MarkdownV2",
    )
    clip    = await _make_preview_clip(video_path)
    caption = (
        f"🎵 *{_md(song_data['title'])}* — {_md(song_data['artist'])}\n"
        f"First {_PREVIEW_DURATION_S}s preview\\. Does the sync look good?"
    )
    if clip:
        try:
            with open(clip, "rb") as fh:
                await message_obj.reply_video(
                    video=fh, caption=caption, parse_mode="MarkdownV2",
                    reply_markup=keyboard, read_timeout=120, write_timeout=120,
                )
            return
        except Exception:
            pass
    await message_obj.reply_text(
        f"🎬 *Render complete for* `{_md(song_data['title'])}`\\!\n"
        "_\\(Preview unavailable\\)_\n\nUpload or discard?",
        parse_mode="MarkdownV2", reply_markup=keyboard,
    )


async def preview_decision_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    pending = context.user_data.pop("pending_upload", None)

    if not pending:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "⚠️ No pending upload found\\.", parse_mode="MarkdownV2"
        )
        return

    song_data  = pending["song_data"]
    video_path = pending["video_path"]
    title      = song_data.get("title", "")
    video_id   = song_data.get("video_id")
    await query.edit_message_reply_markup(reply_markup=None)

    if query.data == "preview_upload":
        await query.message.reply_text(
            f"📤 *Uploading* `{_md(title)}` *to YouTube\\.\\.\\.*",
            parse_mode="MarkdownV2",
        )
        ok = await asyncio.to_thread(orchestrator.run_upload_only, song_data, video_path)
        if ok:
            await query.message.reply_text(
                f"🚀 *Uploaded\\!* `{_md(title)}` is live on YouTube\\.",
                parse_mode="MarkdownV2",
            )
        else:
            await query.message.reply_text(
                f"❌ *Upload failed* for `{_md(title)}`\\. Check the console\\.",
                parse_mode="MarkdownV2",
            )

    elif query.data == "preview_discard":
        db_manager.update_song_status(video_id, "DISCARDED")
        await query.message.reply_text(
            f"🗑️ *Discarded* `{_md(title)}`\\.", parse_mode="MarkdownV2"
        )
        context.user_data["skip_count"] = context.user_data.get("skip_count", 0) + 1
        msg = await query.message.reply_text(
            "🔍 Fetching next song\\.", parse_mode="MarkdownV2"
        )
        await fetch_and_present_song(context, msg)


# ─── /cancel ──────────────────────────────────────────────────────────────────

async def cancel_pipeline_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cancel_event = context.bot_data.get("cancel_event")
    active_task  = context.bot_data.get("active_pipeline_task")

    if not active_task or active_task.done():
        await update.message.reply_text(
            "ℹ️ No pipeline is currently running\\.", parse_mode="MarkdownV2"
        )
        return

    await update.message.reply_text(
        "🛑 *Cancellation requested\\.*\n"
        "The pipeline will stop at the next safe checkpoint\\.",
        parse_mode="MarkdownV2",
    )
    if cancel_event:
        cancel_event.set()
    active_task.cancel()


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Operation cancelled\\.", parse_mode="MarkdownV2")
    return ConversationHandler.END


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    log.info("🤖 EchoForge Telegram Bot booting...")
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Main conversation (song selection) ────────────────────────────────────
    main_conv = ConversationHandler(
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

    # ── Font conversation ─────────────────────────────────────────────────────
    font_conv = ConversationHandler(
        entry_points=[CommandHandler("changefont", changefont_command)],
        states={
            WAITING_FOR_FONT_ELEMENT: [CallbackQueryHandler(font_element_handler, pattern="^font_elem:")],
            WAITING_FOR_FONT_CHOICE:  [CallbackQueryHandler(font_choice_handler,  pattern="^font_pick:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── Background conversation ───────────────────────────────────────────────
    bg_conv = ConversationHandler(
        entry_points=[CommandHandler("changebg", changebg_command)],
        states={
            WAITING_FOR_BG_CHOICE: [CallbackQueryHandler(bg_choice_handler, pattern="^bg_pick:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── Retry conversation ────────────────────────────────────────────────────
    retry_conv = ConversationHandler(
        entry_points=[CommandHandler("retry", retry_command)],
        states={
            WAITING_FOR_RETRY_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_retry_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(main_conv)
    app.add_handler(font_conv)
    app.add_handler(bg_conv)
    app.add_handler(retry_conv)
    app.add_handler(CommandHandler("status",      status_command))
    app.add_handler(CommandHandler("queue",       queue_command))
    app.add_handler(CommandHandler("description", description_command))
    app.add_handler(CommandHandler("cancel",      cancel_pipeline_command))
    app.add_handler(CallbackQueryHandler(lyrics_decision_handler,  pattern="^lyrics_"))
    app.add_handler(CallbackQueryHandler(preview_decision_handler, pattern="^preview_"))
    app.add_handler(CallbackQueryHandler(queue_pick_handler,       pattern="^queue_pick:"))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_lyrics_upload))

    log.info("✅ Bot online — commands: /start /status /queue /changefont /changebg /description /retry /cancel")
    app.run_polling()


if __name__ == "__main__":
    main()