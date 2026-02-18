"""
social_promoter.py — ブログ記事の自動拡散

はてなブログのRSSフィードを監視し、新しく公開された記事を検出して
にほんブログ村へ自動でping送信する。

使い方:
  python social_promoter.py              # RSSから新着記事を検出してping送信
  python social_promoter.py --dry-run    # 実際の送信はせずプレビュー
  python social_promoter.py --url URL    # 特定の記事URLを指定してping送信
"""

import os
import json
import argparse
import xmlrpc.client
import urllib.request
import datetime
import xml.etree.ElementTree as ET
from typing import Optional


# 設定
BLOG_NAME = "１話完結型ショートストーリー"
BLOG_URL = "https://kakikukekoichi.hatenablog.com"
BLOG_FEED_URL = f"{BLOG_URL}/feed"
BLOGMURA_PING_URL = os.getenv(
    "BLOGMURA_PING_URL",
    "https://ping.blogmura.com/xmlrpc/7d5erbtdg9mu/"
)
BLOG_PUBLISHED_DIR = "blog_published"
PROMOTION_HISTORY_FILE = os.path.join(BLOG_PUBLISHED_DIR, "promotion_history.json")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RSS フィード監視
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_rss_entries(feed_url: str, max_entries: int = 10) -> list:
    """はてなブログのAtomフィードから最新記事を取得する。"""
    try:
        req = urllib.request.Request(feed_url, headers={
            "User-Agent": "PomeraToKnowledge-Promoter/1.0"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_text = resp.read().decode("utf-8")

        root = ET.fromstring(xml_text)

        # Atom名前空間
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = []

        for entry in root.findall("atom:entry", ns)[:max_entries]:
            title_el = entry.find("atom:title", ns)
            title = title_el.text if title_el is not None else "無題"

            # 記事URLを取得
            # はてなブログのAtomフィードではrelが省略されることがある
            url = ""
            for link in entry.findall("atom:link", ns):
                rel = link.get("rel")
                link_type = link.get("type")
                href = link.get("href", "")
                # alternate、またはrel/type未指定で記事URLらしいもの
                if rel == "alternate" or (rel is None and link_type is None and href):
                    url = href
                    break

            published_el = entry.find("atom:published", ns)
            published = published_el.text if published_el is not None else ""

            entries.append({
                "title": title,
                "url": url,
                "published": published
            })

        print(f"📡 RSSフィードから{len(entries)}件の記事を取得")
        return entries

    except Exception as e:
        print(f"❌ RSSフィードの取得に失敗: {e}")
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# にほんブログ村 ping送信
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def send_blogmura_ping(article_url: str = "", dry_run: bool = False) -> bool:
    """にほんブログ村にXML-RPC pingを送信する。"""
    ping_url = BLOGMURA_PING_URL

    if dry_run:
        print(f"🔍 ドライラン: にほんブログ村へのping送信をシミュレート")
        print(f"   送信先: {ping_url}")
        print(f"   ブログ名: {BLOG_NAME}")
        print(f"   ブログURL: {BLOG_URL}")
        if article_url:
            print(f"   記事URL: {article_url}")
        return True

    try:
        server = xmlrpc.client.ServerProxy(ping_url)

        # 拡張ping: 記事URLも送信
        if article_url:
            result = server.weblogUpdates.extendedPing(
                BLOG_NAME,
                BLOG_URL,
                article_url,
                BLOG_FEED_URL
            )
        else:
            result = server.weblogUpdates.ping(BLOG_NAME, BLOG_URL)

        # レスポンス解析
        if hasattr(result, "get"):
            error = result.get("flerror", False)
            message = result.get("message", "")
        else:
            error = False
            message = str(result)

        if error:
            print(f"⚠️ にほんブログ村 ping応答にエラー: {message}")
            return False
        else:
            print(f"✅ にほんブログ村へのping送信成功！")
            if message:
                print(f"   応答: {message}")
            return True

    except Exception as e:
        print(f"❌ にほんブログ村へのping送信に失敗: {e}")
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 拡散履歴管理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_promotion_history() -> list:
    """拡散履歴を読み込む。"""
    if not os.path.exists(PROMOTION_HISTORY_FILE):
        return []
    try:
        with open(PROMOTION_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def is_already_promoted(article_url: str) -> bool:
    """同じ記事が既に拡散済みかチェックする。"""
    history = load_promotion_history()
    return any(h.get("article_url") == article_url for h in history)


def record_promotion(article_url: str, title: str, results: dict):
    """拡散履歴を記録する。"""
    if not os.path.exists(BLOG_PUBLISHED_DIR):
        os.makedirs(BLOG_PUBLISHED_DIR)

    history = load_promotion_history()
    history.append({
        "article_url": article_url,
        "title": title,
        "promoted_at": datetime.datetime.now().isoformat(),
        "results": results
    })

    with open(PROMOTION_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"📋 拡散履歴を記録しました")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メインフロー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def promote_from_rss(dry_run: bool = False, force: bool = False) -> int:
    """RSSフィードから新着記事を検出してpingを送信する。"""
    entries = fetch_rss_entries(BLOG_FEED_URL)

    if not entries:
        print("💤 RSSフィードに記事がありません")
        return 0

    promoted_count = 0

    for entry in entries:
        article_url = entry.get("url", "")
        title = entry.get("title", "無題")

        if not article_url:
            continue

        if not force and is_already_promoted(article_url):
            continue

        print(f"\n📢 新着記事を検出: {title}")
        print(f"   URL: {article_url}")

        results = {}

        blogmura_ok = send_blogmura_ping(
            article_url=article_url,
            dry_run=dry_run
        )
        results["blogmura"] = "success" if blogmura_ok else "failed"

        if not dry_run:
            record_promotion(article_url, title, results)

        promoted_count += 1

    return promoted_count


def promote_single(article_url: str, title: str = "", dry_run: bool = False) -> bool:
    """単一の記事URLを指定して拡散する。"""
    if not title:
        title = "新着記事"

    print(f"\n📢 拡散開始: {title}")
    print(f"   URL: {article_url}")

    results = {}

    blogmura_ok = send_blogmura_ping(
        article_url=article_url,
        dry_run=dry_run
    )
    results["blogmura"] = "success" if blogmura_ok else "failed"

    if not dry_run:
        record_promotion(article_url, title, results)

    return blogmura_ok


def main():
    parser = argparse.ArgumentParser(
        description="ブログ記事をにほんブログ村に自動拡散する"
    )
    parser.add_argument(
        "--url",
        help="拡散する記事のURL。省略時はRSSフィードから新着を自動検出"
    )
    parser.add_argument(
        "--title",
        default="",
        help="記事のタイトル"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際には送信せず、内容をプレビューするだけ"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="拡散済みの記事でも強制的に再拡散する"
    )

    args = parser.parse_args()

    print("=" * 50)
    print("📡 ブログ自動拡散スクリプト")
    print("=" * 50)

    if args.dry_run:
        print("🔍 ドライランモード: 実際の送信は行いません\n")

    if args.url:
        success = promote_single(
            args.url,
            title=args.title,
            dry_run=args.dry_run
        )
        if success:
            print("\n✅ 拡散完了！")
        else:
            print("\n❌ 拡散に失敗しました")
    else:
        count = promote_from_rss(
            dry_run=args.dry_run,
            force=args.force
        )
        if count > 0:
            print(f"\n✅ {count}件の記事を拡散しました！")
        else:
            print("\n💤 新たに拡散する記事はありませんでした")


if __name__ == "__main__":
    main()
