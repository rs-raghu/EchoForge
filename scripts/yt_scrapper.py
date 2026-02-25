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
    """
    print("🤖 Launching Headless Browser...")

    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--incognito") 
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    # Back to the official weekly URL
    url = "https://charts.youtube.com/charts/TopSongs/global/weekly"
    
    try:
        print(f"🌍 Navigating to: {url}")
        driver.get(url)
        
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "ytmc-entry-row"))
        )
        time.sleep(2)  
        
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

    if top_50_songs:
        folder_path = os.path.join("Database", "JSON")
        os.makedirs(folder_path, exist_ok=True)

        today_date = datetime.now().strftime("%Y-%m-%d")
        output_file = os.path.join(folder_path, f"{today_date}.json")

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(top_50_songs, f, indent=4, ensure_ascii=False)
            
        print(f"\n🎉 Success! Extracted {len(top_50_songs)} songs.")
        print(f"💾 Saved to: {output_file}")
    else:
        print("\n❌ Failed to extract any songs.")

    return top_50_songs

if __name__ == "__main__":
    songs_data = scrape_top_50()