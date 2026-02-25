import os
import shutil
import db_manager

# The master folder for your 30+ downloaded backgrounds
BACKGROUNDS_POOL_DIR = os.path.join("Assets", "backgrounds")

def generate_background(title, artist, output_folder):
    """Selects a sequential background from your local folder."""
    print(f"\n🎨 Staging curated background for '{title}'...")
    
    os.makedirs(BACKGROUNDS_POOL_DIR, exist_ok=True)
    os.makedirs(output_folder, exist_ok=True)
    
    valid_extensions = ('.jpg', '.jpeg', '.png')
    available_bgs = [f for f in os.listdir(BACKGROUNDS_POOL_DIR) if f.lower().endswith(valid_extensions)]
    total_bgs = len(available_bgs)
    
    if total_bgs == 0:
        print("   ❌ Error: No backgrounds found in Assets/backgrounds! Please add images.")
        return None
        
    # Sort files to guarantee consistent order
    available_bgs.sort()
    
    # Get total generated videos, default to 0 if anything fails
    try:
        video_count = db_manager.get_total_video_count()
    except Exception:
        video_count = 0
        
    # Modulo math to cycle through the list
    bg_index = video_count % total_bgs
    chosen_bg = available_bgs[bg_index]
    
    source_path = os.path.join(BACKGROUNDS_POOL_DIR, chosen_bg)
    final_bg_path = os.path.join(output_folder, "bg.jpg")
    
    shutil.copy(source_path, final_bg_path)
    print(f"✅ Success! Background '{chosen_bg}' staged.")
    return final_bg_path