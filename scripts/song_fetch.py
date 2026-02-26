import os
import yt_dlp

# Sentinel return value so master_controller can distinguish
# "video unavailable" from other failures and auto-skip
UNAVAILABLE = "UNAVAILABLE"

def download_audio(youtube_url: str, output_folder: str, filename: str = "audio"):
    """
    Downloads the highest quality audio stream as MP3.
    Returns:
      - file path string on success
      - UNAVAILABLE sentinel if the video is geo/age restricted or deleted
      - None on other failures
    """
    print(f"🎵 Extracting audio from: {youtube_url}")

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': os.path.join(output_folder, f"{filename}.%(ext)s"),
        'quiet': False,
        'no_warnings': True,
        'nocheckcertificate': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])

        final_path = os.path.join(output_folder, f"{filename}.mp3")
        if os.path.exists(final_path):
            print(f"✅ Audio successfully saved to: {final_path}")
            return final_path
        else:
            print(f"❌ Audio file not found after download.")
            return None

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e).lower()
        # Detect all known unavailability reasons
        unavailable_triggers = [
            "this video is not available",
            "video unavailable",
            "this video has been removed",
            "private video",
            "this video is private",
            "age-restricted",
            "sign in to confirm your age",
            "blocked in your country",
            "not available in your country",
        ]
        if any(trigger in error_msg for trigger in unavailable_triggers):
            print(f"⛔ Video unavailable (geo/age/removed): {youtube_url}")
            return UNAVAILABLE

        print(f"❌ Audio download failed: {e}")
        return None

    except Exception as e:
        print(f"❌ Audio download failed: {e}")
        return None