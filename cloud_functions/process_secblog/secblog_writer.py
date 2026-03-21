"""
secblog_writer.py — Cloud Function 用 SECBLOGライター

scripts/secblog_writer.py から Cloud Function 実行用に
ファイルI/O・はてな投稿を除いた生成コアロジックのみを提供する。
"""
import os
import re
import json
from typing import Dict, Any, Tuple

import requests

API_KEY = os.environ.get("GOOGLE_API_KEY", "")

SECBLOG_SYSTEM_PROMPT = """
あなたはセキュリティ分野の専門家であり、教育者です。
提供されたセキュリティに関する考察をもとに、
**対話形式のブログ記事**を執筆してください。

# 登場人物
- **セキュリティスペシャリスト（あなたが演じる）**: セキュリティ専門家。質問を投げかけ、正しい点を評価し、誤りや認識の浅い点を丁寧に補足し、実際の事例を用いて解説する。威圧的でなく、学習を楽しくするトーンで話す。
- **セキュリティ初学者（筆者）**: セキュリティを学び始めた素直な学習者。拙くても正直な言葉で話す。専門用語を知らなくてもいい。

# 対話の構成ルール
1. **セキュリティスペシャリストが問いを立てる**: 提供された内容から核心的なテーマを2〜3個取り出し、それぞれ独立したテーマとして立てる
2. **セキュリティ初学者が答える**: 提供された内容の考えをそのまま口語で表現する（整えすぎない）。2〜3文以上で答える
3. **セキュリティスペシャリストが評価・補足する**: 正しい点を明示した上で、誤りや不足を実際の事例・具体的な攻撃シナリオや実際に起きた被害例・技術的根拠を300〜400字程度で丁寧に補足する。「なるほど、それは的確です」「惜しい！もう少し深めましょう」のようなトーンで
4. **セキュリティスペシャリストが深堀りする**: さらに一段深い問いを投げかけ、対話を2〜3往復続ける。1テーマにつきセキュリティスペシャリスト・セキュリティ初学者が最低2回ずつ発言する
5. **セキュリティスペシャリストがまとめる**: 今日のポイントを箇条書き3〜5点でまとめる

# 文体ルール
- セキュリティスペシャリストの言葉: 親しみやすく、少し逆説的・挑発的な問いかけが良い。「本当にそれだけ？」「それは正しい。では攻撃者の視点から考えると？」
- セキュリティ初学者の言葉: 話し言葉に近い、素直な日本語。整いすぎない。「〜だと思います」「〜ということですよね？」くらいの温度感
- 見出しはテーマの内容をシンプルに表した文章一文にする。番号形式（「第1問」など）は使わない
- 記事の冒頭に「今日のテーマ」として〜2行でトピックを紹介する
- 末尾に「今日のまとめ」セクションを置く

# 絶対に守るべきルール
1. セキュリティ初学者の言葉は、提供された内容の考えを忠実に反映する。正しくても間違っていても、その時点の認識を大切にする
2. セキュリティスペシャリストは答えを先に言わない。問いを立ててから、セキュリティ初学者の言葉を受けて補足する
3. 専門用語は必ず平易な言葉でフォローする（例: 「XSS、つまりクロスサイトスクリプティングとは〜」）
4. 実際の事例や攻撃手法は具体的に書く（ただし悪用を促す内容は書かない）
5. 記事の冒頭にタイトルは書かない
6. 記事全体を通して「学ぶのが楽しい」という読後感を心がける
7. **メタ表現禁止**: 「メモ」「草案」「書いてくれた内容」「提供された情報によると」など、筆者が事前に何かを書いたことを匂わせる表現は一切使わない。セキュリティ初学者は自分の経験・考えとして自然に語る

# 記事の構成

## Part 1: 対話パート（セキュリティ初学者 × セキュリティスペシャリスト）
前述の対話の構成ルールに従い対話形式で執筆する。

## Part 2: 技術メモ
対話パートの後ろに、以下のセクションを「---」で区切った上で「## 技術メモ」として必ず追加する。

技術メモには以下の3つを必ず含めること:

[1] 「### 攻撃の種類」
トピックの攻撃手法の種類をMarkdownテーブルで整理する（種類名・特徴・主なリスク の3列）。
XSSの場合は「反射型 / 蓄積型 / DOM型」。SQLiやCSRFなど別の脅威ならその脅威の分類を書く。

[2] 「### コード例（学習用・悪用不可）」
攻撃ペイロードの簡易例（html コードブロック）と、防御側のエスケープ・サニタイズ処理例（python など）を示す。
トピックに応じて言語・内容を変えること。

[3] 「### 防御の実装チェックリスト」
エンジニアが実際に対処できる防御策を「- [ ] 〜」形式で5〜8項目列挙する。
XSSなら: HTMLエスケープ、CSPヘッダー、HttpOnly属性、Secure属性、X-Content-Type-Options、ライブラリの最新化、定期スキャン など。
トピックに応じた内容に変更すること。

# 文字数・ボリュームの基準
- 本文全体（対話パート＋技術メモ）は2500文字以上4500文字以下にすること
- 対話パートのセキュリティスペシャリストの補足説明は250〜400文字を目安に書く
- 実際の事例（○○社の情報漏洩事件、ハッカーがよく使う手口など）を最低1件以上、具体的に盛り込む
- 「今日のまとめ」は箇条書き3〜5点で、各点を2〜3文で説明する
- 技術メモのテーブル・コードブロック・チェックリストは必ず全て含める

言語: 日本語。
本文のみを出力してください。JSONやコードブロックの囲みは不要です。
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


def _call_api(prompt: str, as_json: bool = False) -> str:
    """Gemini APIを呼び出す。"""
    if not API_KEY:
        raise ValueError("GOOGLE_API_KEY is not set.")

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent"
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7}
    }
    if as_json:
        data["generationConfig"]["response_mime_type"] = "application/json"

    resp = requests.post(url, headers={"Content-Type": "application/json"}, json=data, params={"key": API_KEY})
    resp.raise_for_status()
    result = resp.json()
    return result["candidates"][0]["content"]["parts"][0]["text"]


def _extract_json(text: str) -> str:
    """テキストからJSONブロックを抽出する。"""
    m = re.search(r'```json\s*([\s\S]*?)\s*```', text)
    if m:
        return m.group(1).strip()
    start = text.find('{')
    end = text.rfind('}') + 1
    if start != -1 and end > start:
        return text[start:end]
    return text


def _review(body: str) -> Tuple[bool, list]:
    """生成された記事をレビューする。"""
    prompt = f"{REVIEW_PROMPT}\n\n### レビュー対象の記事\n{body}"
    raw = _call_api(prompt, as_json=True)
    result = json.loads(_extract_json(raw))
    return result.get("passed", True), result.get("issues", [])


def _generate_meta(body: str) -> Dict[str, Any]:
    """本文からタイトル・説明文・カテゴリをJSON形式で生成する。"""
    prompt = f"""
