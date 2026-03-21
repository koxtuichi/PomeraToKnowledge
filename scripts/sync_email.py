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
STORY_DRAFTS_DIR = "story_drafts"
SECBLOG_DRAFTS_DIR = "secblog_drafts"
ANALYSIS_SCRIPT = "scripts/llm_graph_builder.py"
BLOG_ARTICLE_WRITER_SCRIPT = "scripts/blog_article_writer.py"
STORY_WRITER_SCRIPT = "scripts/story_writer.py"
SECBLOG_WRITER_SCRIPT = "scripts/secblog_writer.py"
SUBJECT_KEYWORD = "POMERA" # POMERAまたはPOMERAtoKNOWLEDGEを含む件名
ROLE_KEYWORD = "ROLEtoKNOWLEDGE" # 役割定義用キーワード
BLOG_KEYWORD = "BLOG"   # ブログ記事用キーワード
STORY_KEYWORD = "STORY"  # 小説草案用キーワード
SECBLOG_KEYWORD = "SECBLOG" # セキュリティ対話ブログ用キーワード
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

def extract_date_from_subject(subject: str) -> str:
    """件名またはファイル名から日記の日付を抽出して YYYYMMDD 形式で返す。
    
    対応形式:
      - 2026年2月24日  -> 20260224
      - 2026/02/24      -> 20260224
    抽出できない場合はメール受信日（現在日）を返す。
    """
    # 形式: 「2026年2月24日」
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', subject)
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    # 形式: 「2026/02/24」
    m = re.search(r'(\d{4})/(\d{2})/(\d{2})', subject)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    # 形式: 「20260224」など数字8桁の日付
    m = re.search(r'(\d{8})', subject)
    if m:
        return m.group(1)
    # 抽出失敗→メール受信日でfallback
    return datetime.now().strftime('%Y%m%d')
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
        print("🔌 IMAP接続中...")
        import socket
        socket.setdefaulttimeout(30)
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, timeout=30)
        mail.login(EMAIL_ACCOUNT, APP_PASSWORD)
        print("✅ IMAP接続成功")
        return mail
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return None

