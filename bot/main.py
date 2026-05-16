"""
bot/main.py

EchoForge V3 — Telegram Dashboard Bot.

Fixes applied
─────────────
• Bug 1  : "Upload to YouTube" now calls update_state(macro='VIDEO_APPROVED')
           AND set_target_state('PUBLISHED'). Previously it only set the target,
           leaving current_macro_state as PREVIEW_PENDING which is not in the
           STATE_MACHINE, so uploads never triggered.

• Bug 4  : bot/keyboards.py is dead code — removed. All keyboard builders live
           here, matching the original file structure.

• Bug 5  : /start requires SECRET_PASSWORD from .env. Any Telegram user who
           finds the bot is rejected before seeing the dashboard.

• Lyrics : When live_panel_updater detects LYRICS_REVIEW_PENDING, it sends the
           actual lyrics file (.lrc or .txt) as a Telegram document so the user
           can read/download it before approving.

• Editor : Native lyrics editor now sends the file and accepts EITHER a text
           reply OR a .lrc/.txt file upload, working around Telegram's 4096-char
           message limit for long lyrics.

• Cache  : "Run Chart Scraper" button shows the age of the last scrape and
           blocks redundant scrapes within CHART_CACHE_HOURS (6 h default).
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

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db_manager
from utils.logger import get_logger

# discovery is optional (may not be built yet)
try:
    from discovery import chart_scraper
except ImportError:
    chart_scraper = None

log = get_logger(__name__)
load_dotenv()

BOT_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "")
SECRET_PASSWORD = os.getenv("SECRET_PASSWORD", "")

# Conversation states
(
    WAITING_FOR_LYRICS_TEXT,
    WAITING_FOR_LYRICS_FILE,
) = range(2)


# ─── MarkdownV1 escaping ──────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Escape special characters for Telegram Markdown (parse_mode='Markdown')."""
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


# ─── Dashboard builders ───────────────────────────────────────────────────────

