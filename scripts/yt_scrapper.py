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
    """
    Scrapes the top 50 songs from YouTube's Global Weekly Charts.
    Uses a headless Chrome browser to render JavaScript-injected content
    and BeautifulSoup to parse the resulting DOM.
    
    Returns:
        list: A list of dictionaries containing track metadata.
    """
    print("🤖 Launching Headless Browser...")

    # Stealth configuration to bypass YouTube's anti-bot detection
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--log-level=3")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    url = "https://charts.youtube.com/charts/TopSongs/global/weekly"
    
    try:
        print(f"🌍 Navigating to: {url}")
        driver.get(url)
        
        # Await the rendering of YouTube's custom Polymer tags
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "ytmc-entry-row"))
        )
        time.sleep(2)  # Buffer for dynamic text injection
        
        html_content = driver.page_source

    except Exception as e:
        print(f"❌ Error fetching page: {e}")
        return None
    finally:
        driver.quit()

    print("✅ Data received. Parsing HTML...")
    soup = BeautifulSoup(html_content, 'html.parser')
    rows = soup.find_all('ytmc-entry-row')
    
    top_50_songs = []
    
    for row in rows:
        if len(top_50_songs) >= 50:
            break
            
        try:
            rank_span = row.find('span', id='rank')
            if not rank_span: continue
            rank = int(rank_span.text.strip())

            title_div = row.find(id="entity-title")
            if not title_div: continue
            raw_title = title_div.text.strip()
            
            # Extract URL from the embedded JSON in the 'endpoint' attribute
            endpoint_json = title_div.get('endpoint')
            if not endpoint_json: continue
            
            data = json.loads(endpoint_json)
            url = data['urlEndpoint']['url']
            video_id = url.split('v=')[-1]

            # Extract and aggregate multiple artist names
            artist_div = row.find(id="artist-names")
            artists = [span.text.strip() for span in artist_div.find_all(class_="artistName")]
            artist_string = " & ".join(artists)

            # Weekly views are located in the 4th metric column (index 3)
            metrics = row.find_all(class_="metric")
            if len(metrics) < 4: continue
            
            weekly_views_str = metrics[3].text.strip().replace(',', '')
            if not weekly_views_str.isdigit(): continue
            weekly_views = int(weekly_views_str)

            top_50_songs.append({
                'rank': rank,
                'title': raw_title,
                'artist': artist_string,
                'video_id': video_id,
                'url': f"https://www.youtube.com/watch?v={video_id}",
                'weekly_views': weekly_views,
                'search_query': f"{artist_string} {raw_title} official audio"
            })

        except Exception:
            continue

    return top_50_songs

if __name__ == "__main__":
    songs_data = scrape_top_50()
    
    if songs_data:
        # Setup output directory and dynamic filepath
        folder_path = os.path.join("Database", "JSON")
        os.makedirs(folder_path, exist_ok=True)
        
        today_date = datetime.now().strftime("%d-%m-%Y")
        output_file = os.path.join(folder_path, f"{today_date}.json")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(songs_data, f, indent=4, ensure_ascii=False)
            
        print(f"\n🎉 Success! Extracted {len(songs_data)} songs.")
        print(f"💾 Saved to: {output_file}")
        print(f"\n🏆 #1 CURRENT SONG: {songs_data[0]['title']} by {songs_data[0]['artist']} ({songs_data[0]['weekly_views']:,} views)")
    else:
        print("\n❌ Failed to extract any songs.")