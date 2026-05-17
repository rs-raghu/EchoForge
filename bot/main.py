"""
bot/main.py

EchoForge V3 — Telegram Dashboard Bot.
"""

import asyncio
import os
import sys
from datetime import datetime

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
from telegram.error import BadRequest  # <--- NEW IMPORT ADDED HERE

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db_manager
from utils.logger import get_logger

try:
    from discovery import chart_scraper
except ImportError:
    chart_scraper = None

log = get_logger(__name__)
load_dotenv()

BOT_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "")
SECRET_PASSWORD = os.getenv("SECRET_PASSWORD", "")

(
    WAITING_FOR_LYRICS_TEXT,
    WAITING_FOR_LYRICS_FILE,
    WAITING_FOR_METADATA,
    WAITING_FOR_SOURCE_URL,
) = range(4)

def _esc(text: str) -> str:
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text

# ─── Safe Edit Helper ─────────────────────────────────────────────────────────
async def _safe_edit(query, text: str, markup=None):
    """Safely edit a callback message, falling back for media messages."""
    try:
        return await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return None
        try:
            return await query.edit_message_caption(
                caption=text,
                parse_mode="Markdown",
                reply_markup=markup,
            )
        except BadRequest:
            return await query.message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=markup,
            )
# ──────────────────────────────────────────────────────────────────────────────

