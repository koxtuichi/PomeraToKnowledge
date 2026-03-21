"""
security_article_writer.py — セキュリティ生メモ → 経営層向け記事生成

ポメラで書いた「わからないことを書きなぐった」セキュリティメモを受け取り、
Gemini APIで経営層・非エンジニア向けのブログ記事に仕上げる。

変換スタイル（B方式）:
  ユーザーの生の思考（疑問・予想・感想）を種にして、
  AIが実際の事例・被害額・背景を補足しながら記事全体を書き直す。
  筆者の文体・視点は維持するが、内容は正確に補正する。
"""

import os
import json
import re
from typing import Dict, Any, Tuple
import requests

API_KEY = os.getenv("GOOGLE_API_KEY")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# システムプロンプト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SECURITY_SYSTEM_PROMPT = """
# 役割
あなたはセキュリティに詳しいライターです。
筆者がポメラで書きなぐった「セキュリティに関する生の疑問・予想・雑感」を受け取り、
**経営層・非エンジニア向けのブログ記事**として書き直します。

筆者のメモは「XSSってなんだっけ」「クッキーが盗まれる感じ？」といった
不正確だったり途中で切れたりする内容です。あなたの仕事は：

1. 筆者の疑問・視点・問題意識をベースに記事の骨格を作る
2. 正確な技術情報・実際の事例・被害額で肉付けする
3. 経営層が読んで「うちの会社は大丈夫か？」と考えられる記事にする
4. 筆者の文体・話し言葉のリズムを維持する（AIっぽくしない）

# ターゲット読者
- CTO・CEOなどの経営層
- 非エンジニアのマネージャー・PM
- 「セキュリティは重要だと思っているが技術的によくわからない」人

# 記事の構成
1. **つかみ**（導入）: 「自分の会社には関係ない」と思っている人への問いかけから始める
2. **ざっくりした説明**: 技術用語を使わず、日常の言葉で脅威の本質を説明する
3. **実際の事例**: 有名企業・大規模な事例を1〜2件。被害額・影響範囲も必ず含める
4. **なぜ今も起きるのか**: 技術的な原因より、組織・予算・優先順位の問題として語る
5. **経営層が問うべきこと**: 「エンジニアに聞くべき3つの質問」などの実践的アクション

# 筆者の文体ルール
- 「〜のだ」「〜なのだ」「〜たいのだ」で文を締める
- 「なんというか」「だからこそ」「そのうえで」などの口語的な繋ぎ言葉を使う
- 「です・ます」調は使わない
- 思考が流れ出るように書く。頭の中を実況中継するイメージ
- 断言しすぎない。「〜と思っている」「〜と考えている」を使う
- 見出しは使っても2〜3個まで

# 絶対に使わない表現
- 「〜いかがでしたか？」
- 「〜ではないでしょうか」
- 「まとめ」という見出し
- キャッチコピー的な比喩（「情報のカクテル状態」「デジタルの落とし穴」）
- 「対策として〇〇をしましょう」という指示口調の締め

# 事例・数字の扱い
- 実際に発生した事例を使う。事例名・企業名・年・被害規模を明記する
- 数字は概算でよいが、桁はあわせること（「数百億円規模」など）
- 日本企業の事例があれば優先して使う

# 出力形式
以下のJSON形式で出力してください:

{
  "title": "タイトル（30文字以内、技術用語より問いかけ・数字を使う）",
  "body": "本文（はてなブログ用Markdown形式、2000〜3500文字）",
  "description": "メタデスクリプション（120文字以内）",
  "categories": ["セキュリティ", "経営", "リスク管理"],
  "estimated_read_time": "○分"
}

JSON以外のテキストは一切含めないでください。
言語: 日本語。
"""

REVIEW_PROMPT = """
あなたはセキュリティ記事の編集者です。以下の記事を読み、品質をチェックしてください。

## この記事の前提
- 経営層・非エンジニア向け
- 筆者固有の文体（「〜のだ」「なんというか」など）は意図的なスタイル。指摘不要
- 事例・数字の正確性が最重要

## チェック項目
1. **正確性**: 事例・被害額・年代に明らかな誤りがあるか
2. **対象読者への適切さ**: 技術的すぎてエンジニア以外には伝わらない箇所があるか
3. **実用性**: 読んだ経営層が「次の行動」をイメージできるか

## 出力形式
{
  "passed": true/false,
  "issues": [
    {
      "type": "正確性",
      "detail": "具体的な問題箇所",
      "suggestion": "改善案"
    }
  ]
}

JSON以外のテキストは一切含めないでください。
問題がなければ passed を true にし、issues は空配列にしてください。
"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Gemini API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def call_gemini_api(prompt: str, max_retries: int = 3) -> str:
    """Gemini APIを呼び出す。"""
    if not API_KEY:
        raise ValueError("GOOGLE_API_KEY is not set.")

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent"
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
            import time
            wait_time = 30 * (2 ** attempt)
            print(f"⏳ レートリミット。{wait_time}秒後リトライ... ({attempt + 1}/{max_retries})")
            time.sleep(wait_time)
        else:
            raise Exception(f"API Error: {response.status_code} - {response.text}")

    result = response.json()
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise Exception(f"Unexpected API response: {result}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 記事生成フロー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_generation_prompt(raw_memo: str, style_guide: str = "") -> str:
    """生成プロンプトを組み立てる。"""
    style_section = ""
    if style_guide:
        style_section = f"\n### 文体ガイド（最優先で従うこと）\n{style_guide}\n"

    return f"""
{SECURITY_SYSTEM_PROMPT}
{style_section}

### 筆者がポメラに書きなぐったメモ（原文そのまま）

{raw_memo}

### 指示
このメモをベースに、経営層・非エンジニア向けのセキュリティブログ記事を書いてください。
筆者が「わからない」と書いていた部分は正確な情報で補完してください。
筆者が書いた予想・感想は、合っていれば活かし、間違っていれば自然に修正してください。
メモの文体（口語的・思考の流れ）は記事全体のトーンに活かしてください。
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


def generate_security_article(
    raw_memo: str,
    style_guide: str = "",
    max_revisions: int = 1
) -> Dict[str, Any]:
    """生メモからセキュリティ記事を生成する。

    生成後に自己レビューを行い、問題があればフィードバックを反映して再生成する。
    """
    prompt = build_generation_prompt(raw_memo, style_guide)
    print("🔒 セキュリティ記事を生成中...")
    json_text = call_gemini_api(prompt)
    article_data = json.loads(json_text)

    for revision in range(max_revisions):
        article_body = article_data.get("body", "")
        if not article_body:
            break

        passed, issues = review_article(article_body)
        if passed:
            break

        feedback_lines = [
            f"- [{i.get('type', '')}] {i.get('detail', '')}\n  改善案: {i.get('suggestion', '')}"
            for i in issues
        ]
        feedback_section = "\n".join(feedback_lines)

        revision_prompt = f"""
{SECURITY_SYSTEM_PROMPT}

{build_generation_prompt(raw_memo, style_guide)}

### 前回の生成結果に対するレビューフィードバック
以下の問題を修正して書き直してください。

{feedback_section}

### 前回の本文（参考）
{article_body[:1000]}...

### 指示
フィードバックを反映し、問題を修正した新しいバージョンを執筆してください。
"""
        print(f"📝 フィードバック反映版を生成中... (リビジョン {revision + 1}/{max_revisions})")
        json_text = call_gemini_api(revision_prompt)
        article_data = json.loads(json_text)

    return article_data