def build_main_dashboard() -> tuple[str, InlineKeyboardMarkup]:
    """Build the /start Master Control dashboard."""
    jobs      = db_manager.get_active_jobs()
    q_count   = db_manager.get_queue_count()
    age_str, _= db_manager.get_last_scrape_info()
    scrape_lbl = f"🔍 Scraper  (last: {age_str})" if age_str else "🔍 Run Chart Scraper"

    text     = "🎛️ *EchoForge Master Control*\n\n"
    keyboard = []

    # Active jobs section
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

    # Queue info
    text += f"\n*Queue:* {q_count} song(s) waiting\n\n*Actions:*"

    keyboard += [
        [InlineKeyboardButton("▶️ Fetch Next from Queue",  callback_data="fetch_next")],
        [InlineKeyboardButton(scrape_lbl,                  callback_data="run_scraper")],
        [InlineKeyboardButton("🔄 Refresh Dashboard",       callback_data="refresh_main")],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def build_song_panel(song: dict) -> tuple[str, InlineKeyboardMarkup]:
    """Build the dynamic control panel for one song."""
    macro  = song["current_macro_state"]
    micro  = song["current_micro_state"]
    target = song["target_macro_state"]

    icon   = _state_icon(macro)
    text   = (
        f"🎵 *{_esc(song['title'])}*\n"
        f"👤 {_esc(song['artist'])}\n"
        f"────────────────\n"
        f"🎯 *Target:* `{target}`\n"
        f"{icon} *Status:* `{macro}`\n"
        f"🔍 *Activity:* `{micro}`\n\n"
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
        # Bug 1 fix: approve_video sets macro → VIDEO_APPROVED so the orchestrator
        # can find it in STATE_MACHINE and fire the upload worker.
        keyboard.append([
            InlineKeyboardButton("🚀 Upload to YouTube",  callback_data=f"approve_video:{song['video_id']}"),
            InlineKeyboardButton("🗑️ Discard",            callback_data=f"discard:{song['video_id']}"),
        ])

    elif macro == "FAILED":
        text += "❌ *Pipeline crashed. Check the logs.*"
        keyboard.append([
            InlineKeyboardButton("🔄 Retry",  callback_data=f"set_target:{song['video_id']}:{target}"),
        ])

    elif macro == "PUBLISHED":
        url = _read_published_url(song.get("workspace_dir"))
        text += f"🚀 *Published!*\n{_esc(url) if url else '_URL not found_'}"

    # Kill controls — only when a worker could be running
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


# ─── Live panel updater ───────────────────────────────────────────────────────

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
    """
    Refresh the song panel every 3 s while a worker is running.
    Stops when the job reaches a resting (human-input) or terminal state.

    When the state reaches LYRICS_REVIEW_PENDING, automatically sends the
    lyrics file as a Telegram document so the user can read it before deciding.
    """
    last_micro    = ""
    lyrics_sent   = False   # send the lyrics file only once
    preview_sent  = False   # send the 60-second video clip only once

    while True:
        await asyncio.sleep(3)
        song = db_manager.get_song(video_id)
        if not song:
            break

        macro = song["current_macro_state"]
        micro = song["current_micro_state"]

        # Refresh panel if micro changed or we just hit a resting state
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
                pass   # message unchanged or Telegram rate-limit — non-fatal

        # Lyrics file: send once when LYRICS_REVIEW_PENDING is first reached
        if macro == "LYRICS_REVIEW_PENDING" and not lyrics_sent:
            lyrics_sent = True
            await _send_lyrics_for_review(context, chat_id, song)

        # 60-second preview clip: send once when PREVIEW_PENDING is first reached
        if macro == "PREVIEW_PENDING" and not preview_sent:
            preview_sent = True
            await _send_video_preview(context, chat_id, song)

        # Stop the watcher once we hit a state that needs human input or is done
        if macro in _RESTING_STATES:
            break


async def _send_lyrics_for_review(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    song: dict,
) -> None:
    """
    Send the lyrics file (.lrc or .txt) as a Telegram document so the user
    can read the full content before tapping Approve or Edit.
    """
    workspace = song.get("workspace_dir")
    if not workspace:
        return

    lrc_path = os.path.join(workspace, "lyrics.lrc")
    txt_path = os.path.join(workspace, "lyrics.txt")

    lyrics_path = lrc_path if os.path.exists(lrc_path) else (
        txt_path if os.path.exists(txt_path) else None
    )

    if not lyrics_path:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Lyrics file not found in workspace. Upload a `.lrc` or `.txt` file.",
        )
        return

    ltype    = "Synced LRC" if lyrics_path.endswith(".lrc") else "Plain Text"
    filename = f"{song['title']} lyrics{os.path.splitext(lyrics_path)[1]}"

    try:
        with open(lyrics_path, "rb") as fh:
            await context.bot.send_document(
                chat_id=chat_id,
                document=fh,
                filename=filename,
                caption=(
                    f"📝 *Lyrics ready for review*\n"
                    f"_{_esc(song['title'])}_ — {ltype}\n\n"
                    "Use the panel buttons to Approve, Edit, or Reject."
                ),
                parse_mode="Markdown",
            )
    except Exception as exc:
        log.warning("⚠️  Could not send lyrics file: %s", exc)
        # Fallback: send a snippet as text
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



# ─── Video preview helpers ───────────────────────────────────────────────────

_PREVIEW_DURATION_S = 60          # seconds to cut from the rendered video
_PREVIEW_MAX_BYTES  = 48_000_000  # 48 MB — safe margin below Telegram's 50 MB bot limit


async def _make_preview_clip(video_path: str) -> str | None:
    """
    Cut the first _PREVIEW_DURATION_S seconds from *video_path* using ffmpeg,
    re-encode at 720p / CRF 28 to keep the file under Telegram's limit.

    Returns the clip path on success, None if ffmpeg fails or the file is
    too large to send.  Runs in a thread — never blocks the event loop.
    """
    import subprocess

    preview_path = video_path.replace(".mp4", "_preview.mp4")

    def _run() -> bool:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i",      video_path,
                "-t",      str(_PREVIEW_DURATION_S),
                "-vf",     "scale=-2:720",
                "-c:v",    "libx264",
                "-crf",    "28",
                "-preset", "fast",
                "-c:a",    "aac",
                "-b:a",    "128k",
                preview_path,
            ],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    try:
        ok = await asyncio.to_thread(_run)
    except Exception as exc:
        log.warning("\u26a0\ufe0f  ffmpeg preview crashed: %s", exc)
        return None

    if not ok:
        log.warning("\u26a0\ufe0f  ffmpeg exited with error — preview skipped.")
        return None

    try:
        size = os.path.getsize(preview_path)
    except OSError:
        return None

    if size > _PREVIEW_MAX_BYTES:
        log.warning(
            "\u26a0\ufe0f  Preview is %.1f MB — over Telegram limit, skipping.",
            size / 1_000_000,
        )
        try:
            os.remove(preview_path)
        except OSError:
            pass
        return None

    log.info("\u2705 Preview clip ready: %.1f MB", size / 1_000_000)
    return preview_path