def build_main_dashboard() -> tuple[str, InlineKeyboardMarkup]:
    jobs      = db_manager.get_active_jobs()
    q_count   = db_manager.get_queue_count()
    age_str, _= db_manager.get_last_scrape_info()
    scrape_lbl = f"🔍 Scraper  (last: {age_str})" if age_str else "🔍 Run Chart Scraper"

    text     = "🎛️ *EchoForge Master Control*\n\n"
    keyboard = []

    text += f"*Active Jobs ({len(jobs)}):*\n"
    if not jobs:
        text += "_Nothing in flight — queue a song to start!_\n"
    else:
        for job in jobs:
            icon = _state_icon(job["macro"])
            text += f"{icon} `{job['macro']}` — {_esc(job['title'])}\n"
            keyboard.append([
                InlineKeyboardButton(
                    f"⚙️ {job['title'][:30]}",
                    callback_data=f"open_panel:{job['video_id']}",
                )
            ])

    text += f"\n*Queue:* {q_count} song(s) waiting\n\n*Actions:*"
    keyboard += [
        [InlineKeyboardButton("▶️ Fetch Next from Queue",  callback_data="fetch_next")],
        [InlineKeyboardButton(scrape_lbl,                  callback_data="run_scraper")],
        [InlineKeyboardButton("🔄 Refresh Dashboard",       callback_data="refresh_main")],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def build_song_panel(song: dict) -> tuple[str, InlineKeyboardMarkup]:
    macro  = song["current_macro_state"]
    micro  = song["current_micro_state"]
    target = song["target_macro_state"]
    source_url = song.get("url") or f"https://www.youtube.com/watch?v={song['video_id']}"

    icon   = _state_icon(macro)
    text   = (
        f"🎵 *{_esc(song['title'])}*\n"
        f"👤 {_esc(song['artist'])}\n"
        f"────────────────\n"
        f"🎯 *Target:* `{target}`\n"
        f"{icon} *Status:* `{macro}`\n"
        f"🔍 *Activity:* `{micro}`\n"
        f"🔗 *Source:* {_esc(source_url)}\n\n"
    )

    keyboard = []

    if macro in ("STAGED", "PAUSED"):
        text += "_Ready — choose a target:_"
        keyboard.append([
            InlineKeyboardButton("▶️ Run Full (→ Publish)",   callback_data=f"set_target:{song['video_id']}:PUBLISHED"),
            InlineKeyboardButton("🛠️ Assets Only",             callback_data=f"set_target:{song['video_id']}:ASSETS_READY"),
        ])

    elif macro == "LYRICS_REVIEW_PENDING":
        text += "⚠️ *Action Required: Review the lyrics sent above.*"
        keyboard.append([
            InlineKeyboardButton("✅ Approve Lyrics",  callback_data=f"approve_lyrics:{song['video_id']}"),
            InlineKeyboardButton("✏️ Edit Natively",   callback_data=f"edit_lyrics:{song['video_id']}"),
        ])
        keyboard.append([
            InlineKeyboardButton("❌ Reject / Discard", callback_data=f"discard:{song['video_id']}"),
        ])

    elif macro == "PREVIEW_PENDING":
        text += "🎬 *Video rendered! Review the clip then decide.*"
        keyboard.append([
            InlineKeyboardButton("🚀 Upload to YouTube",  callback_data=f"approve_video:{song['video_id']}"),
            InlineKeyboardButton("🗑️ Discard",            callback_data=f"discard:{song['video_id']}"),
        ])

    elif macro == "FAILED":
        text += "❌ *Pipeline crashed. Check the logs.*"
        keyboard.append([
            InlineKeyboardButton("🔄 Retry",  callback_data=f"retry:{song['video_id']}:{target}"),
        ])

    elif macro == "ASSETS_READY" and target == "ASSETS_READY":
        text += "✅ *Assets are ready.*"
        keyboard.append([
            InlineKeyboardButton("▶️ Continue Video", callback_data=f"continue_video:{song['video_id']}"),
        ])

    elif macro == "ASSETS_READY":
        text += "🎬 *Assets are ready. Rendering will start shortly.*"

    elif macro == "PUBLISHED":
        url = _read_published_url(song.get("workspace_dir"))
        text += f"🚀 *Published!*\n{_esc(url) if url else '_URL not found_'}"

    _running_macros = {
        "STAGED", "AUDIO_FETCHED", "LYRICS_APPROVED", "ASSETS_READY", "VIDEO_APPROVED"
    }
    if macro in _running_macros:
        keyboard.append([
            InlineKeyboardButton("🛑 ABORT (Kill Process)", callback_data=f"abort:{song['video_id']}"),
            InlineKeyboardButton("⏸️ Pause at Checkpoint", callback_data=f"pause:{song['video_id']}"),
        ])

    if macro not in ("PUBLISHED", "DISCARDED"):
        keyboard.append([
            InlineKeyboardButton("✏️ Edit Title / Artist", callback_data=f"edit_metadata:{song['video_id']}"),
            InlineKeyboardButton("🔗 Change Source", callback_data=f"edit_source:{song['video_id']}"),
        ])
        keyboard.append([
            InlineKeyboardButton("🗑️ Discard Song", callback_data=f"discard:{song['video_id']}"),
        ])

    keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_main")])
    return text, InlineKeyboardMarkup(keyboard)


def _state_icon(macro: str) -> str:
    return {
        "STAGED":                "📋",
        "AUDIO_FETCHED":         "🎵",
        "LYRICS_REVIEW_PENDING": "📝",
        "LYRICS_APPROVED":       "✅",
        "ASSETS_READY":          "🎨",
        "PREVIEW_PENDING":       "🎬",
        "VIDEO_APPROVED":        "📤",
        "PUBLISHED":             "🚀",
        "PAUSED":                "⏸️",
        "FAILED":                "❌",
        "DISCARDED":             "🗑️",
    }.get(macro, "❓")


def _read_published_url(workspace_dir: str | None) -> str | None:
    if not workspace_dir:
        return None
    url_file = os.path.join(workspace_dir, "published_url.txt")
    if os.path.exists(url_file):
        with open(url_file, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    return None


def _retry_macro_from_workspace(song: dict) -> str:
    workspace = song.get("workspace_dir")
    if not workspace:
        return "STAGED"

    final_video = os.path.join(workspace, "final_video.mp4")
    timestamps = os.path.join(workspace, "timestamps.json")
    lyrics_lrc = os.path.join(workspace, "lyrics.lrc")
    lyrics_txt = os.path.join(workspace, "lyrics.txt")
    audio = os.path.join(workspace, "audio.mp3")

    if os.path.exists(final_video):
        return "VIDEO_APPROVED"
    if os.path.exists(timestamps):
        return "ASSETS_READY"
    if os.path.exists(lyrics_lrc) or os.path.exists(lyrics_txt):
        return "LYRICS_APPROVED"
    if os.path.exists(audio):
        return "AUDIO_FETCHED"
    return "STAGED"

_RESTING_STATES = {
    "PAUSED", "LYRICS_REVIEW_PENDING", "PREVIEW_PENDING",
    "PUBLISHED", "FAILED", "DISCARDED",
}

async def live_panel_updater(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    video_id: str,
) -> None:
    last_micro    = ""
    lyrics_sent   = False
    preview_sent  = False

    while True:
        await asyncio.sleep(3)
        song = db_manager.get_song(video_id)
        if not song:
            break

        macro = song["current_macro_state"]
        micro = song["current_micro_state"]

        if micro != last_micro or macro in _RESTING_STATES:
            last_micro = micro
            panel_text, markup = build_song_panel(song)
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=panel_text,
                    parse_mode="Markdown",
                    reply_markup=markup,
                )
            except Exception:
                pass

        if macro == "LYRICS_REVIEW_PENDING" and not lyrics_sent:
            lyrics_sent = True
            await _send_lyrics_for_review(context, chat_id, song)

        if macro == "PREVIEW_PENDING" and not preview_sent:
            preview_sent = True
            await _send_video_preview(context, chat_id, song)

        if macro in _RESTING_STATES:
            break

async def _send_lyrics_for_review(context: ContextTypes.DEFAULT_TYPE, chat_id: int, song: dict) -> None:
    workspace = song.get("workspace_dir")
    if not workspace:
        return
    lrc_path = os.path.join(workspace, "lyrics.lrc")
    txt_path = os.path.join(workspace, "lyrics.txt")
    lyrics_path = lrc_path if os.path.exists(lrc_path) else (txt_path if os.path.exists(txt_path) else None)

    if not lyrics_path:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Lyrics file not found in workspace.")
        return

    ltype    = "Synced LRC" if lyrics_path.endswith(".lrc") else "Plain Text"
    filename = f"{song['title']} lyrics{os.path.splitext(lyrics_path)[1]}"

    try:
        with open(lyrics_path, "rb") as fh:
            await context.bot.send_document(
                chat_id=chat_id,
                document=fh,
                filename=filename,
                caption=f"📝 *Lyrics ready for review*\n_{_esc(song['title'])}_ — {ltype}\n\nUse the panel buttons to Approve, Edit, or Reject.",
                parse_mode="Markdown",
            )
    except Exception as exc:
        log.warning("⚠️  Could not send lyrics file: %s", exc)
        try:
            with open(lyrics_path, "r", encoding="utf-8") as fh:
                snippet = fh.read(1500)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"📝 *Lyrics snippet (first 1500 chars):*\n\n```\n{snippet}\n```",
                parse_mode="Markdown",
            )
        except Exception:
            pass

