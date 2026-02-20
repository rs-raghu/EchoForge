import json
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

def scrape_top_50():
    print("🤖 Launching Headless Browser...")

    # 1. THE BULLETPROOF BROWSER SETUP (From your working code)
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--log-level=3")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    url = "https://charts.youtube.com/charts/TopSongs/global/weekly"
    print(f"🌍 Navigating to: {url}")
    
    try:
        # 2. FETCH THE PAGE
        driver.get(url)
        print("⏳ Waiting for chart data to render...")
        
        # Wait until the custom web components load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "ytmc-entry-row"))
        )
        
        # Give it an extra second to ensure text is fully injected into the tags
        time.sleep(2) 
        
        html_content = driver.page_source
        print("✅ Data received. Parsing HTML...")

    except Exception as e:
        print(f"❌ Error fetching page: {e}")
        return None
    finally:
        driver.quit()

    # 3. PARSE THE HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    rows = soup.find_all('ytmc-entry-row')
    
    top_50_songs = []
    
    for row in rows:
        # Stop once we hit 50 valid songs
        if len(top_50_songs) >= 50:
            break
            
        try:
            # --- RANK ---
            rank_span = row.find('span', id='rank')
            if not rank_span: continue
            rank = int(rank_span.text.strip())

            # --- TITLE & URL ---
            title_div = row.find(id="entity-title")
            if not title_div: continue
            
            raw_title = title_div.text.strip()
            endpoint_json = title_div.get('endpoint')
            
            if not endpoint_json: continue
            
            data = json.loads(endpoint_json)
            url = data['urlEndpoint']['url']
            video_id = url.split('v=')[-1]

            # --- ARTIST(S) ---
            artist_div = row.find(id="artist-names")
            artists = [span.text.strip() for span in artist_div.find_all(class_="artistName")]
            artist_string = " & ".join(artists)

            # --- VIEWS ---
            metrics = row.find_all(class_="metric")
            if len(metrics) < 4: continue
            
            weekly_views_str = metrics[3].text.strip().replace(',', '')
            if not weekly_views_str.isdigit(): continue
            weekly_views = int(weekly_views_str)

            # --- COMPILE DATA ---
            top_50_songs.append({
                'rank': rank,
                'title': raw_title,
                'artist': artist_string,
                'video_id': video_id,
                'url': f"https://www.youtube.com/watch?v={video_id}",
                'weekly_views': weekly_views,
                'search_query': f"{artist_string} {raw_title} official audio"
            })

        except Exception as e:
            # Skip ad rows or malformed HTML
            continue

    return top_50_songs

if __name__ == "__main__":
    songs_data = scrape_top_50()
    
    if songs_data:
        # 4. SETUP FOLDERS AND FILENAME
        # Create the path string: "Database/JSON"
        folder_path = os.path.join("Database", "JSON")
        
        # Tell the OS to physically create the folders if they don't exist yet
        # exist_ok=True prevents it from crashing if the folder is already there tomorrow
        os.makedirs(folder_path, exist_ok=True)
        
        # Get today's date in YYYY-MM-DD format (e.g., "2026-02-20")
        today_date = datetime.now().strftime("%d-%m-%Y")
        filename = f"{today_date}.json"
        
        # Combine folder and filename: "Database/JSON/2026-02-20.json"
        output_file = os.path.join(folder_path, filename)
        
        # 5. SAVE TO JSON
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(songs_data, f, indent=4, ensure_ascii=False)
            
        print(f"\n🎉 Success! Extracted {len(songs_data)} songs.")
        print(f"💾 Saved to: {output_file}")
        
        # Quick preview of the #1 song
        print("\n🏆 #1 CURRENT SONG:")
        print(f"   {songs_data[0]['title']} by {songs_data[0]['artist']} ({songs_data[0]['weekly_views']:,} views)")
    else:
        print("\n❌ Failed to extract any songs.")