async def _send_video_preview(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    song: dict,
) -> None:
    """
    Send a 60-second preview clip to the bot chat with Upload / Discard
    inline buttons attached directly to the video message.

    Steps:
      1. Locate final_video.mp4 in the workspace.
      2. Run ffmpeg in a thread to cut the clip.
      3. Send the clip as a Telegram video with caption + keyboard.
      4. On any failure, send a plain-text fallback with the same buttons.
    """
    workspace = song.get("workspace_dir")
    title     = song.get("title", "Unknown")
    artist    = song.get("artist", "Unknown")
    video_id  = song["video_id"]

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("\U0001f680 Upload to YouTube", callback_data=f"approve_video:{video_id}"),
        InlineKeyboardButton("\U0001f5d1\ufe0f Discard",   callback_data=f"discard:{video_id}"),
    ]])

    video_path = os.path.join(workspace, "final_video.mp4") if workspace else None

    if not video_path or not os.path.exists(video_path):
        log.warning("\u26a0\ufe0f  final_video.mp4 not found for '%s'.", title)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"\U0001f3ac *Render complete:* _{_esc(title)}_\n\n"
                "\u26a0\ufe0f `final_video.mp4` not found — use buttons to decide."
            ),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    # Notify while ffmpeg runs
    notice = await context.bot.send_message(
        chat_id=chat_id,
        text=f"\U0001f3ac *Render complete!* Cutting {_PREVIEW_DURATION_S}s preview clip\u2026",
        parse_mode="Markdown",
    )

    clip_path = await _make_preview_clip(video_path)

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=notice.message_id)
    except Exception:
        pass

    caption = (
        f"\U0001f3b5 *{_esc(title)}* \u2014 {_esc(artist)}\n"
        f"First {_PREVIEW_DURATION_S}s \u2014 does the sync look good?"
    )

    if clip_path:
        try:
            with open(clip_path, "rb") as fh:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=fh,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                )
            log.info("\u2705 60s preview sent for '%s'.", title)
            return
        except Exception as exc:
            log.warning("\u26a0\ufe0f  Could not send preview video: %s", exc)

    # Fallback: buttons without video
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"\U0001f3ac *Render complete:* _{_esc(title)}_\n\n"
            "_(Preview unavailable \u2014 ffmpeg error or file too large.)_\n\n"
            "Upload to YouTube or discard?"
        ),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

# ─── /start — Bug 5 fix: password gate ───────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point. Requires SECRET_PASSWORD as the first argument."""
    args     = context.args or []
    password = args[0] if args else ""

    if not SECRET_PASSWORD:
        # No password configured — warn in logs but allow access
        log.warning("⚠️  SECRET_PASSWORD not set in .env — bot is open to anyone!")
    elif password != SECRET_PASSWORD:
        await update.message.reply_text("❌ Unauthorized. Invalid or missing password.")
        return ConversationHandler.END

    db_manager.init_db()
    text, markup = build_main_dashboard()
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
    return ConversationHandler.END