_PREVIEW_DURATION_S = 60
_PREVIEW_MAX_BYTES  = 48_000_000

async def _make_preview_clip(video_path: str) -> str | None:
    import subprocess
    preview_path = video_path.replace(".mp4", "_preview.mp4")

    def _run() -> bool:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-t", str(_PREVIEW_DURATION_S), "-vf", "scale=-2:720", "-c:v", "libx264", "-crf", "28", "-preset", "fast", "-c:a", "aac", "-b:a", "128k", preview_path],
            capture_output=True, text=True,
        )
        return result.returncode == 0

    try:
        ok = await asyncio.to_thread(_run)
    except Exception as exc:
        return None

    if not ok: return None

    try:
        size = os.path.getsize(preview_path)
    except OSError:
        return None

    if size > _PREVIEW_MAX_BYTES:
        try: os.remove(preview_path)
        except OSError: pass
        return None
    return preview_path


async def _send_video_preview(context: ContextTypes.DEFAULT_TYPE, chat_id: int, song: dict) -> None:
    workspace = song.get("workspace_dir")
    title     = song.get("title", "Unknown")
    artist    = song.get("artist", "Unknown")
    video_id  = song["video_id"]

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Upload to YouTube", callback_data=f"approve_video:{video_id}"),
        InlineKeyboardButton("🗑️ Discard",   callback_data=f"discard:{video_id}"),
    ]])

    video_path = os.path.join(workspace, "final_video.mp4") if workspace else None

    if not video_path or not os.path.exists(video_path):
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🎬 *Render complete:* _{_esc(title)}_\n\n⚠️ `final_video.mp4` not found — use buttons to decide.",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    notice = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🎬 *Render complete!* Cutting {_PREVIEW_DURATION_S}s preview clip…",
        parse_mode="Markdown",
    )

    clip_path = await _make_preview_clip(video_path)

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=notice.message_id)
    except Exception:
        pass

    caption = f"🎵 *{_esc(title)}* — {_esc(artist)}\nFirst {_PREVIEW_DURATION_S}s — does the sync look good?"

    if clip_path:
        try:
            with open(clip_path, "rb") as fh:
                await context.bot.send_video(
                    chat_id=chat_id, video=fh, caption=caption, parse_mode="Markdown",
                    reply_markup=keyboard, supports_streaming=True, read_timeout=120, write_timeout=120,
                )
            return
        except Exception:
            pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🎬 *Render complete:* _{_esc(title)}_\n\n_(Preview unavailable — ffmpeg error or file too large.)_\n\nUpload to YouTube or discard?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    args     = context.args or []
    password = args[0] if args else ""

    if not SECRET_PASSWORD:
        log.warning("⚠️  SECRET_PASSWORD not set in .env — bot is open to anyone!")
    elif password != SECRET_PASSWORD:
        await update.message.reply_text("❌ Unauthorized. Invalid or missing password.")
        return ConversationHandler.END

    db_manager.init_db()
    text, markup = build_main_dashboard()
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
    return ConversationHandler.END

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    parts    = query.data.split(":")
    cmd      = parts[0]
    video_id = parts[1] if len(parts) > 1 else None
    extra    = parts[2] if len(parts) > 2 else None
    chat_id  = query.message.chat_id

    if cmd in ("back_to_main", "refresh_main"):
        text, markup = build_main_dashboard()
        await _safe_edit(query, text, markup)
        return ConversationHandler.END

    if cmd == "run_scraper":
        age_str, is_stale = db_manager.get_last_scrape_info()
        if not is_stale:
            await query.answer(f"⏳ Scraped {age_str} — waiting {db_manager.CHART_CACHE_HOURS}h before re-scraping.", show_alert=True)
            return ConversationHandler.END

        await _safe_edit(query, "🔍 *Scraping global charts…* This may take 30–60 seconds.")
        try:
            if not chart_scraper:
                raise ImportError("discovery/chart_scraper.py not found.")
            songs = await asyncio.to_thread(chart_scraper.scrape_top_charts, limit=20)
            if songs:
                added = db_manager.add_discovered_songs(songs)
                db_manager.mark_chart_scraped()
                await query.message.reply_text(f"✅ *Scraper finished!* Added *{added}* new songs.\nTotal in queue: *{db_manager.get_queue_count()}*", parse_mode="Markdown")
            else:
                await query.message.reply_text("⚠️ Scraper ran but found no songs.")
        except Exception as exc:
            await query.message.reply_text(f"❌ Scraper failed: `{exc}`", parse_mode="Markdown")

        text, markup = build_main_dashboard()
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
        return ConversationHandler.END

    if cmd == "fetch_next":
        song = db_manager.pop_next_queued_song()
        if not song:
            await _safe_edit(query, "📭 Queue is empty! Tap *Run Chart Scraper* first.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]]))
            return ConversationHandler.END

        text, markup = build_song_panel(song)
        await _safe_edit(query, text, markup)
        return ConversationHandler.END

    if cmd == "open_panel":
        song = db_manager.get_song(video_id)
        if not song:
            await _safe_edit(query, "⚠️ Song not found.")
            return ConversationHandler.END

        text, markup = build_song_panel(song)
        msg = await _safe_edit(query, text, markup)
        if msg and song["current_macro_state"] not in _RESTING_STATES:
            asyncio.create_task(live_panel_updater(context, chat_id, msg.message_id, video_id))
        return ConversationHandler.END

    if cmd == "set_target":
        song = db_manager.get_song(video_id)
        if song and song["current_macro_state"] == "PAUSED":
            db_manager.update_state(video_id, macro=_retry_macro_from_workspace(song), micro="IDLE")
        db_manager.set_target_state(video_id, extra)
        song = db_manager.get_song(video_id)
        text, markup = build_song_panel(song)
        msg = await _safe_edit(query, text, markup)
        if msg:
            asyncio.create_task(live_panel_updater(context, chat_id, msg.message_id, video_id))
        return ConversationHandler.END

    if cmd == "continue_video":
        db_manager.set_target_state(video_id, "PUBLISHED")
        song = db_manager.get_song(video_id)
        text, markup = build_song_panel(song)
        msg = await _safe_edit(query, text, markup)
        if msg:
            asyncio.create_task(live_panel_updater(context, chat_id, msg.message_id, video_id))
        return ConversationHandler.END

    if cmd == "retry":
        song = db_manager.get_song(video_id)
        if not song:
            await _safe_edit(query, "⚠️ Song not found.")
            return ConversationHandler.END

        retry_macro = _retry_macro_from_workspace(song)
        target = extra or song.get("target_macro_state") or "PUBLISHED"
        db_manager.update_state(video_id, macro=retry_macro, micro="IDLE")
        db_manager.set_target_state(video_id, target)

        song = db_manager.get_song(video_id)
        text, markup = build_song_panel(song)
        msg = await _safe_edit(query, text, markup)
        if msg:
            asyncio.create_task(live_panel_updater(context, chat_id, msg.message_id, video_id))
        return ConversationHandler.END

    if cmd == "abort":
        db_manager.request_abort(video_id)
        await query.answer("🛑 Kill signal sent — stopping at next safe point.", show_alert=True)
        return ConversationHandler.END

    if cmd == "pause":
        db_manager.set_target_state(video_id, "PAUSED")
        await query.answer("⏸️ Pausing at next checkpoint…", show_alert=True)
        return ConversationHandler.END

    if cmd == "discard":
        db_manager.update_state(video_id, macro="DISCARDED", micro="IDLE")
        await _safe_edit(query, "🗑️ Song discarded.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="back_to_main")]]))
        return ConversationHandler.END

    if cmd == "approve_lyrics":
        db_manager.update_state(video_id, macro="LYRICS_APPROVED", micro="IDLE")
        song = db_manager.get_song(video_id)
        text, markup = build_song_panel(song)
        msg = await _safe_edit(query, text, markup)
        if msg:
            asyncio.create_task(live_panel_updater(context, chat_id, msg.message_id, video_id))
        return ConversationHandler.END

    if cmd == "approve_video":
        db_manager.update_state(video_id, macro="VIDEO_APPROVED", micro="IDLE")
        db_manager.set_target_state(video_id, "PUBLISHED")
        song = db_manager.get_song(video_id)
        text, markup = build_song_panel(song)
        msg = await _safe_edit(query, text, markup)
        if msg:
            asyncio.create_task(live_panel_updater(context, chat_id, msg.message_id, video_id))
        return ConversationHandler.END

    if cmd == "edit_lyrics":
        song = db_manager.get_song(video_id)
        if not song: return ConversationHandler.END

        workspace    = song.get("workspace_dir") or ""
        lrc_path     = os.path.join(workspace, "lyrics.lrc")
        txt_path     = os.path.join(workspace, "lyrics.txt")
        lyrics_path  = lrc_path if os.path.exists(lrc_path) else (txt_path  if os.path.exists(txt_path) else None)

        context.user_data["editing_video_id"]   = video_id
        context.user_data["editing_lyrics_path"] = lyrics_path

        instructions = (
            f"✏️ *Editing lyrics for {_esc(song['title'])}*\n\n"
            "Download the file above, fix it in a text editor, then:\n"
            "• *Reply with your corrected text*, OR\n"
            "• *Upload a corrected `.lrc` or `.txt` file*.\n\n"
            "Type /cancel to abort."
        )

        if lyrics_path:
            try:
                with open(lyrics_path, "rb") as fh:
                    await query.message.reply_document(document=fh, filename=os.path.basename(lyrics_path), caption=instructions, parse_mode="Markdown")
            except Exception:
                await query.message.reply_text(instructions, parse_mode="Markdown")
        else:
            await query.message.reply_text(f"{instructions}\n\n_(No existing lyrics file found — upload one to start.)_", parse_mode="Markdown")

        await query.edit_message_reply_markup(reply_markup=None)
        return WAITING_FOR_LYRICS_TEXT

    if cmd == "edit_metadata":
        song = db_manager.get_song(video_id)
        if not song:
            await _safe_edit(query, "⚠️ Song not found.")
            return ConversationHandler.END

        context.user_data["editing_metadata_video_id"] = video_id
        await query.message.reply_text(
            "✏️ *Edit video display text*\n\n"
            f"Current title:\n`{_esc(song['title'])}`\n"
            f"Current artist:\n`{_esc(song['artist'])}`\n\n"
            "Reply in this format:\n`Song title | Artist name`\n\n"
            "Type /cancel to abort.",
            parse_mode="Markdown",
        )
        return WAITING_FOR_METADATA

    if cmd == "edit_source":
        song = db_manager.get_song(video_id)
        if not song:
            await _safe_edit(query, "⚠️ Song not found.")
            return ConversationHandler.END

        current_url = song.get("url") or f"https://www.youtube.com/watch?v={video_id}"
        context.user_data["editing_source_video_id"] = video_id
        await query.message.reply_text(
            "🔗 *Change audio source*\n\n"
            f"Current source:\n{_esc(current_url)}\n\n"
            "Reply with the new YouTube link.\n\n"
            "Type /cancel to abort.",
            parse_mode="Markdown",
        )
        return WAITING_FOR_SOURCE_URL

    return ConversationHandler.END


async def handle_metadata_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    video_id = context.user_data.get("editing_metadata_video_id")
    raw_text = (update.message.text or "").strip()

    if not video_id:
        await update.message.reply_text("❌ Context lost. Open the song panel and tap Edit Title / Artist again.")
        return ConversationHandler.END

    if "|" not in raw_text:
        await update.message.reply_text(
            "Please use this format:\n`Song title | Artist name`",
            parse_mode="Markdown",
        )
        return WAITING_FOR_METADATA

    title, artist = [part.strip() for part in raw_text.split("|", 1)]
    if not title or not artist:
        await update.message.reply_text(
            "Both fields are needed. Use:\n`Song title | Artist name`",
            parse_mode="Markdown",
        )
        return WAITING_FOR_METADATA

    db_manager.update_song_metadata(video_id, title, artist)
    context.user_data.pop("editing_metadata_video_id", None)

    song = db_manager.get_song(video_id)
    text, markup = build_song_panel(song)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
    return ConversationHandler.END


async def handle_source_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    video_id = context.user_data.get("editing_source_video_id")
    url = (update.message.text or "").strip()

    if not video_id:
        await update.message.reply_text("❌ Context lost. Open the song panel and tap Change Source again.")
        return ConversationHandler.END

    if not (url.startswith("https://www.youtube.com/") or url.startswith("https://youtu.be/")):
        await update.message.reply_text("Please send a valid YouTube link.")
        return WAITING_FOR_SOURCE_URL

    db_manager.update_song_source(video_id, url)
    context.user_data.pop("editing_source_video_id", None)

    song = db_manager.get_song(video_id)
    text, markup = build_song_panel(song)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
    return ConversationHandler.END

async def handle_lyrics_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    video_id     = context.user_data.get("editing_video_id")
    lyrics_path  = context.user_data.get("editing_lyrics_path")
    new_text     = update.message.text

    if not video_id:
        await update.message.reply_text("❌ Context lost. Tap 'Edit Natively' again.")
        return ConversationHandler.END

    if not lyrics_path:
        song        = db_manager.get_song(video_id)
        ws          = song.get("workspace_dir", "") if song else ""
        lyrics_path = os.path.join(ws, "lyrics.txt")

    os.makedirs(os.path.dirname(lyrics_path), exist_ok=True)
    with open(lyrics_path, "w", encoding="utf-8") as fh:
        fh.write(new_text)

    db_manager.update_state(video_id, macro="LYRICS_APPROVED", micro="IDLE")
    context.user_data.clear()

    await update.message.reply_text(
        "✅ *Lyrics saved and approved!* The pipeline will resume shortly.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Dashboard", callback_data="back_to_main")]]),
    )
    return ConversationHandler.END

