import os
import stable_whisper
import json
import db_manager

def align_audio_and_text(audio_path, lyrics_path, output_folder):
    """
    Uses Whisper AI to force-align a known text file to an audio file,
    generating precise word-level timestamps.
    """
    print("🧠 Booting up Whisper AI Alignment Engine...")

    audio_path = os.path.join(workspace_folder, "audio.mp3")
    lyrics_path = os.path.join(workspace_folder, "lyrics.txt")
    metadata_path = os.path.join(workspace_folder, "metadata.json")

    if not (os.path.exists(audio_path) and os.path.exists(lyrics_path) and os.path.exists(metadata_path)):
        print(f"❌ Error: Missing critical files in {workspace_folder}")
        return None
    
    # 1. Read the pristine lyrics we fetched earlier
    with open(lyrics_path, 'r', encoding='utf-8') as f:
        target_text = f.read()
        
    if not target_text.strip():
        print("❌ Error: lyrics.txt is empty!")
        return None

    try:
        # 2. Load the lightweight "base" model 
        # (Since we aren't transcribing from scratch, base is fast and highly accurate for alignment)
        model = stable_whisper.load_model('base')
        
        print("⏱️ Aligning audio waveforms to text (This may take a minute depending on your CPU/GPU)...")
        
        # 3. Perform Forced Alignment
        result = model.align(audio_path, target_text, language='en')
        
        # 4. Save the outputs!
        # Save as standard SRT (Great for previewing in VLC player)
        srt_path = os.path.join(output_folder, "subtitles.srt")
        result.to_srt_vtt(srt_path, word_level=False) 
        
        # Save as JSON (Crucial for our Remotion/React video engine later)
        json_path = os.path.join(output_folder, "timestamps.json")
        result.save_as_json(json_path)

        db_manager.update_job_status(metadata['video_id'], "ASSETS_READY")
        metadata['status'] = "ASSETS_READY"

        print(f"✅ Success! Alignment complete.")
        print(f"💾 Saved SRT to: {srt_path}")
        print(f"💾 Saved JSON to: {json_path}")
        
        return json_path

    except Exception as e:
        print(f"❌ Whisper Alignment failed: {e}")
        return None

if __name__ == "__main__":
    # ==========================================
    # STANDALONE TEST
    # ==========================================
    import glob
    
    print("🔍 Looking for the most recent Asset folder...")
    
    # Find the newest folder inside Assets/
    asset_folders = glob.glob(os.path.join("Assets", "*"))
    
    if not asset_folders:
        print("❌ No folders found in Assets/. Run auto_discovery.py first!")
    else:
        # Grab the most recently modified folder (which should be the one we just made)
        latest_workspace = max(asset_folders, key=os.path.getmtime)
        print(f"📂 Found workspace: {latest_workspace}")
        
        audio_target = os.path.join(latest_workspace, "audio.mp3")
        lyrics_target = os.path.join(latest_workspace, "lyrics.txt")
        
        # Check if the files actually exist before running
        if os.path.exists(audio_target) and os.path.exists(lyrics_target):
            align_audio_and_text(audio_target, lyrics_target, latest_workspace)
        else:
            print("❌ Missing audio.mp3 or lyrics.txt in the workspace.")