def check_emails(mail, save_dir, blog_only=False):
    # Load history
    history = set()
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            history = set(line.strip() for line in f if line.strip())
    print(f"📋 処理済みUID: {len(history)} 件")
    if blog_only:
        print("📝 blog_onlyモード: BLOGメールのhistoryチェックをバイパスします")

    status, count = mail.select("inbox")
    if status != "OK" or not count[0]:
        print("❌ inbox選択に失敗")
        return [], [], []

    # 今日の日付でIMAPクエリし、Python側で当日分（過去24時間以内）にフィルタ
    from datetime import timedelta
    today_date = datetime.utcnow().strftime("%d-%b-%Y")
    cutoff_time = datetime.utcnow() - timedelta(hours=24)
    print(f"📅 検索: SINCE {today_date}, 24時間以内のメールのみ処理 (UTC cutoff: {cutoff_time.strftime('%H:%M:%S')})")


    saved_files = []
    blog_files = []
    new_history = []

    # 各キーワードで個別に検索して対象メールだけ取得
    search_targets = [
        (SUBJECT_KEYWORD,  False, False, False, False),   # POMERA
        (BLOG_KEYWORD,     False, True,  False, False),   # BLOG
        (STORY_KEYWORD,    False, False, True,  False),   # STORY
        (SECBLOG_KEYWORD,  False, False, False, True),    # SECBLOG
        (ROLE_KEYWORD,     True,  False, False, False),   # ROLEtoKNOWLEDGE
    ]

    all_target_ids = []
    id_metadata = {}  # e_id -> (is_role, is_blog, is_story, is_secblog)

    for keyword, is_role, is_blog, is_story, is_secblog in search_targets:
        print(f"🔍 検索中: SUBJECT '{keyword}' SINCE {today_date}")
        try:
            status, data = mail.search(None, f'(SINCE {today_date} SUBJECT "{keyword}")')
            if status == "OK" and data[0]:
                ids = data[0].split()
                print(f"   → {len(ids)} 件ヒット")
                for eid in ids:
                    eid_str = eid.decode()
                    if eid_str not in id_metadata:
                        all_target_ids.append(eid)
                        id_metadata[eid_str] = (is_role, is_blog, is_story, is_secblog)
            else:
                print(f"   → 0 件")
        except Exception as e:
            print(f"   ❌ 検索エラー: {e}")

    if not all_target_ids:
        print("💤 対象メールはありません。")
        return [], []

    print(f"📩 IMAP検索ヒット: {len(all_target_ids)} 件 → 10分以内+未処理をフィルタ中...")

    story_files = []
    secblog_files = []
    for e_id_bytes in all_target_ids:
        e_id = e_id_bytes.decode()
        is_role_definition, is_blog_draft, is_story_draft, is_secblog_draft = id_metadata[e_id]
        
        # UID と INTERNALDATE を同時に取得
        try:
            status, data = mail.fetch(e_id, "(UID INTERNALDATE)")
            if not data or not data[0]: continue
            
            resp = data[0].decode() if isinstance(data[0], bytes) else str(data[0])
            
            uid_match = re.search(r'UID (\d+)', resp)
            if not uid_match:
                continue
            uid = uid_match.group(1)
            
            # blog_onlyモードはBLOGメールのhistoryチェックをバイパス
            if uid in history and not (blog_only and is_blog_draft):
                continue
            
            # INTERNALDATE で10分以内かチェック
            date_match = re.search(r'INTERNALDATE "([^"]+)"', resp)
            if date_match:
                date_str = date_match.group(1)
                try:
                    # "17-Feb-2026 15:30:00 +0900" 形式をパース
                    mail_time = datetime.strptime(date_str[:20], "%d-%b-%Y %H:%M:%S")
                    # タイムゾーンオフセットを手動で適用してUTCに変換
                    tz_str = date_str[21:].strip()
                    if tz_str:
                        tz_sign = 1 if tz_str[0] == '+' else -1
                        tz_hours = int(tz_str[1:3])
                        tz_mins = int(tz_str[3:5])
                        mail_time_utc = mail_time - timedelta(hours=tz_sign*tz_hours, minutes=tz_sign*tz_mins)
                    else:
                        mail_time_utc = mail_time
                    
                    if mail_time_utc < cutoff_time:
                        continue
                except Exception:
                    pass  # パース失敗時はフィルタしない
        except Exception as e:
            print(f"   ⚠️ UID/日時取得エラー: {e}")
            continue

        # Fetch subject for filename
        try:
            status, msg_header = mail.fetch(e_id, "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
            subject = ""
            for response_part in msg_header:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    raw_subject = msg["Subject"]
                    if raw_subject:
                        subject = clean_filename(raw_subject)
        except Exception as e:
            print(f"   ⚠️ Subject取得エラー: {e}")
            continue

        if not subject:
            continue

        print(f"👉 Processing: {subject} (Role:{is_role_definition}, Blog:{is_blog_draft}, Story:{is_story_draft}, SecBlog:{is_secblog_draft})")
        
        try:
            status, msg_data = mail.fetch(e_id, "(RFC822)")
        except Exception as e:
            print(f"   ❌ メール本文取得エラー: {e}")
            continue

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
                        filename = f"{extract_date_from_subject(subject)}_{subject}.txt"
                        filepath = os.path.join(blog_dir, filename)
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write(body)
                        blog_files.append(filepath)
                        print(f"      📝 Saved Blog Draft: {filename}")
                        # 処理済みメールを既読にする
                        mail.store(e_id, '+FLAGS', '\\Seen')
                    else:
                        print("      ⚠️ Blog draft email had no body.")
                
                # --- STORY DRAFT HANDLING ---
                elif is_story_draft:
                    body = get_body_content(msg)
                    if body:
                        story_dir = STORY_DRAFTS_DIR
                        if not os.path.exists(story_dir):
                            os.makedirs(story_dir)
                        filename = f"{extract_date_from_subject(subject)}_{subject}.txt"
                        filepath = os.path.join(story_dir, filename)
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write(body)
                        story_files.append(filepath)
                        print(f"      📖 Saved Story Draft: {filename}")
                        mail.store(e_id, '+FLAGS', '\\Seen')
                    else:
                        print("      ⚠️ Story draft email had no body.")

                # --- SECBLOG DRAFT HANDLING ---
                elif is_secblog_draft:
                    body = get_body_content(msg)
                    if body:
                        secblog_dir = SECBLOG_DRAFTS_DIR
                        if not os.path.exists(secblog_dir):
                            os.makedirs(secblog_dir)
                        filename = f"{extract_date_from_subject(subject)}_{subject}.txt"
                        filepath = os.path.join(secblog_dir, filename)
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write(body)
                        secblog_files.append(filepath)
                        print(f"      🔒 Saved SecBlog Draft: {filename}")
                        mail.store(e_id, '+FLAGS', '\\Seen')
                    else:
                        print("      ⚠️ SecBlog draft email had no body.")
                    
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
                            filename = f"{extract_date_from_subject(subject)}_{subject}.txt"
                            filepath = os.path.join(save_dir, filename)
                            # 同日に複数回送信した場合は追記（上書きしない）
                            mode = "a" if os.path.exists(filepath) else "w"
                            with open(filepath, mode, encoding="utf-8") as f:
                                if mode == "a":
                                    f.write("\n\n---\n")
                                f.write(body)
                            saved_files.append(filepath)
                            action = "追記" if mode == "a" else "新規"
                            print(f"      📝 Saved Body ({action}): {filename}")
        
        new_history.append(uid)

    if new_history:
        with open(HISTORY_FILE, "a") as f:
            for uid in new_history:
                f.write(f"{uid}\n")
        print(f"📝 {len(new_history)} 件のUIDをhistoryに追加")

    unique_files = list(dict.fromkeys(saved_files))
    unique_blog_files = list(dict.fromkeys(blog_files))
    unique_story_files = list(dict.fromkeys(story_files))
    unique_secblog_files = list(dict.fromkeys(secblog_files))
    print(f"✅ 完了: 日記 {len(unique_files)} 件, ブログ {len(unique_blog_files)} 件, 小説 {len(unique_story_files)} 件, SecBlog {len(unique_secblog_files)} 件")
    return unique_files, unique_blog_files, unique_story_files, unique_secblog_files

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
    """ブログメモファイルからブログ記事を生成し、はてなブログに投稿する。"""
    if not blog_files: return
    print(f"📝 ブログパイプラインを開始します ({len(blog_files)} 件)...")
    
    for i, file_path in enumerate(blog_files, 1):
        print(f"   [{i}/{len(blog_files)}] Processing Blog Draft: {file_path}")
        cmd = ["python3", BLOG_ARTICLE_WRITER_SCRIPT, file_path]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"   ⚠️ ブログ記事生成失敗: {file_path} (returncode={result.returncode})")
        if i < len(blog_files):
            time.sleep(5)


