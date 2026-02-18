"""
social_promoter.py — ブログ記事の自動拡散

はてなブログに投稿された記事を、にほんブログ村へ自動でping送信する。
GitHub Actionsパイプラインの一部として、記事投稿後に自動実行される。
"""

import os
import json
import argparse
import xmlrpc.client
import datetime
from typing import Optional


# 設定
BLOG_NAME = "１話完結型ショートストーリー"
BLOG_URL = "https://kakikukekoichi.hatenablog.com"
BLOGMURA_PING_URL = os.getenv(
    "BLOGMURA_PING_URL",
    "https://ping.blogmura.com/xmlrpc/7d5erbtdg9mu/"
)
BLOG_PUBLISHED_DIR = "blog_published"
PROMOTION_HISTORY_FILE = os.path.join(BLOG_PUBLISHED_DIR, "promotion_history.json")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# にほんブログ村 ping送信
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def send_blogmura_ping(blog_name: str, blog_url: str, article_url: str = "", dry_run: bool = False) -> bool:
    """にほんブログ村にXML-RPC pingを送信する。"""
    ping_url = BLOGMURA_PING_URL

    if dry_run:
        print(f"🔍 ドライラン: にほんブログ村へのping送信をシミュレート")
        print(f"   送信先: {ping_url}")
        print(f"   ブログ名: {blog_name}")
        print(f"   ブログURL: {blog_url}")
        if article_url:
            print(f"   記事URL: {article_url}")
        return True

    try:
        server = xmlrpc.client.ServerProxy(ping_url)

        # 拡張ping: 記事URLも送信
        if article_url:
            result = server.weblogUpdates.extendedPing(
                blog_name,
                blog_url,
                article_url,
                f"{blog_url}/feed"
            )
        else:
            result = server.weblogUpdates.ping(blog_name, blog_url)

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

def promote_from_publish_history(dry_run: bool = False, force: bool = False) -> int:
    """publish_history.jsonから未拡散の記事を自動で拡散する。"""
    publish_history_path = os.path.join(BLOG_PUBLISHED_DIR, "publish_history.json")

    if not os.path.exists(publish_history_path):
        print("💤 投稿履歴がありません")
        return 0

    try:
        with open(publish_history_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception as e:
        print(f"❌ 投稿履歴の読み込みに失敗: {e}")
        return 0

    promoted_count = 0

    for entry in entries:
        article_url = entry.get("url", "")
        title = entry.get("title", "無題")

        if not article_url:
            print(f"⚠️ URLが空の記事をスキップ: {title}")
            continue

        if not force and is_already_promoted(article_url):
            print(f"⏭️ 拡散済みの記事をスキップ: {title}")
            continue

        print(f"\n📢 拡散開始: {title}")
        print(f"   URL: {article_url}")

        results = {}

        # にほんブログ村へping送信
        blogmura_ok = send_blogmura_ping(
            BLOG_NAME,
            BLOG_URL,
            article_url,
            dry_run=dry_run
        )
        results["blogmura"] = "success" if blogmura_ok else "failed"

        # 履歴記録
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
        BLOG_NAME,
        BLOG_URL,
        article_url,
        dry_run=dry_run
    )
    results["blogmura"] = "success" if blogmura_ok else "failed"

    if not dry_run:
        record_promotion(article_url, title, results)

    return blogmura_ok


def main():
    parser = argparse.ArgumentParser(
        description="ブログ記事をSNS/コミュニティに自動拡散する"
    )
    parser.add_argument(
        "--url",
        help="拡散する記事のURL。省略時はpublish_history.jsonから自動検出"
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
        # 単一記事の拡散
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
        # publish_history.jsonから自動拡散
        count = promote_from_publish_history(
            dry_run=args.dry_run,
            force=args.force
        )
        if count > 0:
            print(f"\n✅ {count}件の記事を拡散しました！")
        else:
            print("\n💤 拡散対象の記事がありませんでした")


if __name__ == "__main__":
    main()
