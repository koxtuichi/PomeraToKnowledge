import os
import shutil
import time
import argparse
import subprocess
from datetime import datetime

# Default configuration
POMERA_MOUNT_NAME = "POMERA"  # Adjust if your mount name differs
LOCAL_DIARY_DIR = "diary"     # Relative to script
ANALYSIS_SCRIPT = "scripts/llm_graph_builder.py"

def get_pomera_path(mount_name):
    """Check if Pomera is mounted at /Volumes/{mount_name}"""
    path = f"/Volumes/{mount_name}"
    if os.path.exists(path):
        return path
    return None

def sync_files(source_dir, dest_dir):
    """
    Syncs .txt files from source to destination.
    Returns a list of updated file paths.
    """
    updated_files = []
    
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)

    print(f"📂 同期元をスキャン中: {source_dir}")
    
    # Walk through Pomera directory (recursive)
    for root, dirs, files in os.walk(source_dir):
        for file in files:
            if file.lower().endswith(".txt"):
                source_path = os.path.join(root, file)
                
                # Determine relative path to maintain structure if needed, 
                # or just flatten. Let's flatten for "diary" folder simplicity if preferred,
                # but Pomera might have folders. 
                # Strategy: Copy to flat structure with date prefix if needed, 
                # OR just mirror structure. 
                # Let's mirror structure for now to be safe.
                rel_path = os.path.relpath(source_path, source_dir)
                dest_path = os.path.join(dest_dir, rel_path)
                
                dest_folder = os.path.dirname(dest_path)
                if not os.path.exists(dest_folder):
                    os.makedirs(dest_folder)

                # Check modification time
                do_copy = False
                if not os.path.exists(dest_path):
                    do_copy = True
                    reason = "New file"
                else:
                    src_mtime = os.path.getmtime(source_path)
                    dst_mtime = os.path.getmtime(dest_path)
                    # Allow 2 second buffer for file system differences
                    if src_mtime > dst_mtime + 2:
                        do_copy = True
                        reason = "Updated"
                
                if do_copy:
                    print(f"✨ 同期中 ({reason}): {rel_path}")
                    shutil.copy2(source_path, dest_path)
                    updated_files.append(dest_path)

    return updated_files

def run_analysis(files):
    """Triggers the analysis script for the updated files."""
    if not files:
        return

    print("🚀 LLM分析を開始します...")
    # We can pass specific files to llm_graph_builder if it supports it, 
    # or just run it to process "all pending".
    # Currently llm_graph_builder scans the diary folder.
    
    # We might want to be selective to save API costs, but 
    # llm_graph_builder.py (v2) should theoretically handle "new files only" 
    # if we implemented hash checking.
    # For now, let's just run it. 
    
    cmd = ["python3", ANALYSIS_SCRIPT]
    subprocess.run(cmd)

def main():
    parser = argparse.ArgumentParser(description="Sync Pomera DM250 files and trigger analysis.")
    parser.add_argument("--watch", action="store_true", help="Keep watching for Pomera connection.")
    parser.add_argument("--mount", default=POMERA_MOUNT_NAME, help="Mount name of the Pomera device.")
    parser.add_argument("--dest", default=LOCAL_DIARY_DIR, help="Local destination directory.")
    
    args = parser.parse_args()

    print("📡 ポメラ同期エージェントを開始しました")
    print(f"   対象マウント: /Volumes/{args.mount}")
    print(f"   ローカル保存先: {args.dest}")

    while True:
        pomera_path = get_pomera_path(args.mount)
        
        if pomera_path:
            print(f"✅ ポメラを検出しました: {pomera_path}")
            
            # Sync
            updated = sync_files(pomera_path, args.dest)
            
            if updated:
                print(f"📦 {len(updated)} 件のファイルを同期しました。")
                run_analysis(updated)
            else:
                print("💤 新しい変更はありません。")
            
            if not args.watch:
                break
            
            # Wait before next scan to avoid spamming if watching (though usually we'd wait for unmount/remount)
            print("⏳ 次のサイクルまで待機中 (Ctrl+C で停止)...")
            time.sleep(60) 
            
        else:
            if args.watch:
                # print("Waiting for connection...", end="\r") # Simple feedback
                time.sleep(5)
            else:
                print("❌ ポメラが見つかりません。USB接続を確認するか、マウント名を確認してください。")
                break

if __name__ == "__main__":
    main()
