"""
hatena_publisher.py — はてなブログ AtomPub API 投稿（セキュリティブログ用）

セキュリティ記事をはてなブログに下書きとして投稿する。
通常のBLOGとは別のブログIDを使用する。
  環境変数 HATENA_SECURITY_BLOG_ID でセキュリティブログのIDを指定する。
  未設定の場合は HATENA_BLOG_ID にフォールバックする。
"""

import os
import hashlib
import base64
import datetime
import random
import string
import re
from typing import Optional
import requests

HATENA_ID = os.getenv("HATENA_ID", "kakikukekoichi")
HATENA_BLOG_ID = os.getenv(
    "HATENA_SECURITY_BLOG_ID",
    os.getenv("HATENA_BLOG_ID", "kakikukekoichi.hatenablog.com")
)
HATENA_API_KEY = os.getenv("HATENA_API_KEY")


def generate_wsse_header(username: str, api_key: str) -> str:
    """WSSE認証ヘッダーを生成する。"""
    nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=40))
    nonce_bytes = nonce.encode('utf-8')
    created = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    digest_input = nonce_bytes + created.encode('utf-8') + api_key.encode('utf-8')
    password_digest = base64.b64encode(hashlib.sha1(digest_input).digest()).decode('utf-8')
    nonce_b64 = base64.b64encode(nonce_bytes).decode('utf-8')

    return (
        f'UsernameToken Username="{username}", '
        f'PasswordDigest="{password_digest}", '
        f'Nonce="{nonce_b64}", '
        f'Created="{created}"'
    )


def create_entry_xml(title: str, content: str, categories: list = None, draft: bool = True) -> str:
    """AtomPub形式のXMLエントリーを作成する。"""
    category_xml = ""
    if categories:
        for cat in categories:
            category_xml += f'  <category term="{cat}" />\n'

    draft_value = "yes" if draft else "no"

    content_escaped = (content
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;"))

    return f"""<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom"
       xmlns:app="http://www.w3.org/2007/app">
  <title>{title}</title>
  <author><name>{HATENA_ID}</name></author>
  <content type="text/x-markdown">{content_escaped}</content>
{category_xml}  <app:control>
    <app:draft>{draft_value}</app:draft>
  </app:control>
</entry>"""


def post_to_hatena(title: str, content: str, categories: list = None, draft: bool = True) -> Optional[dict]:
    """はてなブログ（セキュリティブログ）に記事を投稿する。"""
    if not HATENA_API_KEY:
        print("❌ HATENA_API_KEY が設定されていません。")
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
            print(f"✅ セキュリティブログ投稿成功！ ({'下書き' if draft else '公開'})")
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
    match = re.search(r'<link rel="alternate"[^>]*href="([^"]+)"', xml_text)
    if match:
        return match.group(1)
    return ""
