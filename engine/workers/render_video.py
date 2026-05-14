import os
import sys
import json
import subprocess
import shutil

# Ensure the root directory is in the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.logger import get_logger

log = get_logger(__name__)

def render(song):
    """
    Renders the final lyric video using Remotion.
    Copies assets to the Remotion public directory, triggers the CLI, 
    and saves the output video back to the workspace.
    
    Returns True on success, False on failure.
    """
    workspace_dir = song.get('workspace_dir')
    title = song.get('title', 'Unknown Title')
    artist = song.get('artist', 'Unknown Artist')

    if not workspace_dir:
        log.error("❌ Missing workspace directory.")
        return False

    audio_path = os.path.join(workspace_dir, "audio.mp3")
    timestamps_path = os.path.join(workspace_dir, "timestamps.json")
    output_video = os.path.join(workspace_dir, "final_video.mp4")

    # If it's already rendered (e.g. paused and resumed), skip
    if os.path.exists(output_video):
        log.info(f"✅ Video already rendered at {output_video}")
        return True

    if not os.path.exists(audio_path) or not os.path.exists(timestamps_path):
        log.error(f"❌ Missing required assets (audio.mp3 or timestamps.json) for '{title}'.")
        return False

    # Define Remotion paths
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    remotion_dir = os.path.join(root_dir, "remotion")
    public_dir = os.path.join(remotion_dir, "public")
    
    if not os.path.exists(remotion_dir):
        log.error(f"❌ Remotion project directory not found at {remotion_dir}")
        return False

    log.info(f"🎬 Preparing Remotion environment for '{title}'...")

    try:
        # 1. Prepare the Public Directory
        os.makedirs(public_dir, exist_ok=True)
        
        # Copy assets into the public folder so the React app can read them natively
        shutil.copy(audio_path, os.path.join(public_dir, "audio.mp3"))
        shutil.copy(timestamps_path, os.path.join(public_dir, "timestamps.json"))

        # 2. Prepare the Dynamic Props
        # These are injected directly into your React Root component
        props = {
            "title": title,
            "artist": artist,
            # Because they are in the public folder, we just pass the filenames
            "audioUrl": "audio.mp3",
            "timestampsUrl": "timestamps.json"
        }

        props_file = os.path.join(remotion_dir, "current_props.json")
        with open(props_file, "w", encoding="utf-8") as f:
            json.dump(props, f)

        log.info("🔥 Starting Remotion render engine...")

        # 3. Construct the Remotion CLI command
        # Syntax: npx remotion render <entry> <composition> <output> --props=<json_file>
        cmd = [
            "npx",
            "remotion",
            "render",
            "src/index.ts",
            "LyricVideo",  # Matches the composition ID in your Remotion Root
            output_video,
            f"--props={props_file}"
        ]

        # 4. Execute and stream output
        process = subprocess.Popen(
            cmd,
            cwd=remotion_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        for line in process.stdout:
            line = line.strip()
            if line:
                # Log Remotion's progress frames (Optional: set to debug if it's too noisy)
                log.info(f"[REMOTION] {line}")

        process.wait()

        # 5. Verify Success and Cleanup
        if process.returncode == 0 and os.path.exists(output_video):
            log.info(f"✅ Video rendered successfully: {output_video}")
            
            # Clean up the public folder to save space and prevent leaks
            os.remove(os.path.join(public_dir, "audio.mp3"))
            os.remove(os.path.join(public_dir, "timestamps.json"))
            os.remove(props_file)
            
            return True
        else:
            log.error(f"❌ Remotion render failed with exit code {process.returncode}")
            return False

    except Exception as e:
        log.exception(f"❌ Unexpected error during rendering: {e}")
        return False

# --- Independent Testing ---
if __name__ == "__main__":
    print("Testing Render Worker...")
    test_song = {
        "title": "Test Track",
        "artist": "Test Artist",
        "workspace_dir": "./test_workspace"
    }
    # success = render(test_song)
    print("Note: Requires a valid Remotion project in ../../../remotion and assets in the workspace.")