import imaplib
import email
from email.header import decode_header
import os
import argparse
import time
import subprocess
from datetime import datetime
import re

# Configuration
IMAP_SERVER = "imap.gmail.com"
EMAIL_ACCOUNT = os.getenv("GMAIL_ACCOUNT")
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
LOCAL_DIARY_DIR = "diary"
BLOG_DRAFTS_DIR = "blog_drafts"
ANALYSIS_SCRIPT = "scripts/llm_graph_builder.py"
BLOG_WRITER_SCRIPT = "scripts/blog_writer.py"
SUBJECT_KEYWORD = "POMERA" # POMERAまたはPOMERAtoKNOWLEDGEを含む件名
ROLE_KEYWORD = "ROLEtoKNOWLEDGE" # 役割定義用キーワード
BLOG_KEYWORD = "BLOG"  # ブログ草案用キーワード
ROLE_DEF_FILE = "role_definition.txt"
HISTORY_FILE = "sync_history.txt"

def clean_filename(subject):
    """Converts email subject to a safe filename."""
    # Decode header if needed
    decoded_fragments = decode_header(subject)
    subject_str = ""
    for frag, encoding in decoded_fragments:
        if isinstance(frag, bytes):
            subject_str += frag.decode(encoding or "utf-8")
        else:
            subject_str += frag
            
    # Remove unsafe chars
    safe_name = re.sub(r'[\\/*?:"<>|]', "", subject_str)
    return safe_name.strip()

