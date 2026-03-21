"""
secblog_writer.py — ポメラ草案 → セキュリティ対話形式ブログ記事生成

ポメラで書いたセキュリティに関する拙い考察メモをもとに、
「セキュリティスペシャリスト（専門家AIが演じる）」と「セキュリティ初学者（筆者）」の対話形式ブログ記事を生成する。
生成後、hatena_publisher.py を呼び出してはてなブログに下書き投稿する。
"""

import os
import json
import re
import argparse
import subprocess
from datetime import datetime
import requests
from typing import Dict, Any, Tuple

# 設定
API_KEY = os.getenv("GOOGLE_API_KEY")
BLOG_READY_DIR = "blog_ready"
HATENA_PUBLISHER_SCRIPT = "scripts/hatena_publisher.py"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 対話形式ブログ 生成プロンプト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SECBLOG_SYSTEM_PROMPT = """
# 役割
あなたはセキュリティ分野の専門家であり、教育者です。
ユーザーが書いたセキュリティに関する「拙い考察メモ」をもとに、
**対話形式のブログ記事**を執筆してください。

# 登場人物
- **セキュリティスペシャリスト（あなたが演じる）**: セキュリティ専門家。質問を投げかけ、正しい点を評価し、誤りや認識の浅い点を丁寧に補足し、実際の事例を用いて解説する。威圧的でなく、学習を楽しくするトーンで話す。
- **セキュリティ初学者（筆者）**: セキュリティを学び始めた素直な学習者。拙くても正直な言葉で話す。専門用語を知らなくてもいい。

# 対話の構成ルール
1. **セキュリティスペシャリストが問いを立てる**: 提供された内容から核心的なテーマを2〜3個取り出し、それぞれ独立した「問」として立てる
2. **セキュリティ初学者が答える**: 提供された考えをそのまま口語で表現する（整えすぎない）。2〜3文以上で答える
3. **セキュリティスペシャリストが評価・補足する**: 正しい点を明示した上で、誤りや不足を実際の事例・具体的な攻撃シナリオや実際に起きた被害例・技術的根拠を300〜400字程度で丁寧に補足する。「なるほど、それは的確です」「惜しい！もう少し深めましょう」のようなトーンで
4. **セキュリティスペシャリストが深堀りする**: さらに一段深い問いを投げかけ、対話を2〜3往復続ける。1問につきセキュリティスペシャリスト・セキュリティ初学者が最低2回ずつ発言する
5. **セキュリティスペシャリストがまとめる**: 今日のポイントを箇条書き3〜5点でまとめる

# 文体ルール
- セキュリティスペシャリストの言葉: 親しみやすく、少し逆説的・挑発的な問いかけが良い。「本当にそれだけ？」「それは正しい。では攻撃者の視点から考えると？」
- セキュリティ初学者の言葉: 話し言葉に近い、素直な日本語。整いすぎない。「〜だと思います」「〜ということですよね？」くらいの温度感
- 見出しはテーマの内容をシンプルに表した一文にする。番号形式（「第1問」など）は使わない
- 記事の冒頭に「今日のテーマ」として1〜2行でトピックを紹介する
- 末尾に「今日のまとめ」セクションを置く

# 絶対に守るべきルール
1. セキュリティ初学者（筆者）の言葉は、内容の考えを忠実に反映する。正しくても間違っていても、その時点の認識を大切にする
2. セキュリティスペシャリストは答えを先に言わない。問いを立ててから、セキュリティ初学者の言葉を受けて補足する
3. 専門用語は必ず平易な言葉でフォローする（例: 「XSS、つまりクロスサイトスクリプティングとは〜」）
4. 実際の事例や攻撃手法は具体的に書く（ただし悪用を促す内容は書かない）
5. 記事の冒頭にタイトルは書かない
6. 記事全体を通して「学ぶのが楽しい」という読後感を心がける
7. **メタ表現禁止**: 「メモ」「草案」「書いてくれた内容」「提供された情報によると」など、筆者が事前に何かを書いたことを匂わせる表現は一切使わない。セキュリティ初学者は自分の経験・考えとして自然に語る

# 出力形式
以下のJSON形式で出力してください:

{
  "title": "ブログ記事のタイトル（例: 「XSSってどういう攻撃？」を専門家に聞いてみた）",
  "body": "本文（はてなブログ用Markdown形式）",
  "description": "メタデスクリプション（120文字以内）",
  "categories": ["セキュリティ", "学習記録"],
  "estimated_read_time": "○分"
}

# 文字数・ボリュームの基準
- 本文は必ず2000文字以上3500文字以下にすること
- 各問のセキュリティスペシャリストの補足説明は250〜400文字を目安に書く
- 実際の事例（○○社の情報漏洩事件、ハッカーがよく使う手口など）を最低1件以上、具体的に盛り込む
- 「今日のまとめ」は箇条書き3〜5点で、各点を2〜3文で説明する

言語: 日本語。
JSON以外のテキストは一切含めないでください。
"""