# ─── Main button router ───────────────────────────────────────────────────────

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    parts    = query.data.split(":")
    cmd      = parts[0]
    video_id = parts[1] if len(parts) > 1 else None
    extra    = parts[2] if len(parts) > 2 else None

    chat_id = query.message.chat_id

    # ── Dashboard navigation ──────────────────────────────────────────────────
    if cmd in ("back_to_main", "refresh_main"):
        text, markup = build_main_dashboard()
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        return ConversationHandler.END

    # ── Chart scraper ─────────────────────────────────────────────────────────
    if cmd == "run_scraper":
        age_str, is_stale = db_manager.get_last_scrape_info()

        if not is_stale:
            await query.answer(
                f"⏳ Scraped {age_str} — waiting {db_manager.CHART_CACHE_HOURS}h before re-scraping.",
                show_alert=True,
            )
            return ConversationHandler.END

        await query.edit_message_text(
            "🔍 *Scraping global charts…* This may take 30–60 seconds.",
            parse_mode="Markdown",
        )
        try:
            if not chart_scraper:
                raise ImportError("discovery/chart_scraper.py not found.")

            songs = await asyncio.to_thread(chart_scraper.scrape_top_charts, limit=20)
            if songs:
                added = db_manager.add_discovered_songs(songs)
                db_manager.mark_chart_scraped()
                await query.message.reply_text(
                    f"✅ *Scraper finished!* Added *{added}* new songs to the queue.\n"
                    f"Total in queue: *{db_manager.get_queue_count()}*",
                    parse_mode="Markdown",
                )
            else:
                await query.message.reply_text("⚠️ Scraper ran but found no songs.")
        except Exception as exc:
            await query.message.reply_text(f"❌ Scraper failed: `{exc}`", parse_mode="Markdown")

        text, markup = build_main_dashboard()
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
        return ConversationHandler.END

    # ── Fetch next from queue ─────────────────────────────────────────────────
    if cmd == "fetch_next":
        song = db_manager.pop_next_queued_song()
        if not song:
            await query.edit_message_text(
                "📭 Queue is empty! Tap *Run Chart Scraper* first.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back", callback_data="back_to_main")
                ]]),
            )
            return ConversationHandler.END

        text, markup = build_song_panel(song)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        return ConversationHandler.END

    # ── Open song panel ───────────────────────────────────────────────────────
    if cmd == "open_panel":
        song = db_manager.get_song(video_id)
        if not song:
            await query.edit_message_text("⚠️ Song not found.")
            return ConversationHandler.END

        text, markup = build_song_panel(song)
        msg = await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)

        # Start live watcher only when the job is actually running
        if song["current_macro_state"] not in _RESTING_STATES:
            asyncio.create_task(
                live_panel_updater(context, chat_id, msg.message_id, video_id)
            )
        return ConversationHandler.END

    # ── Set target state (starts the orchestrator moving) ─────────────────────
    if cmd == "set_target":
        db_manager.set_target_state(video_id, extra)
        song = db_manager.get_song(video_id)
        text, markup = build_song_panel(song)
        msg = await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        # Start the live watcher — orchestrator will pick the job up within 2 s
        asyncio.create_task(
            live_panel_updater(context, chat_id, msg.message_id, video_id)
        )
        return ConversationHandler.END

    # ── Abort (kill switch) ───────────────────────────────────────────────────
    if cmd == "abort":
        db_manager.request_abort(video_id)
        await query.answer("🛑 Kill signal sent — stopping at next safe point.", show_alert=True)
        return ConversationHandler.END

    # ── Pause ─────────────────────────────────────────────────────────────────
    if cmd == "pause":
        db_manager.set_target_state(video_id, "PAUSED")
        await query.answer("⏸️ Pausing at next checkpoint…", show_alert=True)
        return ConversationHandler.END

    # ── Discard ───────────────────────────────────────────────────────────────
    if cmd == "discard":
        db_manager.update_state(video_id, macro="DISCARDED", micro="IDLE")
        await query.edit_message_text(
            "🗑️ Song discarded.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Menu", callback_data="back_to_main")
            ]]),
        )
        return ConversationHandler.END

    # ── Approve lyrics → let orchestrator continue ────────────────────────────
    if cmd == "approve_lyrics":
        db_manager.update_state(video_id, macro="LYRICS_APPROVED", micro="IDLE")
        song = db_manager.get_song(video_id)
        text, markup = build_song_panel(song)
        msg = await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        asyncio.create_task(
            live_panel_updater(context, chat_id, msg.message_id, video_id)
        )
        return ConversationHandler.END

    # ── Bug 1 fix: approve video → VIDEO_APPROVED (in STATE_MACHINE) ──────────
    if cmd == "approve_video":
        # CRITICAL: set current_macro_state = VIDEO_APPROVED so the orchestrator
        # finds it in STATE_MACHINE and fires the upload worker.
        # Setting only target_macro_state = PUBLISHED would leave the current
        # state as PREVIEW_PENDING, which is NOT in STATE_MACHINE, so the
        # orchestrator would never act on it.
        db_manager.update_state(video_id, macro="VIDEO_APPROVED", micro="IDLE")
        db_manager.set_target_state(video_id, "PUBLISHED")

        song = db_manager.get_song(video_id)
        text, markup = build_song_panel(song)
        msg = await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        asyncio.create_task(
            live_panel_updater(context, chat_id, msg.message_id, video_id)
        )
        return ConversationHandler.END

    # ── Edit lyrics natively ──────────────────────────────────────────────────
    if cmd == "edit_lyrics":
        song = db_manager.get_song(video_id)
        if not song:
            return ConversationHandler.END

        workspace    = song.get("workspace_dir") or ""
        lrc_path     = os.path.join(workspace, "lyrics.lrc")
        txt_path     = os.path.join(workspace, "lyrics.txt")
        lyrics_path  = lrc_path if os.path.exists(lrc_path) else (
            txt_path  if os.path.exists(txt_path) else None
        )

        context.user_data["editing_video_id"]   = video_id
        context.user_data["editing_lyrics_path"] = lyrics_path

        # Send the file for download + editing, then ask for a replacement.
        # We don't paste lyrics as text because Telegram caps messages at 4096
        # chars and many songs exceed that limit.
        instructions = (
            f"✏️ *Editing lyrics for {_esc(song['title'])}*\n\n"
            "Download the file above, fix it in a text editor, then:\n"
            "• *Reply with your corrected text* (for short lyrics), OR\n"
            "• *Upload a corrected `.lrc` or `.txt` file* as a document.\n\n"
            "Type /cancel to abort."
        )

        if lyrics_path:
            try:
                with open(lyrics_path, "rb") as fh:
                    await query.message.reply_document(
                        document=fh,
                        filename=os.path.basename(lyrics_path),
                        caption=instructions,
                        parse_mode="Markdown",
                    )
            except Exception:
                await query.message.reply_text(instructions, parse_mode="Markdown")
        else:
            await query.message.reply_text(
                f"{instructions}\n\n_(No existing lyrics file found — upload one to start.)_",
                parse_mode="Markdown",
            )

        await query.edit_message_reply_markup(reply_markup=None)
        return WAITING_FOR_LYRICS_TEXT   # ConversationHandler picks this up

    return ConversationHandler.END


