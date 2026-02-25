import os
import json
import stable_whisper
import db_manager
import re

def align_audio_and_text(workspace_folder: str):
    """
    Uses Whisper AI to force-align a known text file to an audio file,
    generating precise word-level timestamps.
    Reads metadata to update the database upon completion.
    """
    print("🧠 Booting up Whisper AI Alignment Engine...")

    # 1. Define all paths based on the single workspace folder
    audio_path = os.path.join(workspace_folder, "audio.mp3")
    lyrics_path = os.path.join(workspace_folder, "lyrics.txt")
    metadata_path = os.path.join(workspace_folder, "metadata.json")

    # Ensure all required files actually exist
    if not (os.path.exists(audio_path) and os.path.exists(lyrics_path) and os.path.exists(metadata_path)):
        print(f"❌ Error: Missing critical files in {workspace_folder}")
        return None
    
    # 2. Load the metadata dictionary so we know which song we are working on
    with open(metadata_path, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    # 3. Read the pristine lyrics
    with open(lyrics_path, 'r', encoding='utf-8') as f:
        target_text = f.read()
        
    if not target_text.strip():
        print("❌ Error: lyrics.txt is empty!")
        return None

    try:
        # Load the lightweight "base" model 
        model = stable_whisper.load_model('base')
        print(f"⏱️ Aligning audio to text for: {metadata['title']}...")
        
        # Perform Forced Alignment
        result = model.align(audio_path, target_text, language='en')
        
        # 4. Save the outputs
        srt_path = os.path.join(workspace_folder, "subtitles.srt")
        result.to_srt_vtt(srt_path, word_level=False) 
        
        json_path = os.path.join(workspace_folder, "timestamps.json")
        result.save_as_json(json_path)

        # 5. Lock in the new State Machine status
        db_manager.update_job_status(metadata['video_id'], "ASSETS_READY")
        
        # Save the updated status back to the local file for the React engine
        metadata['status'] = "ASSETS_READY"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)

        print(f"\n✅ Success! Alignment complete. Status updated to ASSETS_READY.")
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
        # Grab the most recently modified folder
        latest_workspace = max(asset_folders, key=os.path.getmtime)
        print(f"📂 Found workspace: {latest_workspace}")
        
        # Execute the alignment using just the folder path
        align_audio_and_text(latest_workspace)