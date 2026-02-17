"""
hatena_publisher.py — はてなブログ AtomPub API 投稿

生成されたブログ記事をはてなブログに下書きとして投稿する。
WSSE認証を使用し、AtomPub APIで記事を投稿する。
"""

import os
import json
import argparse
import hashlib
import base64
import datetime
import random
import string
from typing import Optional
import requests

# 設定
HATENA_ID = os.getenv("HATENA_ID", "kakikukekoichi")
HATENA_BLOG_ID = os.getenv("HATENA_BLOG_ID", "kakikukekoichi.hatenablog.com")
HATENA_API_KEY = os.getenv("HATENA_API_KEY")
BLOG_PUBLISHED_DIR = "blog_published"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WSSE認証
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_wsse_header(username: str, api_key: str) -> str:
    """WSSE認証ヘッダーを生成する。"""
    nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=40))
    nonce_bytes = nonce.encode('utf-8')
    created = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    # PasswordDigest = Base64(SHA1(Nonce + Created + Password))
    digest_input = nonce_bytes + created.encode('utf-8') + api_key.encode('utf-8')
    password_digest = base64.b64encode(hashlib.sha1(digest_input).digest()).decode('utf-8')
    nonce_b64 = base64.b64encode(nonce_bytes).decode('utf-8')
    
    return (
        f'UsernameToken Username="{username}", '
        f'PasswordDigest="{password_digest}", '
        f'Nonce="{nonce_b64}", '
        f'Created="{created}"'
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# はてなブログ投稿
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def create_entry_xml(title: str, content: str, categories: list = None, draft: bool = True) -> str:
    """AtomPub形式のXMLエントリーを作成する。"""
    # カテゴリタグの生成
    category_xml = ""
    if categories:
        for cat in categories:
            category_xml += f'  <category term="{cat}" />\n'
    
    # 下書きフラグ
    draft_value = "yes" if draft else "no"
    
    # コンテンツのXMLエスケープ
    content_escaped = (content
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;"))
    
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom"
       xmlns:app="http://www.w3.org/2007/app">
  <title>{title}</title>
  <author><name>{HATENA_ID}</name></author>
  <content type="text/x-markdown">{content_escaped}</content>
{category_xml}  <app:control>
    <app:draft>{draft_value}</app:draft>
  </app:control>
</entry>"""
    
    return xml


def post_to_hatena(title: str, content: str, categories: list = None, draft: bool = True) -> Optional[dict]:
    """はてなブログに記事を投稿する。"""
    if not HATENA_API_KEY:
        print("❌ HATENA_API_KEY が設定されていません。")
        print("   GitHub Secretsまたは環境変数に HATENA_API_KEY を設定してください。")
        return None
    
    endpoint = f"https://blog.hatena.ne.jp/{HATENA_ID}/{HATENA_BLOG_ID}/atom/entry"
    
    wsse = generate_wsse_header(HATENA_ID, HATENA_API_KEY)
    headers = {
        "X-WSSE": wsse,
        "Content-Type": "application/xml",
        "Accept": "application/xml"
    }
    
    xml_body = create_entry_xml(title, content, categories, draft)
    
    try:
        response = requests.post(endpoint, headers=headers, data=xml_body.encode('utf-8'))
        
        if response.status_code == 201:
            print(f"✅ 投稿成功！ ({'下書き' if draft else '公開'})")
            
            # レスポンスからURLを抽出
            entry_url = extract_url_from_response(response.text)
            return {
                "status": "success",
                "draft": draft,
                "url": entry_url,
                "title": title
            }
        else:
            print(f"❌ 投稿失敗: {response.status_code}")
            print(f"   レスポンス: {response.text[:500]}")
            return None
            
    except Exception as e:
        print(f"❌ 投稿中にエラー: {e}")
        return None


def extract_url_from_response(xml_text: str) -> str:
    """レスポンスXMLから記事URLを抽出する。"""
    import re
    # alternate linkを探す
    match = re.search(r'<link rel="alternate"[^>]*href="([^"]+)"', xml_text)
    if match:
        return match.group(1)
    return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 公開履歴管理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def is_already_published(source_file: str) -> bool:
    """同じソースファイルから既に投稿済みかチェックする。"""
    history_path = os.path.join(BLOG_PUBLISHED_DIR, "publish_history.json")
    if not os.path.exists(history_path):
        return False
    
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
        return source_file in [h.get("source_file") for h in history]
    except Exception:
        return False


def record_publication(result: dict, source_file: str):
    """投稿履歴を記録する。"""
    if not os.path.exists(BLOG_PUBLISHED_DIR):
        os.makedirs(BLOG_PUBLISHED_DIR)
    
    history_path = os.path.join(BLOG_PUBLISHED_DIR, "publish_history.json")
    history = []
    
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    
    history.append({
        "title": result.get("title", ""),
        "url": result.get("url", ""),
        "draft": result.get("draft", True),
        "source_file": source_file,
        "published_at": datetime.datetime.now().isoformat()
    })
    
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    
    print(f"📋 投稿履歴を記録しました: {history_path}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メインフロー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(description="はてなブログに記事を投稿する")
    parser.add_argument("input_file", help="投稿するMarkdownファイルのパス")
    parser.add_argument("--meta", help="メタデータJSONファイルのパス")
    parser.add_argument("--publish", action="store_true", help="下書きではなく公開として投稿")
    parser.add_argument("--force", action="store_true", help="既に投稿済みでも強制的に再投稿")
    
    args = parser.parse_args()
    
    # 1. 記事本文の読み込み
    try:
        with open(args.input_file, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"❌ ファイルが見つかりません: {args.input_file}")
        return
    
    # 2. メタデータの読み込み
    title = "無題"
    categories = []
    source_file = args.input_file
    
    if args.meta:
        try:
            with open(args.meta, "r", encoding="utf-8") as f:
                meta = json.load(f)
            title = meta.get("title", "無題")
            categories = meta.get("categories", [])
            source_file = meta.get("source_file", args.input_file)
        except Exception as e:
            print(f"⚠️ メタデータの読み込みに失敗: {e}")
    
    # 3. 二重投稿チェック
    if not args.force and is_already_published(source_file):
        print(f"⚠️ この草案は既に投稿済みです: {source_file}")
        print("   再投稿するには --force オプションを使用してください。")
        return
    
    # 4. 投稿
    draft = not args.publish
    print(f"📝 投稿準備:")
    print(f"   タイトル: {title}")
    print(f"   カテゴリ: {', '.join(categories) if categories else 'なし'}")
    print(f"   モード: {'下書き' if draft else '公開'}")
    print(f"   文字数: {len(content)}")
    
    result = post_to_hatena(title, content, categories, draft)
    
    if result:
        record_publication(result, source_file)
        if result.get("url"):
            print(f"🔗 記事URL: {result['url']}")


if __name__ == "__main__":
    main()
