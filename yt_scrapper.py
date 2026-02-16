import json
import sqlite3
import time
import os
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Configuration ---
DB_FOLDER = "database"
LOG_FOLDER = "database/logs"
DB_NAME = os.path.join(DB_FOLDER, "songs.db")

def init_db():
    """Creates the database folder and table if they don't exist."""
    # Create the folder first
    if not os.path.exists(DB_FOLDER):
        os.makedirs(DB_FOLDER)
        print(f"bq Created directory: {DB_FOLDER}")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS posted_songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT UNIQUE NOT NULL,
            title TEXT,
            artist TEXT,
            posted_date TEXT,
            full_json TEXT
        )
    ''')
    conn.commit()
    conn.close()

def is_processed(video_id):
    """Checks if a video_id is already in the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM posted_songs WHERE video_id = ?', (video_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_to_db(data):
    """Saves the winner to the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO posted_songs (video_id, title, artist, posted_date, full_json)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            data['video_id'], 
            data['title'], 
            data['artist'], 
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            json.dumps(data)
        ))
        conn.commit()
        print(f"💾 Saved '{data['title']}' to database history.")
    except sqlite3.IntegrityError:
        print(f"⚠️ Warning: {data['title']} was already in DB (IntegrityError).")
    finally:
        conn.close()

# --- Scraper Section ---
def fetch_and_analyze_charts():
    print("🤖 Launching Headless Browser...")

    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--log-level=3")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    url = "https://charts.youtube.com/charts/TopSongs/global/weekly"
    print(f"🌍 Navigating to: {url}")
    
    try:
        driver.get(url)
        print("⏳ Waiting for chart data to render...")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "ytmc-entry-row"))
        )
        html_content = driver.page_source
        print("✅ Data received. Parsing HTML...")

    except Exception as e:
        print(f"❌ Error fetching page: {e}")
        return None
    finally:
        driver.quit()

    soup = BeautifulSoup(html_content, 'html.parser')
    rows = soup.find_all('ytmc-entry-row')
    
    candidates = []
    
    for row in rows:
        try:
            title_div = row.find(id="entity-title")
            if not title_div: continue
            
            raw_title = title_div.text.strip()
            endpoint_json = title_div.get('endpoint')
            
            if not endpoint_json: continue
            
            data = json.loads(endpoint_json)
            url = data['urlEndpoint']['url']
            video_id = url.split('v=')[-1]

            artist_div = row.find(id="artist-names")
            artists = [span.text.strip() for span in artist_div.find_all(class_="artistName")]
            artist_string = " & ".join(artists)

            metrics = row.find_all(class_="metric")
            if len(metrics) < 4: continue
            
            release_date_str = metrics[0].text.strip()
            weekly_views_str = metrics[3].text.strip().replace(',', '')
            
            if not weekly_views_str.isdigit(): continue
            weekly_views = int(weekly_views_str)

            try:
                release_date = datetime.strptime(release_date_str, '%b %d, %Y')
                days_old = (datetime.now() - release_date).days
                if days_old < 1: days_old = 1
            except ValueError:
                days_old = 365

            velocity_score = weekly_views

            candidates.append({
                'title': raw_title,
                'artist': artist_string,
                'url': f"https://www.youtube.com/watch?v={video_id}",
                'video_id': video_id,
                'views': weekly_views,
                'release_date': release_date_str,
                'priority_score': int(velocity_score)
            })

        except Exception:
            continue

    if not candidates:
        print("❌ No candidates found.")
        return None

    # Sort by Score High -> Low
    candidates.sort(key=lambda x: x['priority_score'], reverse=True)

    # --- Database Check Loop ---
    print(f"🔍 Checking top candidates against database...")
    for song in candidates:
        if not is_processed(song['video_id']):
            print(f"\n🏆 WINNER FOUND: {song['title']}")
            print(f"   Artist: {song['artist']}")
            print(f"   Score: {song['priority_score']:,} | Views: {song['views']:,}")
            return song
        else:
            print(f"   ⏭️ Skipping '{song['title']}' (Already processed)")
    
    print("\n⚠️ No new songs found! All top candidates are already in the database.")
    return None

if __name__ == "__main__":
    # 1. Ensure DB exists
    init_db()
    
    # 2. Run the Discovery
    winner_data = fetch_and_analyze_charts()
    
    if winner_data:
        # 3. Generate Timestamped Filename
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"trackinfo_{timestamp}.json"
        file_path = os.path.join(LOG_FOLDER, filename)
        
        # 4. Save to local JSON file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(winner_data, f, indent=4)
        
        print(f"✅ Data saved to: {file_path}")

        # 5. Save to Database (Mark as processed)
        save_to_db(winner_data)
        
        print("\nCreated!!")