REVIEW_PROMPT = """
あなたはブログの編集者です。以下のセキュリティ対話形式ブログ記事を読み、品質をチェックしてください。

## チェック項目

1. **対話の自然さ**: セキュリティスペシャリストとセキュリティ初学者のやりとりが不自然に噛み合っていない箇所があるか
2. **正確性**: セキュリティに関する明らかな事実誤りがあるか
3. **わかりやすさ**: 専門用語が説明なく登場していないか

## 出力形式
以下のJSON形式で出力してください:

{
  "passed": true/false,
  "issues": [
    {
      "type": "対話の自然さ",
      "detail": "具体的な問題箇所",
      "suggestion": "改善案"
    }
  ]
}

問題がなければ passed を true にし、issues は空配列にしてください。
JSON以外のテキストは一切含めないでください。
"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ユーティリティ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def call_gemini_api(prompt: str, max_retries: int = 3) -> str:
    """Gemini APIを呼び出す。"""
    if not API_KEY:
        raise ValueError("GOOGLE_API_KEY is not set.")

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent"
    params = {"key": API_KEY}
    headers = {"Content-Type": "application/json"}

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"}
    }

    for attempt in range(max_retries + 1):
        response = requests.post(url, headers=headers, json=data, params=params)

        if response.status_code == 200:
            break
        elif response.status_code == 429 and attempt < max_retries:
            wait_time = 30 * (2 ** attempt)
            print(f"⏳ レートリミット到達。{wait_time}秒後にリトライします... ({attempt + 1}/{max_retries})")
            import time
            time.sleep(wait_time)
        else:
            raise Exception(f"API Error: {response.status_code} - {response.text}")

    result = response.json()
    try:
        if "candidates" in result and result["candidates"]:
            return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            raise Exception(f"Empty candidates in response: {result}")
    except (KeyError, IndexError):
        raise Exception(f"Unexpected API response format: {result}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 生成・レビュー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_generation_prompt(memo_text: str) -> str:
    """生成プロンプトを組み立てる。"""
    return f"""
{SECBLOG_SYSTEM_PROMPT}

### 筆者が書いたセキュリティに関するメモ
以下が筆者の拙い考察メモです。これをもとに対話形式の記事を生成してください。
セキュリティ初学者の言葉は、この内容の考えを忠実に反映させてください。

---
{memo_text}
---

### 指示
上記のメモをもとに、対話形式のブログ記事を1本執筆してください。
メモの内容がたとえ不正確であっても、それが「現時点での筆者の考え」として記事に生かされるようにしてください。
セキュリティスペシャリストが正確な情報や事例で補足することで、読者も一緒に学べる記事にしてください。
"""


def review_article(article_body: str) -> Tuple[bool, list]:
    """生成された記事をレビューする。"""
    prompt = f"""
{REVIEW_PROMPT}

### レビュー対象の記事
{article_body}
"""
    print("🔍 品質レビュー中...")
    json_text = call_gemini_api(prompt)
    result = json.loads(json_text)
    passed = result.get("passed", True)
    issues = result.get("issues", [])

    if issues:
        for issue in issues:
            print(f"   ⚠️ [{issue.get('type', '不明')}] {issue.get('detail', '')}")
    else:
        print("   ✅ 品質チェック合格")

    return passed, issues


def generate_secblog_article(memo_text: str, max_revisions: int = 1) -> Dict[str, Any]:
    """メモから対話形式のセキュリティブログ記事を生成する。"""
    prompt = build_generation_prompt(memo_text)
    print("📝 セキュリティ対話記事を生成中...")
    json_text = call_gemini_api(prompt)
    article_data = json.loads(json_text)

    for revision in range(max_revisions):
        article_body = article_data.get("body", "")
        if not article_body:
            break

        passed, issues = review_article(article_body)

        if passed:
            break

        feedback_lines = []
        for issue in issues:
            feedback_lines.append(
                f"- [{issue.get('type', '')}] {issue.get('detail', '')}\n"
                f"  改善案: {issue.get('suggestion', '')}"
            )
        feedback_section = "\n".join(feedback_lines)

        revision_prompt = f"""
{SECBLOG_SYSTEM_PROMPT}

