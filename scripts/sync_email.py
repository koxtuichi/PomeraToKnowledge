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
ANALYSIS_SCRIPT = "scripts/llm_graph_builder.py"
SUBJECT_KEYWORD = "POMERA" # Subject to filter by (all caps as requested)
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
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
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
        return []
        
    total_emails = int(count[0])
    
    # Process the last 50 emails
    start_id = max(1, total_emails - 50 + 1)
    status, data = mail.search(None, f"{start_id}:{total_emails}")
    if status != "OK" or not data[0]:
        return []
        
    email_ids = data[0].split()
    
    saved_files = []
    new_history = []

    if not email_ids:
        return []

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
        subject = ""
        
        for response_part in msg_header:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                raw_subject = msg["Subject"]
                if raw_subject:
                    subject = clean_filename(raw_subject)
                    if SUBJECT_KEYWORD.lower() in subject.lower():
                        subject_matched = True
        
        if not subject_matched:
            continue

        print(f"👉 Processing Pomera Email: {subject}")
        status, msg_data = mail.fetch(e_id, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                
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

    return saved_files

def run_analysis(files):
    if not files: return
    print(f"🚀 LLM分析を開始します (Triggering Analysis for {len(files)} files)...")
    
    for file_path in files:
        print(f"   Analyzing: {file_path}")
        cmd = ["python3", ANALYSIS_SCRIPT, file_path]
        subprocess.run(cmd)

def main():
    parser = argparse.ArgumentParser(description="Sync Pomera emails and trigger analysis.")
    parser.add_argument("--watch", action="store_true", help="Keep watching for new emails.")
    parser.add_argument("--interval", type=int, default=300, help="Check interval in seconds (default: 300s/5min).")
    
    args = parser.parse_args()

    if not os.path.exists(LOCAL_DIARY_DIR):
        os.makedirs(LOCAL_DIARY_DIR)

    print("📧 Pomera Email Sync Agent Started")
    print(f"   Account: {EMAIL_ACCOUNT}")
    print(f"   Target Dir: {LOCAL_DIARY_DIR}")
    print("   --------------------------------")

    while True:
        mail = connect_imap()
        if mail:
            try:
                new_files = check_emails(mail, LOCAL_DIARY_DIR)
                if new_files:
                    run_analysis(new_files)
                else:
                    if not args.watch:
                        print("💤 新着のPomeraメールはありませんでした。")
                
                mail.logout()
            except Exception as e:
                print(f"❌ Error during check: {e}")
        
        if not args.watch:
            break
            
        print(f"⏳ 次のチェックまで待機中... ({args.interval}秒)")
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
