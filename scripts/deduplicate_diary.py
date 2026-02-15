import os
import hashlib
import re
from collections import defaultdict
from datetime import datetime

DIARY_DIR = "diary"

def calculate_file_hash(filepath):
    """Calculates the MD5 hash of a file."""
    hasher = hashlib.md5()
    with open(filepath, "rb") as f:
        buf = f.read()
        hasher.update(buf)
    return hasher.hexdigest()

def extract_date_from_filename(filename):
    """Extracts date from filename if possible."""
    # Pattern 1: 20260215_POMERA...
    match1 = re.match(r"(\d{8})_", filename)
    if match1:
        return match1.group(1)
    
    # Pattern 2: ...POMERA2026年2月15日.txt
    match2 = re.search(r"POMERA(\d{4})年(\d{1,2})月(\d{1,2})日", filename)
    if match2:
        y, m, d = match2.groups()
        return f"{y}{int(m):02d}{int(d):02d}"
    
    return "99999999" # Unknown date

def main():
    if not os.path.exists(DIARY_DIR):
        print(f"Directory not found: {DIARY_DIR}")
        return

    # Group files by hash
    files_by_hash = defaultdict(list)
    
    print("🔍 Scanning for duplicates...")
    
    for filename in os.listdir(DIARY_DIR):
        if not filename.endswith(".txt"):
            continue
            
        filepath = os.path.join(DIARY_DIR, filename)
        file_hash = calculate_file_hash(filepath)
        files_by_hash[file_hash].append(filename)

    # Process duplicates
    duplicates_found = 0
    bytes_saved = 0
    
    for file_hash, filenames in files_by_hash.items():
        if len(filenames) > 1:
            duplicates_found += 1
            print(f"\nDuplicate group found ({len(filenames)} files):")
            
            # Sort filenames to decide which one to keep
            # Criteria: 
            # 1. Prefer filename with explicit date matching content (hard to know content date without reading, so rely on filename format)
            # 2. Prefer shorter filename (usually cleaner)
            # 3. Alphabetical order as tie breaker
            
            # Let's try to prioritize filenames that look "cleaner" or have standard prefix
            # The user has: 20260215_POMERA2026年2月15日.txt vs 20260216_POMERA2026年2月15日.txt
            # It seems the prefix 20260216 might be the excessive one if the content is 2/15.
            # However, looking at the file list:
            # 20260215_POMERA2026年2月15日.txt (Size 6124)
            # 20260216_POMERA2026年2月15日.txt (Size 6124)
            # 20260215_[POMERAtoKNOWLEDGE]2026年2月16日.txt (Size 1293)
            # 20260216_[POMERAtoKNOWLEDGE]2026年2月16日.txt (Size 1293)
            
            # It seems the sync script might be adding a date prefix based on sync time?
            # 20260216_... might be a duplicate created on the next day.
            
            # We will prefer the one where the prefix matches the inner date, OR the earliest prefix?
            # Actually, standard logic: keep the oldest filename (lexicographically) might be wrong if prefix is date.
            # 20260215 < 20260216. So 20260215 is "older" (earlier date).
            # Usually we want to keep the original.
            
            files_ranked = sorted(filenames)
            keep_file = files_ranked[0] # Keep the first one lexicographically (e.g. 20260215_...)
            remove_files = files_ranked[1:]
            
            print(f"  ✅ Keeping: {keep_file}")
            
            for rm_file in remove_files:
                rm_path = os.path.join(DIARY_DIR, rm_file)
                file_size = os.path.getsize(rm_path)
                print(f"  🗑️ Deleting: {rm_file}")
                os.remove(rm_path)
                bytes_saved += file_size

    print(f"\n✨ Cleanup complete.")
    print(f"   Duplicate groups resolved: {duplicates_found}")
    print(f"   Space reclaimed: {bytes_saved / 1024:.2f} KB")

if __name__ == "__main__":
    main()