async def handle_lyrics_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    video_id = context.user_data.get("editing_video_id")
    doc      = update.message.document
    if not doc: return ConversationHandler.END

    fname = (doc.file_name or "").lower()
    if not (fname.endswith(".lrc") or fname.endswith(".txt")):
        await update.message.reply_text("❌ Please upload a `.lrc` or `.txt` file.", parse_mode="Markdown")
        return WAITING_FOR_LYRICS_TEXT

    if not video_id:
        await update.message.reply_text("⚠️ No active editing session. Tap 'Edit Natively' first.")
        return ConversationHandler.END

    song      = db_manager.get_song(video_id)
    workspace = song.get("workspace_dir") if song else None
    if not workspace:
        await update.message.reply_text("❌ Workspace not found.")
        return ConversationHandler.END

    ext       = ".lrc" if fname.endswith(".lrc") else ".txt"
    save_path = os.path.join(workspace, f"lyrics{ext}")

    tg_file   = await context.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(save_path)

    stale = os.path.join(workspace, "lyrics.txt" if ext == ".lrc" else "lyrics.lrc")
    if os.path.exists(stale): os.remove(stale)

    db_manager.update_state(video_id, macro="LYRICS_APPROVED", micro="IDLE")
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ *Lyrics file saved* (`{fname}`) *and approved!* Pipeline resumes shortly.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Dashboard", callback_data="back_to_main")]]),
    )
    return ConversationHandler.END

async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Lyrics edit cancelled.")
    return ConversationHandler.END


async def log_bot_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Telegram update failed: %s", update, exc_info=context.error)

def main() -> None:
    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN missing in .env!")
        return

    log.info("🤖 EchoForge Telegram Dashboard booting...")
    db_manager.init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start), CallbackQueryHandler(button_router, pattern=r"^(edit_lyrics|edit_metadata|edit_source):")],
        states={
            WAITING_FOR_LYRICS_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_lyrics_text_reply),
                MessageHandler(filters.Document.ALL, handle_lyrics_file_upload),
                CallbackQueryHandler(button_router),
            ],
            WAITING_FOR_METADATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_metadata_reply),
                CallbackQueryHandler(button_router),
            ],
            WAITING_FOR_SOURCE_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_source_reply),
                CallbackQueryHandler(button_router),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        per_message=False,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_router, pattern=r"^(?!(edit_lyrics|edit_metadata|edit_source):)"))
    app.add_error_handler(log_bot_error)
    log.info("✅ Bot online. Commands: /start <password>")
    app.run_polling()

if __name__ == "__main__":
    main()
