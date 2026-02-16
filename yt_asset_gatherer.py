import yt_dlp
import json
import os
import glob

# --- Configuration ---
DB_FOLDER = "database/logs"
ASSETS_ROOT = "assets"

def get_latest_job():
    """Finds the most recent trackinfo JSON file created by Stage 1."""
    # Look for all json files in database/ matching the pattern
    list_of_files = glob.glob(os.path.join(DB_FOLDER, 'trackinfo_*.json'))
    
    if not list_of_files:
        print("❌ No job files found in database/. Run auto_discovery.py first.")
        return None, None

    # Get the latest file based on creation time
    latest_file = max(list_of_files, key=os.path.getctime)
    print(f"rz Found latest job: {latest_file}")
    
    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    return data, latest_file

def download_audio(video_id, video_url):
    """Downloads audio from YouTube and converts it to MP3."""
    
    # 1. Create a unique folder for this song
    song_folder = os.path.join(ASSETS_ROOT, video_id)
    if not os.path.exists(song_folder):
        os.makedirs(song_folder)
    
    # 2. Define the output path template
    # yt-dlp will replace %(ext)s with 'mp3'
    output_template = os.path.join(song_folder, 'audio')

    print(f"⬇️  Downloading audio for ID: {video_id}...")
    
    # 3. Configure yt-dlp options
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': output_template, # This saves it as assets/[ID]/audio
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
            
        # Verify the file exists (yt-dlp adds the extension automatically)
        final_path = f"{output_template}.mp3"
        if os.path.exists(final_path):
            print(f"✅ Audio saved to: {final_path}")
            return final_path
        else:
            print("❌ Download finished but file not found.")
            return None

    except Exception as e:
        print(f"❌ Critical Error in yt-dlp: {e}")
        return None

def update_job_file(json_path, data, audio_path):
    """Updates the JSON contract with the new audio path."""
    data['local_audio_path'] = audio_path
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    print("📝 Job contract updated with audio path.")

if __name__ == "__main__":
    # 1. Get the job
    job_data, job_file_path = get_latest_job()
    
    if job_data:
        video_id = job_data.get('video_id')
        url = job_data.get('url')
        
        # 2. Download
        if video_id and url:
            audio_path = download_audio(video_id, url)
            
            # 3. Update Contract
            if audio_path:
                update_job_file(job_file_path, job_data, audio_path)