{build_generation_prompt(memo_text)}

### 前回の生成結果に対するレビューフィードバック
以下の問題が指摘されました。これらを全て修正した上で、記事を書き直してください。

{feedback_section}

### 前回の本文（参考）
{article_body[:1000]}...

### 指示
上記のフィードバックを反映し、問題を修正した新しいバージョンの記事を執筆してください。
"""
        print(f"📝 フィードバック反映版を生成中... (リビジョン {revision + 1}/{max_revisions})")
        json_text = call_gemini_api(revision_prompt)
        article_data = json.loads(json_text)

    return article_data


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 保存・投稿
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_article(article_data: Dict[str, Any], source_file: str) -> tuple:
    """生成された記事をファイルに保存する。"""
    if not os.path.exists(BLOG_READY_DIR):
        os.makedirs(BLOG_READY_DIR)

    date_str = datetime.now().strftime('%Y%m%d')
    title = article_data.get("title", "無題")

    safe_title = re.sub(r'[\\/*?"<>|]', '', title)[:50]

    md_filename = f"{date_str}_{safe_title}.md"
    md_path = os.path.join(BLOG_READY_DIR, md_filename)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(article_data.get("body", ""))

    meta_filename = f"{date_str}_{safe_title}.json"
    meta_path = os.path.join(BLOG_READY_DIR, meta_filename)

    meta = {
        "title": title,
        "description": article_data.get("description", ""),
        "categories": article_data.get("categories", ["セキュリティ", "学習記録"]),
        "estimated_read_time": article_data.get("estimated_read_time", ""),
        "source_file": source_file,
        "generated_at": datetime.now().isoformat(),
        "type": "secblog_article"
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"✅ 記事を保存しました: {md_path}")
    print(f"✅ メタデータを保存しました: {meta_path}")

    return md_path, meta_path


def publish_to_hatena(md_path: str, meta_path: str):
    """はてなブログに下書き投稿する。"""
    cmd = ["python3", HATENA_PUBLISHER_SCRIPT, md_path, "--meta", meta_path, "--force"]
    print("🚀 はてなブログへの投稿を開始...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"⚠️ はてなブログへの投稿に失敗しました (returncode={result.returncode})")
    else:
        print("✅ はてなブログへの投稿が完了しました")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メインフロー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(description="ポメラセキュリティメモ → 対話形式ブログ記事 → はてなブログ投稿")
    parser.add_argument("input_file", help="メモテキストファイルのパス")
    parser.add_argument("--skip-publish", action="store_true", help="はてなブログへの投稿をスキップ")

    args = parser.parse_args()

    try:
        import unicodedata
        args.input_file = unicodedata.normalize('NFC', args.input_file)
        with open(args.input_file, "r", encoding="utf-8") as f:
            memo_text = f.read()
    except FileNotFoundError:
        print(f"❌ ファイルが見つかりません: {args.input_file}")
        return

    if not memo_text.strip():
        print("❌ メモが空です。")
        return

    print(f"📄 セキュリティメモを読み込みました: {args.input_file}")
    print(f"   文字数: {len(memo_text)}")

    try:
        article_data = generate_secblog_article(memo_text)
        print(f"✨ 記事生成完了: 「{article_data.get('title', '無題')}」")
    except Exception as e:
        print(f"❌ 記事生成中にエラー: {e}")
        return

    md_path, meta_path = save_article(article_data, args.input_file)

    if not args.skip_publish:
        publish_to_hatena(md_path, meta_path)
    else:
        print("⏭️ はてなブログへの投稿はスキップされました")


if __name__ == "__main__":
    main()
