import os
import json
import stable_whisper
import db_manager
import re

# BUG FIX: was 'from timestamps_processor import...' — the file is timestamp_processor.py
from timestamp_processor import process_timestamps


def align_audio_and_text(workspace_folder: str):
    """
    Uses Whisper AI to force-align a known lyrics.txt file to an audio file,
    generating precise word-level timestamps — then post-processes them into
    clean line-level segments ready for the video renderer.

    OUTPUT FILES:
      timestamps_raw.json  — raw Whisper word-level data (backup)
      timestamps.json      — clean line-level segments (used by renderer)
      lyrics.lrc           — LRC file with one line per lyric line
    """
    print("🧠 Booting up Whisper AI Alignment Engine...")

    audio_path    = os.path.join(workspace_folder, "audio.mp3")
    lyrics_path   = os.path.join(workspace_folder, "lyrics.txt")
    metadata_path = os.path.join(workspace_folder, "metadata.json")
    raw_json_path = os.path.join(workspace_folder, "timestamps_raw.json")
    json_path     = os.path.join(workspace_folder, "timestamps.json")
    lrc_path      = os.path.join(workspace_folder, "lyrics.lrc")

    if not os.path.exists(audio_path):
        print(f"❌ Missing audio: {audio_path}")
        return None
    if not os.path.exists(lyrics_path):
        print(f"❌ Missing lyrics: {lyrics_path}")
        return None
    if not os.path.exists(metadata_path):
        print(f"❌ Missing metadata: {metadata_path}")
        return None

    with open(metadata_path, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    with open(lyrics_path, 'r', encoding='utf-8') as f:
        target_text = f.read()

    if not target_text.strip():
        print("❌ lyrics.txt is empty!")
        return None

    try:
        model = stable_whisper.load_model('large-v2')
        print(f"⏱️  Aligning audio to text for: {metadata.get('title', '?')}...")

        result = model.align(audio_path, target_text, language='en')

        # ── Save raw word-level JSON (backup) ──────────────────────────────────
        # IMPORTANT: Do NOT call merge_all_segments() or merge_by_punctuation()
        # before this save — those calls collapse everything into 1 blob.
        result.save_as_json(raw_json_path)
        print(f"💾 Raw word-level timestamps saved to: {raw_json_path}")

        # ── POST-PROCESS: word-level → clean line-level ────────────────────────
        print("\n🔧 Running Timestamps Post-Processor...")
        processed_path = process_timestamps(workspace_folder)

        if not processed_path:
            print("⚠️  Post-processing failed. Raw timestamps kept as-is.")
        else:
            print(f"✅ Post-processing complete: {processed_path}")

        # ── Update state machine ───────────────────────────────────────────────
        db_manager.update_song_status(metadata['video_id'], "ASSETS_READY")
        metadata['status'] = "ASSETS_READY"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)

        print(f"\n✅ Alignment complete. Status → ASSETS_READY")
        return processed_path or raw_json_path

    except Exception as e:
        print(f"❌ Whisper Alignment failed: {e}")
        return None


if __name__ == "__main__":
    import glob

    print("🔍 Looking for the most recent Asset folder...")
    asset_folders = glob.glob(os.path.join("Assets", "*"))

    if not asset_folders:
        print("❌ No folders found in Assets/. Run auto_discovery.py first!")
    else:
        latest_workspace = max(asset_folders, key=os.path.getmtime)
        print(f"📂 Found workspace: {latest_workspace}")
        align_audio_and_text(latest_workspace)