def run_story_pipeline(story_files):
    """小説草案ファイルからフィクション短編を生成し、はてなブログに投稿する。"""
    if not story_files: return
    print(f"📖 小説パイプラインを開始します ({len(story_files)} 件)...")
    
    for i, file_path in enumerate(story_files, 1):
        print(f"   [{i}/{len(story_files)}] Processing Story Draft: {file_path}")
        cmd = ["python3", STORY_WRITER_SCRIPT, file_path]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"   ⚠️ 小説生成失敗: {file_path} (returncode={result.returncode})")
        if i < len(story_files):
            time.sleep(5)


def run_secblog_pipeline(secblog_files):
    """セキュリティメモから対話形式ブログ記事を生成し、はてなブログに投稿する。"""
    if not secblog_files: return
    print(f"🔒 SecBlogパイプラインを開始します ({len(secblog_files)} 件)...")

    for i, file_path in enumerate(secblog_files, 1):
        print(f"   [{i}/{len(secblog_files)}] Processing SecBlog Draft: {file_path}")
        cmd = ["python3", SECBLOG_WRITER_SCRIPT, file_path]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"   ⚠️ SecBlog記事生成失敗: {file_path} (returncode={result.returncode})")
        if i < len(secblog_files):
            time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description="Sync Pomera emails and trigger analysis.")
    parser.add_argument("--watch", action="store_true", help="Keep watching for new emails.")
    parser.add_argument("--interval", type=int, default=300, help="Check interval in seconds (default: 300s/5min).")
    parser.add_argument("--blog-only", action="store_true", help="Process only BLOG emails.")
    parser.add_argument("--story-only", action="store_true", help="Process only STORY emails.")
    parser.add_argument("--secblog-only", action="store_true", help="Process only SECBLOG emails.")

    args = parser.parse_args()

    if not os.path.exists(LOCAL_DIARY_DIR):
        os.makedirs(LOCAL_DIARY_DIR)
    if not os.path.exists(BLOG_DRAFTS_DIR):
        os.makedirs(BLOG_DRAFTS_DIR)
    if not os.path.exists(STORY_DRAFTS_DIR):
        os.makedirs(STORY_DRAFTS_DIR)
    if not os.path.exists(SECBLOG_DRAFTS_DIR):
        os.makedirs(SECBLOG_DRAFTS_DIR)

    print("📧 Pomera & Role & Blog & Story & SecBlog Email Sync Agent Started")
    print(f"   Account: {EMAIL_ACCOUNT}")
    print(f"   Target Dir: {LOCAL_DIARY_DIR}")
    print(f"   Blog Drafts Dir: {BLOG_DRAFTS_DIR}")
    print(f"   Story Drafts Dir: {STORY_DRAFTS_DIR}")
    print(f"   SecBlog Drafts Dir: {SECBLOG_DRAFTS_DIR}")
    print(f"   Role Definition File: {ROLE_DEF_FILE}")
    print(f"   Blog Only Mode: {args.blog_only}")
    print(f"   Story Only Mode: {args.story_only}")
    print(f"   SecBlog Only Mode: {args.secblog_only}")
    print("   --------------------------------")

    while True:
        mail_conn = connect_imap()
        if mail_conn:
            try:
                new_files, blog_files, story_files, secblog_files = check_emails(mail_conn, LOCAL_DIARY_DIR, blog_only=args.blog_only)

                if args.blog_only:
                    # BLOGモード: ブログパイプラインのみ実行
                    if blog_files:
                        run_blog_pipeline(blog_files)
                    else:
                        print("💤 新着のBLOGメールはありませんでした。")
                elif args.story_only:
                    # STORYモード: 小説パイプラインのみ実行
                    if story_files:
                        run_story_pipeline(story_files)
                    else:
                        print("💤 新着のSTORYメールはありませんでした。")
                elif args.secblog_only:
                    # SECBLOGモード: SecBlogパイプラインのみ実行
                    if secblog_files:
                        run_secblog_pipeline(secblog_files)
                    else:
                        print("💤 新着のSECBLOGメールはありませんでした。")
                else:
                    # 通常モード: 日記分析 + ブログ + 小説 + SecBlogパイプライン
                    if new_files:
                        run_analysis(new_files)
                    if blog_files:
                        run_blog_pipeline(blog_files)
                    if story_files:
                        run_story_pipeline(story_files)
                    if secblog_files:
                        run_secblog_pipeline(secblog_files)
                    if not new_files and not blog_files and not story_files and not secblog_files:
                        if not args.watch:
                            print("💤 新着の対象メールはありませんでした。")

                mail_conn.logout()
            except Exception as e:
                print(f"❌ Error during check: {e}")

        if not args.watch:
            break

        print(f"⏳ 次のチェックまで待機中... ({args.interval}秒)")
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