def get_body_content(msg):
    """Extracts text content from email body."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = part.get("Content-Disposition") or ""
            
            if content_type == "text/plain" and "attachment" not in content_disposition:
                try:
                    return part.get_payload(decode=True).decode()
                except:
                    pass
    else:
        try:
            return msg.get_payload(decode=True).decode()
        except:
            pass
    return None

def save_attachment(part, directory):
    """Saves an attachment to the directory."""
    filename = part.get_filename()
    if filename:
        filename = clean_filename(filename)
        filepath = os.path.join(directory, filename)
        
        if os.path.exists(filepath):
            print(f"      ⚠️  File exists, overwriting: {os.path.basename(filepath)}")
            
        with open(filepath, "wb") as f:
            f.write(part.get_payload(decode=True))
        return filepath
    return None

def connect_imap():
    if not EMAIL_ACCOUNT or not APP_PASSWORD:
        print("❌ Error: GMAIL_ACCOUNT or GMAIL_APP_PASSWORD not set.")
        return None
    
    try:
        imaplib.IMAP4_SSL.timeout = 30  # 30秒タイムアウト
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, timeout=30)
        mail.login(EMAIL_ACCOUNT, APP_PASSWORD)
        return mail
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return None

def check_emails(mail, save_dir):
    # Load history
    history = set()
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            history = set(line.strip() for line in f if line.strip())

    # Fetch the latest IDs from the inbox directly
    status, count = mail.select("inbox")
    if status != "OK" or not count[0]:
        return [], []
        
    total_emails = int(count[0])
    print(f"📬 受信トレイのメール総数: {total_emails}")
    
    # まず未読メールのみを対象にする
    status, data = mail.search(None, 'UNSEEN')
    if status == "OK" and data[0]:
        email_ids = data[0].split()
        print(f"📩 未読メール {len(email_ids)} 件を処理")
    else:
        # 未読メールがなければ、直近50件をFETCHで取得
        print("📭 未読メールなし。直近50件をhistoryベースで確認")
        start_id = max(1, total_emails - 50 + 1)
        email_ids = [str(i).encode() for i in range(start_id, total_emails + 1)]
        
    saved_files = []
    blog_files = []
    new_history = []

    if not email_ids:
        return [], []

    print(f"📩 最新の {len(email_ids)} 件をチェック中...")

    for e_id_bytes in email_ids:
        e_id = e_id_bytes.decode()
        
        # Get UID for persistent tracking
        status, data = mail.fetch(e_id, "(UID)")
        if not data or not data[0]: continue
        
        uid_match = re.search(r'UID (\d+)', data[0].decode())
        if not uid_match:
            continue
        uid = uid_match.group(1)
        
        if uid in history:
            continue

        # Fetch subject
        status, msg_header = mail.fetch(e_id, "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
        subject_matched = False
        is_role_definition = False
        is_blog_draft = False
        subject = ""
        
        for response_part in msg_header:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                raw_subject = msg["Subject"]
                if raw_subject:
                    subject = clean_filename(raw_subject)
                    
                    # ROLEtoKNOWLEDGE を先に判定する
                    if ROLE_KEYWORD.lower() in subject.lower():
                        subject_matched = True
                        is_role_definition = True
                    # BLOG を判定（POMERAより優先）
                    elif BLOG_KEYWORD.lower() in subject.lower():
                        subject_matched = True
                        is_blog_draft = True
                    elif SUBJECT_KEYWORD.lower() in subject.lower():
                        subject_matched = True
        
        if not subject_matched:
            continue

        print(f"👉 Processing Email: {subject} (RoleDef: {is_role_definition}, Blog: {is_blog_draft})")
        
        status, msg_data = mail.fetch(e_id, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                
                # --- ROLE DEFINITION HANDLING ---
                if is_role_definition:
                    body = get_body_content(msg)
                    if body:
                        with open(ROLE_DEF_FILE, "w", encoding="utf-8") as f:
                            f.write(body)
                        print(f"      ✅ Role Definition Updated: {ROLE_DEF_FILE}")
                    else:
                        print("      ⚠️ Role definition email had no body.")
                
                # --- BLOG DRAFT HANDLING ---
                elif is_blog_draft:
                    body = get_body_content(msg)
                    if body:
                        blog_dir = BLOG_DRAFTS_DIR
                        if not os.path.exists(blog_dir):
                            os.makedirs(blog_dir)
                        filename = f"{datetime.now().strftime('%Y%m%d')}_{subject}.txt"
                        filepath = os.path.join(blog_dir, filename)
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write(body)
                        blog_files.append(filepath)
                        print(f"      📝 Saved Blog Draft: {filename}")
                        # 処理済みメールを既読にする
                        mail.store(e_id, '+FLAGS', '\\Seen')
                    else:
                        print("      ⚠️ Blog draft email had no body.")
                    
                # --- POMERA DIARY HANDLING ---
                else:
                    has_attachment = False
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_maintype() == 'multipart': continue
                            if part.get('Content-Disposition') is None: continue
                            
                            filename = part.get_filename()
                            if filename and filename.lower().endswith(".txt"):
                                saved_path = save_attachment(part, save_dir)
                                if saved_path:
                                    saved_files.append(saved_path)
                                    has_attachment = True
                                    print(f"      📎 Saved Attachment: {os.path.basename(saved_path)}")

                    if not has_attachment:
                        body = get_body_content(msg)
                        if body:
                            filename = f"{datetime.now().strftime('%Y%m%d')}_{subject}.txt"
                            filepath = os.path.join(save_dir, filename)
                            with open(filepath, "w", encoding="utf-8") as f:
                                f.write(body)
                            saved_files.append(filepath)
                            print(f"      📝 Saved Body: {filename}")
        
        new_history.append(uid)

    if new_history:
        with open(HISTORY_FILE, "a") as f:
            for uid in new_history:
                f.write(f"{uid}\n")

    # 同じファイルパスに上書き保存された重複を除去
    unique_files = list(dict.fromkeys(saved_files))
    if len(unique_files) < len(saved_files):
        print(f"⚠️ 重複ファイルを除去: {len(saved_files)} → {len(unique_files)} 件")
    unique_blog_files = list(dict.fromkeys(blog_files))
    return unique_files, unique_blog_files

def run_analysis(files):
    if not files: return
    print(f"🚀 LLM分析を開始します ({len(files)} 件)...")
    
    for i, file_path in enumerate(files, 1):
        print(f"   [{i}/{len(files)}] Analyzing: {file_path}")
        cmd = ["python3", ANALYSIS_SCRIPT, file_path]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"   ⚠️ 分析失敗: {file_path} (returncode={result.returncode})")
        # API レートリミット対策: 連続呼び出しの間に少し待つ
        if i < len(files):
            time.sleep(5)


def run_blog_pipeline(blog_files):
    """ブログ草案ファイルからブログ記事を生成し、はてなブログに投稿する。"""
    if not blog_files: return
    print(f"📝 ブログパイプラインを開始します ({len(blog_files)} 件)...")
    
    for i, file_path in enumerate(blog_files, 1):
        print(f"   [{i}/{len(blog_files)}] Processing Blog Draft: {file_path}")
        cmd = ["python3", BLOG_WRITER_SCRIPT, file_path]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"   ⚠️ ブログ記事生成失敗: {file_path} (returncode={result.returncode})")
        if i < len(blog_files):
            time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description="Sync Pomera emails and trigger analysis.")
    parser.add_argument("--watch", action="store_true", help="Keep watching for new emails.")
    parser.add_argument("--interval", type=int, default=300, help="Check interval in seconds (default: 300s/5min).")
    parser.add_argument("--blog-only", action="store_true", help="Process only BLOG emails.")
    
    args = parser.parse_args()

    if not os.path.exists(LOCAL_DIARY_DIR):
        os.makedirs(LOCAL_DIARY_DIR)
    if not os.path.exists(BLOG_DRAFTS_DIR):
        os.makedirs(BLOG_DRAFTS_DIR)

    print("📧 Pomera & Role & Blog Email Sync Agent Started")
    print(f"   Account: {EMAIL_ACCOUNT}")
    print(f"   Target Dir: {LOCAL_DIARY_DIR}")
    print(f"   Blog Drafts Dir: {BLOG_DRAFTS_DIR}")
    print(f"   Role Definition File: {ROLE_DEF_FILE}")
    print(f"   Blog Only Mode: {args.blog_only}")
    print("   --------------------------------")

    while True:
        mail = connect_imap()
        if mail:
            try:
                new_files, blog_files = check_emails(mail, LOCAL_DIARY_DIR)
                
                if args.blog_only:
                    # BLOGモード: ブログパイプラインのみ実行
                    if blog_files:
                        run_blog_pipeline(blog_files)
                    else:
                        print("💤 新着のBLOGメールはありませんでした。")
                else:
                    # 通常モード: 日記分析 + ブログパイプライン
                    if new_files:
                        run_analysis(new_files)
                    if blog_files:
                        run_blog_pipeline(blog_files)
                    if not new_files and not blog_files:
                        if not args.watch:
                            print("💤 新着の対象メールはありませんでした。")
                
                mail.logout()
            except Exception as e:
                print(f"❌ Error during check: {e}")
        
        if not args.watch:
            break
            
        print(f"⏳ 次のチェックまで待機中... ({args.interval}秒)")
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
