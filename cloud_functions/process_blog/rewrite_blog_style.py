"""
rewrite_blog_style.py — 既存ブログ記事を文体ガイドに従い書き換えるバッチスクリプト

blog_ready/ 内の全ブログ記事 (.md) を reading style.md に従い
Gemini APIで書き換えて上書き保存する。
"""

import os
import json
import time
import requests
from typing import Optional

API_KEY = os.getenv("GOOGLE_API_KEY")
BLOG_READY_DIR = "blog_ready"
WRITING_STYLE_PATH = "writing_style.md"

REWRITE_SYSTEM_PROMPT = """
# 役割
あなたは筆者本人の代わりに記事を書き直すライターです。
既存のブログ記事を「文体ガイド」に従い、筆者の言葉に書き換えてください。

# 最重要ルール
- 内容・情報・構成はそのまま保つ。変えるのは文体・語調のみ
- 文体ガイドを最優先で守ること
- マークダウンの見出し構造はできる限り維持する
- 文章量は元記事とほぼ同程度を保つ

# 絶対に使わない表現
- 「〜いかがでしたか？」
- 「〜ではないでしょうか」
- 「〜してみてはどうだろうか」
- 「〜してくれるはずだ」
- キャッチコピー的な比喩（例：「情報のカクテル状態」「超有能な秘書」）
- 「〜してほしい」で読者に訴えかける締め方

# 語尾のルール
- 「〜のだ」「〜なのだ」「〜たいのだ」を積極的に使う
- 「〜と思っている」「〜と考えている」で自分の考えを語る
- 「なんというか」「だからこそ」「そのうえで」などの口語的な繋ぎ言葉を自然に使う

# 出力
書き換えた記事本文のみを出力してください。
JSONや説明文は不要です。マークダウン形式のテキストのみ出力してください。
"""


def call_gemini_api(prompt: str, max_retries: int = 3) -> str:
    """Gemini APIを呼び出す。"""
    if not API_KEY:
        raise ValueError("GOOGLE_API_KEY is not set.")

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    params = {"key": API_KEY}
    headers = {"Content-Type": "application/json"}

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7}
    }

    for attempt in range(max_retries + 1):
        response = requests.post(url, headers=headers, json=data, params=params)
        if response.status_code == 200:
            break
        elif response.status_code == 429 and attempt < max_retries:
            wait_time = 30 * (2 ** attempt)
            print(f"⏳ レートリミット到達。{wait_time}秒後にリトライ... ({attempt + 1}/{max_retries})")
            time.sleep(wait_time)
        else:
            raise Exception(f"API Error: {response.status_code} - {response.text[:200]}")

    result = response.json()
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise Exception(f"Unexpected API response format: {result}")


def load_writing_style() -> str:
    """文体ガイドを読み込む。"""
    if not os.path.exists(WRITING_STYLE_PATH):
        print("⚠️ writing_style.md が見つかりません")
        return ""
    with open(WRITING_STYLE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def is_blog_article(json_path: str) -> bool:
    """JSONメタデータからブログ記事かどうか判定する。"""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # typeがblog_articleであること、または短編小説でないこと
        if data.get("type") == "blog_article":
            return True
        if "短編小説" in data.get("categories", []):
            return False
        return True
    except Exception:
        return False


def rewrite_article(md_content: str, style_guide: str) -> str:
    """記事を文体ガイドに従い書き換える。"""
    prompt = f"""{REWRITE_SYSTEM_PROMPT}

### 文体ガイド（最優先で従うこと）
{style_guide}

### 書き換え対象の記事
{md_content}

### 指示
上記の記事を、文体ガイドに従い筆者の言葉で書き直してください。
内容・情報・見出し構造は保ちつつ、文体・語調のみを変えてください。
マークダウン形式で本文のみ出力してください。
"""
    return call_gemini_api(prompt)


def main():
    style_guide = load_writing_style()
    if not style_guide:
        print("❌ 文体ガイドがないと書き換えできません")
        return

    # blog_ready/ 内のブログ記事を列挙
    targets = []
    for f in sorted(os.listdir(BLOG_READY_DIR)):
        if not f.endswith(".md") or f in [".gitkeep", "gravity_analysis_mechanism.md"]:
            continue
        md_path = os.path.join(BLOG_READY_DIR, f)
        json_path = md_path.replace(".md", ".json")

        # JSONがあればブログ記事か確認、なければスキップ
        if os.path.exists(json_path):
            if not is_blog_article(json_path):
                print(f"⏭️ スキップ（小説）: {f}")
                continue
        else:
            print(f"⏭️ スキップ（JSONなし）: {f}")
            continue

        targets.append((md_path, json_path))

    print(f"📝 書き換え対象: {len(targets)}件")
    print()

    rewritten = []
    for i, (md_path, json_path) in enumerate(targets, 1):
        filename = os.path.basename(md_path)
        print(f"[{i}/{len(targets)}] 書き換え中: {filename}")

        with open(md_path, "r", encoding="utf-8") as f:
            original = f.read()

        try:
            rewritten_text = rewrite_article(original, style_guide)

            # マークダウンコードブロックが含まれていたら除去
            if rewritten_text.startswith("```"):
                lines = rewritten_text.split("\n")
                lines = [l for l in lines if not l.startswith("```")]
                rewritten_text = "\n".join(lines).strip()

            # 上書き保存
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(rewritten_text)

            rewritten.append(filename)
            print(f"  ✅ 完了 ({len(rewritten_text)}文字)")

        except Exception as e:
            print(f"  ❌ エラー: {e}")

        # レートリミット対策
        if i < len(targets):
            time.sleep(3)

    print()
    print(f"✨ 書き換え完了: {len(rewritten)}/{len(targets)}件")


if __name__ == "__main__":
    main()