以下のセキュリティブログ記事の本文を読み、次の情報を生成してください。

本文:
{body[:800]}

出力はJSON形式で、以下の4つのキーのみ含めてください:
- title: 魅力的なブログ記事タイトル（50文字以内）
- description: SEO向けメタディスクリプション（120文字以内）
- categories: カテゴリのリスト（例: ["セキュリティ", "学習記録"]）
- estimated_read_time: 読了時間（例: "8分"）

JSON以外のテキストは一切含めないでください。
"""
    raw = _call_api(prompt, as_json=True)
    try:
        return json.loads(_extract_json(raw))
    except Exception:
        return {"title": "セキュリティ学習記録", "description": "", "categories": ["セキュリティ", "学習記録"], "estimated_read_time": ""}


def generate_secblog_article(memo_text: str, max_revisions: int = 1) -> Dict[str, Any]:
    """セキュリティメモから対話形式のブログ記事を生成する。"""
    body_prompt = f"""
{SECBLOG_SYSTEM_PROMPT}

### セキュリティに関する考察
---
{memo_text}
---

上記の考察をもとに、対話形式のブログ記事を1本執筆してください。
内容がたとえ不正確であっても、それが「現時点での学習者の考え」として記事に生かされるようにしてください。
セキュリティスペシャリストが正確な情報や事例で補足することで、読者も一緒に学べる記事にしてください。
記事本文のみを出力してください。
"""
    print("📝 セキュリティ対話記事を生成中...")
    body_text = _call_api(body_prompt)

    # レビュー & リビジョン
    passed, issues = _review(body_text)
    if not passed and max_revisions > 0:
        feedback = "\n".join(
            f"- [{i.get('type', '')}] {i.get('detail', '')}\n  改善案: {i.get('suggestion', '')}"
            for i in issues
        )
        revision_prompt = f"""
{SECBLOG_SYSTEM_PROMPT}

### セキュリティに関する考察
---
{memo_text}
---

### レビューフィードバック
{feedback}

### 前回の本文（参考）
{body_text[:800]}...

上記のフィードバックを反映し、修正した記事本文のみを出力してください。
"""
        print("📝 フィードバック反映版を生成中...")
        body_text = _call_api(revision_prompt)

    # メタ情報生成
    print("🏷️ タイトル・メタ情報を生成中...")
    meta = _generate_meta(body_text)

    return {
        "title": meta.get("title", "セキュリティ学習記録"),
        "body": body_text,
        "description": meta.get("description", ""),
        "categories": meta.get("categories", ["セキュリティ", "学習記録"]),
        "estimated_read_time": meta.get("estimated_read_time", ""),
    }
