import sys
import os

# Ensure the root directory is in the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger

log = get_logger(__name__)

try:
    from ytmusicapi import YTMusic
except ImportError:
    log.error("❌ 'ytmusicapi' is not installed! Run: pip install ytmusicapi")
    YTMusic = None

def scrape_top_charts(limit=20):
    """
    Fetches the top trending songs from YouTube Music Global Charts.
    Returns a list of dictionaries containing video_id, title, and artist.
    """
    if not YTMusic:
        raise ImportError("ytmusicapi is missing. Please install it.")

    log.info(f"🔍 Initializing YTMusic API to fetch top {limit} trending songs...")
    yt = YTMusic()
    
    songs_data = []
    
    try:
        # Fetch global charts ('ZZ' is often used for Global in YT Music, or 'US' for United States)
        # We'll fetch the 'trending' or 'videos' chart.
        charts = yt.get_charts(country='US') 
        
        # 'videos' or 'tracks' usually contains the top charts
        # Fallback to 'trending' if 'videos' isn't available
        top_items = charts.get('videos', {}).get('items', [])
        if not top_items:
            top_items = charts.get('tracks', {}).get('items', [])

        for item in top_items:
            if len(songs_data) >= limit:
                break
                
            video_id = item.get('videoId')
            title = item.get('title')
            
            # Artists is usually a list of dictionaries, we extract the names and join them
            artists_list = item.get('artists', [])
            artist_name = ", ".join([a.get('name') for a in artists_list if a.get('name')])
            
            if not artist_name:
                artist_name = "Unknown Artist"

            if video_id and title:
                songs_data.append({
                    "video_id": video_id,
                    "title": title,
                    "artist": artist_name
                })
                
        log.info(f"✅ Successfully scraped {len(songs_data)} songs from the charts.")
        return songs_data

    except Exception as e:
        log.error(f"❌ Failed to scrape charts: {e}")
        return []

# --- Independent Testing ---
# You can run this file directly to test if it works without booting the whole bot!
if __name__ == "__main__":
    print("Testing Chart Scraper...")
    results = scrape_top_charts(limit=5)
    for i, s in enumerate(results, 1):
        print(f"{i}. {s['title']} by {s['artist']} (ID: {s['video_id']})")