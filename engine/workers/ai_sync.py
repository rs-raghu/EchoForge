import os
import sys
import json
import subprocess
from pathlib import Path

# Ensure the root directory is in the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.logger import get_logger

log = get_logger(__name__)

# You might need to adjust these paths or imports based on your actual legacy files
# In the new architecture, we want to isolate the logic as much as possible here.
try:
    import whisper_timestamped as whisper
except ImportError:
    log.error("❌ 'whisper-timestamped' is not installed!")
    whisper = None

def run_demucs(audio_path: str, output_dir: str) -> str | None:
    """
    Runs Demucs to isolate vocals from the audio file.
    Returns the path to the isolated vocals.mp3, or None on failure.
    """
    log.info(f"🎙️ Starting Demucs vocal isolation for {audio_path}...")
    try:
        # Construct the demucs command. Adjust model (htdemucs) as needed.
        cmd = [
            "demucs",
            "--two-stems=vocals",
            "--out", output_dir,
            audio_path
        ]
        
        # Run Demucs in a subprocess
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # You could potentially stream output to the log here if needed, 
        # but for now we just wait for it to finish.
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            log.error(f"❌ Demucs failed with return code {process.returncode}:\n{stdout}")
            return None
            
        # Demucs usually creates a folder structure like: output_dir/htdemucs/song_name/vocals.mp3
        # We need to locate that file.
        base_name = os.path.splitext(os.path.basename(audio_path))[0]
        vocals_path = os.path.join(output_dir, "htdemucs", base_name, "vocals.mp3") # or .wav depending on demucs version/settings
        
        # Try to find .wav if .mp3 isn't there, demucs defaults to wav often
        if not os.path.exists(vocals_path):
             vocals_path = os.path.join(output_dir, "htdemucs", base_name, "vocals.wav")
             
        if os.path.exists(vocals_path):
            log.info(f"✅ Demucs completed. Vocals saved to: {vocals_path}")
            return vocals_path
        else:
             log.error(f"❌ Demucs finished, but could not find vocals file at expected path.")
             return None

    except Exception as e:
        log.exception(f"❌ Unexpected error running Demucs: {e}")
        return None

def run_whisper_sync(vocals_path: str, lyrics_txt_path: str, workspace_dir: str) -> bool:
    """
    Runs whisper-timestamped to align the vocals with the provided lyrics.
    Saves the output to timestamps.json in the workspace.
    """
    log.info(f"🧠 Starting Whisper alignment on {vocals_path}...")
    if not whisper:
         return False

    try:
        with open(lyrics_txt_path, "r", encoding="utf-8") as f:
            lyrics_text = f.read()

        # Load the model (consider making the model size configurable)
        model = whisper.load_model("base", device="cpu") # Or "cuda" if available
        
        # Transcribe and force-align using the provided text
        log.info("🧠 Transcribing and aligning... (This may take a while)")
        result = whisper.transcribe(
            model,
            vocals_path,
            initial_prompt=lyrics_text, # Give Whisper the lyrics as a strong hint
            language="en" # Adjust if necessary
        )
        
        timestamps_path = os.path.join(workspace_dir, "timestamps.json")
        with open(timestamps_path, "w", encoding="utf-8") as f:
             json.dump(result, f, indent=2)
             
        log.info(f"✅ Whisper alignment complete. Saved to {timestamps_path}")
        return True

    except Exception as e:
        log.exception(f"❌ Error during Whisper alignment: {e}")
        return False

def process_lrc_timestamps(lrc_path: str, workspace_dir: str) -> bool:
    """
    If an LRC file already exists (from syncedlyrics), we don't need Whisper.
    We just parse the LRC and create a simplified timestamps.json.
    """
    log.info(f"⚡ Processing pre-synced LRC file: {lrc_path}")
    try:
        segments = []
        with open(lrc_path, 'r', encoding='utf-8') as f:
            for line in f:
                # Basic LRC parsing: [mm:ss.xx] Lyric text
                import re
                match = re.match(r'\[(\d{2}):(\d{2}\.\d{2,3})\](.*)', line)
                if match:
                    mins = int(match.group(1))
                    secs = float(match.group(2))
                    text = match.group(3).strip()
                    if text: # Ignore blank lines with timestamps
                        start_time = (mins * 60) + secs
                        
                        # We don't have exact word-level timestamps or end times from basic LRC.
                        # We estimate the end time or let the React renderer handle it.
                        segments.append({
                            "start": start_time,
                            "end": start_time + 3.0, # Placeholder end time
                            "text": text,
                            "words": [] # No word-level data in basic LRC
                        })
        
        # Fix up end times based on the start of the next segment
        for i in range(len(segments) - 1):
             segments[i]["end"] = segments[i+1]["start"]
             
        output_data = {"segments": segments}
        timestamps_path = os.path.join(workspace_dir, "timestamps.json")
        
        with open(timestamps_path, "w", encoding="utf-8") as f:
             json.dump(output_data, f, indent=2)
             
        log.info(f"✅ Processed LRC into {timestamps_path}")
        return True

    except Exception as e:
         log.exception(f"❌ Failed to process LRC file: {e}")
         return False

def process(song):
    """
    Main entry point for the AI Sync worker.
    Determines whether to use an existing .lrc file or run the Demucs/Whisper pipeline.
    """
    workspace_dir = song.get('workspace_dir')
    if not workspace_dir:
        log.error("❌ Missing workspace directory.")
        return False

    lrc_path = os.path.join(workspace_dir, "lyrics.lrc")
    txt_path = os.path.join(workspace_dir, "lyrics.txt")
    audio_path = os.path.join(workspace_dir, "audio.mp3")
    timestamps_path = os.path.join(workspace_dir, "timestamps.json")

    # If timestamps.json already exists, skip
    if os.path.exists(timestamps_path):
        log.info("✅ Timestamps already exist. Skipping AI Sync.")
        return True

    # SCENARIO A: We have a pre-synced LRC file. Fast path!
    if os.path.exists(lrc_path):
         log.info("⏩ Pre-synced LRC found. Skipping Demucs and Whisper.")
         return process_lrc_timestamps(lrc_path, workspace_dir)

    # SCENARIO B: We only have plain text. Must run Demucs + Whisper.
    elif os.path.exists(txt_path):
        if not os.path.exists(audio_path):
             log.error(f"❌ audio.mp3 missing in workspace. Cannot run AI Sync.")
             return False

        # 1. Isolate Vocals
        vocals_path = run_demucs(audio_path, workspace_dir)
        if not vocals_path:
             return False

        # 2. Align Lyrics
        success = run_whisper_sync(vocals_path, txt_path, workspace_dir)
        
        # Note: You might want to process the raw Whisper output into a cleaner
        # format required by your React app here, similar to your old timestamp_processor.py
        
        return success

    else:
        log.error("❌ No lyrics file found (.lrc or .txt). Cannot sync.")
        return False

# --- Independent Testing ---
if __name__ == "__main__":
    print("Testing AI Sync Worker...")
    # You would need a valid workspace with audio.mp3 and lyrics.txt to test this fully
    test_song = {
        "title": "Test Song",
        "workspace_dir": "./test_workspace"
    }
    # success = process(test_song)
    print("Note: Run with a real workspace to test Demucs/Whisper.")