# ─── Lyrics editor — text reply handler ──────────────────────────────────────

async def handle_lyrics_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User replied with corrected lyrics as raw text."""
    video_id     = context.user_data.get("editing_video_id")
    lyrics_path  = context.user_data.get("editing_lyrics_path")
    new_text     = update.message.text

    if not video_id:
        await update.message.reply_text("❌ Context lost. Tap 'Edit Natively' again.")
        return ConversationHandler.END

    # If no existing path, default to lyrics.txt in the workspace
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
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Dashboard", callback_data="back_to_main")
        ]]),
    )
    return ConversationHandler.END


# ─── Lyrics editor — file upload handler ─────────────────────────────────────

async def handle_lyrics_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    User uploaded a corrected .lrc or .txt file.
    Works whether we're in WAITING_FOR_LYRICS_TEXT state or the user just
    drops a file into the chat while a song is stalled.
    """
    video_id = context.user_data.get("editing_video_id")
    doc      = update.message.document

    if not doc:
        return ConversationHandler.END

    fname = (doc.file_name or "").lower()
    if not (fname.endswith(".lrc") or fname.endswith(".txt")):
        await update.message.reply_text(
            "❌ Please upload a `.lrc` or `.txt` file.", parse_mode="Markdown"
        )
        return WAITING_FOR_LYRICS_TEXT

    if not video_id:
        await update.message.reply_text(
            "⚠️ No active editing session. Tap 'Edit Natively' from the song panel first."
        )
        return ConversationHandler.END

    song      = db_manager.get_song(video_id)
    workspace = song.get("workspace_dir") if song else None
    if not workspace:
        await update.message.reply_text("❌ Workspace not found for this song.")
        return ConversationHandler.END

    ext       = ".lrc" if fname.endswith(".lrc") else ".txt"
    save_path = os.path.join(workspace, f"lyrics{ext}")

    tg_file   = await context.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(save_path)

    # If user uploaded a .lrc, remove any stale .txt (and vice versa)
    stale = os.path.join(workspace, "lyrics.txt" if ext == ".lrc" else "lyrics.lrc")
    if os.path.exists(stale):
        os.remove(stale)

    db_manager.update_state(video_id, macro="LYRICS_APPROVED", micro="IDLE")
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ *Lyrics file saved* (`{fname}`) *and approved!* Pipeline resumes shortly.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Dashboard", callback_data="back_to_main")
        ]]),
    )
    return ConversationHandler.END


async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Lyrics edit cancelled.")
    return ConversationHandler.END


# ─── App bootstrap ────────────────────────────────────────────────────────────

def main() -> None:
    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN missing in .env!")
        return

    log.info("🤖 EchoForge Telegram Dashboard booting...")
    db_manager.init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler wraps everything so the lyrics editor
    # can intercept text/file replies in WAITING_FOR_LYRICS_TEXT state.
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_router),
        ],
        states={
            WAITING_FOR_LYRICS_TEXT: [
                # Accept a plain-text reply
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handle_lyrics_text_reply,
                ),
                # Accept a file upload (works even in WAITING_FOR_LYRICS_TEXT)
                MessageHandler(
                    filters.Document.ALL,
                    handle_lyrics_file_upload,
                ),
                # Allow navigating back via buttons while editor is open
                CallbackQueryHandler(button_router),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        # Allow callback queries to re-enter the handler from any state
        per_message=False,
    )

    app.add_handler(conv)

    log.info("✅ Bot online. Commands: /start <password>")
    app.run_polling()


if __name__ == "__main__":
    main()
