"""
study_blog_writer.py — 勉強記録 → 勉強ブログ記事生成 → はてなブログ投稿

勉強ドラフトファイルを受け取り、Neo4jの過去の学習ノードと組み合わせて
「今日学んだこと」スタイルの技術ブログ記事を生成し、
kakikukekoichi-study.hateblo.jp に下書き投稿する。

使い方:
  python scripts/study_blog_writer.py study_drafts/20260319_STUDY_TypeScript.txt

投稿先:
  通常ブログ: kakikukekoichi.hatenablog.com (HATENA_BLOG_ID)
  勉強ブログ: HATENA_STUDY_BLOG_ID (例: kakikukekoichi-study.hateblo.jp)
"""

import os
import json
import re
import sys
import argparse
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

# ── 設定 ──
API_KEY = os.getenv("GOOGLE_API_KEY")
BLOG_READY_DIR = "blog_ready"
STUDY_REVIEWS_DIR = "study_reviews"
HATENA_PUBLISHER_SCRIPT = "scripts/hatena_publisher.py"
WRITING_STYLE_PATH = "writing_style.md"
STUDY_BLOG_ID = os.getenv("HATENA_STUDY_BLOG_ID", "kakikukekoichi-study.hateblo.jp")
_DEFAULT_MODEL = "gemini-2.0-flash"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# プロンプト定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STUDY_BLOG_SYSTEM_PROMPT = """
# 役割
あなたは「エンジニアが勉強したことをブログにまとめる」ライターです。
ポメラで書いた勉強メモをもとに、「今日学んだこと」「やっとわかった」スタイルの
技術・学習ブログ記事を書いてください。

# このブログの特徴
- 対象: kakikukekoichi-study.hateblo.jp（勉強専用ブログ）
- 読者: 同じことを勉強中のエンジニア・学習者
- トーン: 丁寧すぎず、フランクすぎず。自分が学んだ過程を素直に書く

# 記事のスタイル（必ず守ること）
- 「〜のだ」「〜なのだ」「〜たいのだ」で文を締める。筆者の語尾の基本
- 「〜と思っている」「〜と考えている」で自分の考えを語る。断言しすぎない
- 「なんというか」「だからこそ」「そのうえで」などの口語的な繋ぎ言葉を使う
- 「です・ます」調は使わない
- 勉強したことを「教える」のではなく「一緒に発見する」ように書く

# 絶対に使わない表現
- 「〜いかがでしたか？」
- 「まとめ」「おわりに」という見出し（これで終わる感じが嫌い）
- キャッチコピー的な比喩
- 「〜してほしい」で読者に訴えかける締め方

# 構成ガイド
1. 導入: なぜこれを勉強したか、どこで詰まったか（正直に）
2. 本論: わかったこと・ハマったこと・試したことの流れ
   - コードや例があれば使う（はてなブログのMarkdown形式）
3. 締め: 「これが使えるなら〜ができそう」という展望、または「まだわかってない部分」

# 記事の長さ
1200〜2500文字程度。スマホで読み切れる長さ。

# 出力形式（必ずこのJSON形式）
{
  "title": "ブログ記事のタイトル（40文字以内。読者が『あ、自分も知りたい』と思えるもの）",
  "body": "本文（はてなブログ用Markdown形式）",
  "description": "メタデスクリプション（120文字以内）",
  "categories": ["カテゴリ1", "カテゴリ2"],
  "estimated_read_time": "○分",
  "subject": "科目名（TypeScript, 簿記3級 など）"
}

言語: 日本語。JSON以外のテキストは一切含めないでください。
"""

STUDY_CONTENT_REVIEW_PROMPT = """
# 役割
あなたは経験豊富なエンジニア・メンターです。
学習者が書いた「勉強メモ」を読んで、理解度をフィードバックしてください。

# 評価の基本姿勢
- 学習者を励ます。厳しく採点するのではなく「次に進むための地図」を渡すイメージ
- 「わかっていること」を先に認める
- 抜け漏れや誤りは「こっちも面白いよ」という提示の仕方で伝える

# 出力形式（必ずこのJSONで）
{
  "understanding_score": 0.0〜1.0,
  "understanding_summary": "今の理解度を一言で表す（例：基礎の入口に立っている）",
  "strong_points": ["理解できている点①", "②"],
  "missing_points": ["まだカバーできていないが重要な点①", "②"],
  "corrections": ["明確に誤っている理解があれば指摘（なければ空配列）"],
  "next_steps": ["次に学ぶと理解が深まる具体的なトピック①", "②", "③"],
  "encouraging_message": "学習者への短いエールメッセージ（2〜3文。筆者の言葉で）",
  "estimated_time_to_next_level": "次のレベルに達するまでの目安（例：週1回の練習で1ヶ月程度）"
}

JSON以外のテキストは一切含めないでください。言語: 日本語。
"""

STUDY_REVIEW_PROMPT = """
あなたはブログの編集者です。以下の「勉強まとめブログ記事」をレビューしてください。

## 文体への指摘は不要
以下の特徴は意図的なスタイルです:
- 「〜のだ」「〜なのだ」という語尾
- 「なんというか」などの口語的な繋ぎ言葉
- 思考を流れるように書く構成

## チェック項目（これだけ指摘してください）
1. **技術的正確さ**: 明らかに誤った説明はあるか
2. **わかりやすさ**: 同じことを勉強している人が読んで意味を追えるか
3. **タイトル**: 記事内容と大きくズレているか

## 出力形式
{
  "passed": true/false,
  "issues": [
    {
      "type": "技術的正確さ",
      "detail": "問題箇所と理由",
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
    if not API_KEY:
        raise ValueError("GOOGLE_API_KEY が未設定です。")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{_DEFAULT_MODEL}:generateContent"
    params = {"key": API_KEY}
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }

    import time
    for attempt in range(max_retries + 1):
        response = requests.post(url, headers=headers, json=data, params=params)
        if response.status_code == 200:
            break
        elif response.status_code == 429 and attempt < max_retries:
            wait = 30 * (2 ** attempt)
            print(f"⏳ レートリミット。{wait}秒後リトライ ({attempt+1}/{max_retries})...")
            time.sleep(wait)
        else:
            raise Exception(f"API Error: {response.status_code} - {response.text}")

    result = response.json()
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise Exception(f"Unexpected API response: {result}")


def load_writing_style() -> str:
    """文体ガイドファイルを読み込む。"""
    if not os.path.exists(WRITING_STYLE_PATH):
        return ""
    try:
        with open(WRITING_STYLE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"⚠️ 文体ガイドの読み込みに失敗: {e}")
        return ""


def extract_subject_from_filename(filepath: str) -> str:
    """ファイル名から科目名を推測する。
    例: study_drafts/20260319_STUDY_TypeScript.txt → TypeScript
    """
    basename = os.path.basename(filepath).replace(".txt", "")
    # STUDY_ の後の部分を取得
    parts = basename.split("_STUDY_")
    if len(parts) > 1:
        return parts[-1]
    # [STUDY] 形式にも対応
    parts = re.split(r'\[STUDY\]', basename, flags=re.IGNORECASE)
    if len(parts) > 1:
        return parts[-1].strip()
    return "学習記録"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Neo4j からの学習コンテキスト取得
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_subject_context(subject: str) -> str:
    """Neo4j から同じ科目の過去学習ノードを取得してコンテキストとして返す。"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)

        import neo4j_client as _nc
        client = _nc.Neo4jClient()
        graph = client.export_graph()
        client.close()

        # 同じ科目の勉強記録ノードを検索（部分一致）
        study_nodes = [
            n for n in graph.get("nodes", [])
            if n.get("type") == "勉強記録"
            and subject.lower() in (n.get("subject") or n.get("label", "")).lower()
        ]

        if not study_nodes:
            return ""

        # 日付昇順でソート（学習履歴として読める）
        study_nodes.sort(key=lambda x: x.get("date", ""))

        context_lines = [f"### 「{subject}」の過去の学習履歴（最新{min(len(study_nodes), 5)}件）"]
        for node in study_nodes[-5:]:
            date = node.get("date", "日付不明")
            mastery = node.get("mastery", 0.5)
            concepts = node.get("key_concepts") or []
            if isinstance(concepts, str):
                try:
                    concepts = json.loads(concepts)
                except Exception:
                    concepts = [concepts]
            questions = node.get("questions") or []
            if isinstance(questions, str):
                try:
                    questions = json.loads(questions)
                except Exception:
                    questions = [questions]
            detail = node.get("detail", "")[:200]

            context_lines.append(f"\n**{date}** (習熟度: {int(mastery * 100)}%)")
            if concepts:
                context_lines.append(f"  学んだ概念: {', '.join(concepts[:5])}")
            if questions:
                context_lines.append(f"  残った疑問: {', '.join(questions[:3])}")
            if detail:
                context_lines.append(f"  内容: {detail}")

        print(f"✅ 過去の {subject} 学習記録 {len(study_nodes)} 件を取得")
        return "\n".join(context_lines)

    except Exception as e:
        print(f"⚠️ Neo4j からの学習コンテキスト取得失敗（スキップ）: {e}")
        return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 勉強内容レビュー生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_study_review(
    memo_text: str,
    subject: str,
    past_context: str,
    study_date: str,
) -> Dict[str, Any]:
    """勉強メモをAIがレビューし、理解度・抜け漏れ・次のステップを返す。"""
    if not API_KEY:
        print("⚠️ GOOGLE_API_KEY 未設定。レビューをスキップします。")
        return {}

    prompt = f"""
{STUDY_CONTENT_REVIEW_PROMPT}

{past_context}

### 今回の勉強メモ（{study_date}）
科目: {subject}

{memo_text}

### 指示
上記の勉強メモを読んで、学習者の理解度を評価してください。
過去の学習履歴があれば、成長度合いも考慮してください。
"""

    print(f"🔍 勉強内容をレビュー中... (科目: {subject})")
    try:
        raw = call_gemini_api(prompt)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'```\s*$', '', cleaned).strip()
        review = json.loads(cleaned)
        score = review.get("understanding_score", 0)
        print(f"✅ レビュー完了: 理解度スコア {int(score * 100)}%")
        return review
    except Exception as e:
        print(f"⚠️ レビュー生成失敗: {e}")
        return {}


def save_study_review(
    review: Dict[str, Any],
    source_file: str,
    subject: str,
    study_date: str,
) -> Optional[str]:
    """レビュー結果を study_reviews/ に保存する。"""
    if not review:
        return None

    if not os.path.exists(STUDY_REVIEWS_DIR):
        os.makedirs(STUDY_REVIEWS_DIR)

    date_str = study_date.replace("-", "") if study_date else datetime.now().strftime("%Y%m%d")
    safe_subject = re.sub(r'[\\/*?:"<>|]', '', subject)[:30]
    filename = f"{date_str}_review_{safe_subject}.json"
    filepath = os.path.join(STUDY_REVIEWS_DIR, filename)

    output = {
        "source_file": source_file,
        "subject": subject,
        "date": study_date,
        "generated_at": datetime.now().isoformat(),
        "review": review,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ レビューを保存しました: {filepath}")
    return filepath


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 記事生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_generation_prompt(
    memo_text: str,
    subject: str,
    past_context: str,
    style_guide: str,
    study_date: str,
) -> str:
    style_section = f"\n### 文体ガイド（最優先で従うこと）\n{style_guide}\n" if style_guide else ""

    return f"""
{STUDY_BLOG_SYSTEM_PROMPT}
{style_section}
{past_context}

### 今回の勉強メモ（{study_date}）
科目: {subject}

{memo_text}

### 指示
上記の勉強メモを、「今日 {subject} を勉強してこんなことがわかった」という
ブログ記事にしてください。

- メモをそのままコピーせず、記事として再構成してください
- 過去の学習履歴があれば「以前詰まっていた〇〇がやっとわかった」という流れにしてください
- コードサンプルや具体例があれば積極的に使ってください
- 読者は「同じことを勉強中の人」を想定してください
"""


def review_article(body: str) -> Tuple[bool, list]:
    """生成された記事をレビューする。"""
    prompt = f"""
{STUDY_REVIEW_PROMPT}

### レビュー対象の記事
{body}
"""
    print("🔍 品質レビュー中...")
    try:
        raw = call_gemini_api(prompt)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'```\s*$', '', cleaned).strip()
        result = json.loads(cleaned)
        passed = result.get("passed", True)
        issues = result.get("issues", [])
        if issues:
            for issue in issues:
                print(f"   ⚠️ [{issue.get('type')}] {issue.get('detail')}")
        else:
            print("   ✅ 品質チェック合格")
        return passed, issues
    except Exception as e:
        print(f"   ⚠️ レビュー失敗（スキップ）: {e}")
        return True, []


def generate_study_article(
    memo_text: str,
    subject: str,
    past_context: str,
    style_guide: str,
    study_date: str,
    max_revisions: int = 1,
) -> Dict[str, Any]:
    """勉強メモから記事を生成する（レビュー・修正ループ付き）。"""
    prompt = build_generation_prompt(memo_text, subject, past_context, style_guide, study_date)
    print(f"📝 勉強ブログ記事を生成中... (科目: {subject})")

    raw = call_gemini_api(prompt)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'```\s*$', '', cleaned).strip()
    article_data = json.loads(cleaned)

    for revision in range(max_revisions):
        body = article_data.get("body", "")
        if not body:
            break
        passed, issues = review_article(body)
        if passed:
            break

        feedback = "\n".join([
            f"- [{i.get('type')}] {i.get('detail')}\n  改善案: {i.get('suggestion', '')}"
            for i in issues
        ])
        revision_prompt = f"""
{STUDY_BLOG_SYSTEM_PROMPT}

{past_context}

### 元の勉強メモ
{memo_text[:1500]}

### レビューで指摘された問題
{feedback}

### 前回の本文（参考）
{body[:1000]}...

### 指示
上記のフィードバックを反映して記事を書き直してください。
"""
        print(f"📝 フィードバック反映版を生成中... (リビジョン {revision+1}/{max_revisions})")
        raw = call_gemini_api(revision_prompt)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'```\s*$', '', cleaned).strip()
        article_data = json.loads(cleaned)

    return article_data


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 保存・投稿
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_article(article_data: Dict[str, Any], source_file: str, study_date: str) -> Tuple[str, str]:
    """生成された記事を blog_ready/ に保存する。"""
    if not os.path.exists(BLOG_READY_DIR):
        os.makedirs(BLOG_READY_DIR)

    date_str = study_date.replace("-", "") if study_date else datetime.now().strftime("%Y%m%d")
    title = article_data.get("title", "無題")
    subject = article_data.get("subject", "study")

    safe_title = re.sub(r'[\\/*?:"<>|]', '', title)[:50]

    md_filename = f"{date_str}_STUDY_{safe_title}.md"
    md_path = os.path.join(BLOG_READY_DIR, md_filename)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(article_data.get("body", ""))

    meta_filename = f"{date_str}_STUDY_{safe_title}.json"
    meta_path = os.path.join(BLOG_READY_DIR, meta_filename)

    meta = {
        "title": title,
        "description": article_data.get("description", ""),
        "categories": article_data.get("categories", []),
        "estimated_read_time": article_data.get("estimated_read_time", ""),
        "subject": subject,
        "source_file": source_file,
        "generated_at": datetime.now().isoformat(),
        "type": "study_article",
        "blog_id": STUDY_BLOG_ID,
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"✅ 勉強ブログ記事を保存しました: {md_path}")
    print(f"✅ メタデータを保存しました: {meta_path}")

    return md_path, meta_path


def publish_to_hatena(md_path: str, meta_path: str):
    """はてなブログ（勉強専用）に下書き投稿する。"""
    env = os.environ.copy()
    env["HATENA_BLOG_ID"] = STUDY_BLOG_ID

    cmd = ["python3", HATENA_PUBLISHER_SCRIPT, md_path, "--meta", meta_path, "--force"]
    print(f"🚀 はてなブログ（{STUDY_BLOG_ID}）へ下書き投稿中...")
    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        print(f"⚠️ はてなブログへの投稿に失敗しました (returncode={result.returncode})")
    else:
        print(f"✅ はてなブログへの投稿が完了しました")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メイン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(description="勉強メモ → ブログ記事 → はてなブログ投稿")
    parser.add_argument("input_file", help="study_drafts/ のテキストファイルのパス")
    parser.add_argument("--skip-publish", action="store_true", help="はてなブログへの投稿をスキップ")
    parser.add_argument("--subject", default="", help="科目名（省略時はファイル名から推測）")
    args = parser.parse_args()

    # 1. メモの読み込み
    try:
        import unicodedata
        args.input_file = unicodedata.normalize("NFC", args.input_file)
        with open(args.input_file, "r", encoding="utf-8") as f:
            memo_text = f.read()
    except FileNotFoundError:
        print(f"❌ ファイルが見つかりません: {args.input_file}")
        return

    if not memo_text.strip():
        print("❌ メモが空です。")
        return

    print(f"📄 勉強メモを読み込みました: {args.input_file}")
    print(f"   文字数: {len(memo_text)}")

    # 2. 科目名を決定
    subject = args.subject or extract_subject_from_filename(args.input_file)
    print(f"📚 科目: {subject}")

    # 3. 勉強日を抽出（ファイル名から）
    basename = os.path.basename(args.input_file)
    date_match = re.search(r'(\d{4})(\d{2})(\d{2})', basename)
    if date_match:
        y, m, d = date_match.groups()
        study_date = f"{y}-{m}-{d}"
    else:
        study_date = datetime.now().strftime("%Y-%m-%d")
    print(f"📅 勉強日: {study_date}")

    # 4. 文体ガイドを読み込む
    style_guide = load_writing_style()

    # 5. Neo4j から過去の学習コンテキストを取得
    past_context = fetch_subject_context(subject)

    # 6. 勉強内容レビューを生成
    review = generate_study_review(
        memo_text=memo_text,
        subject=subject,
        past_context=past_context,
        study_date=study_date,
    )
    save_study_review(review, args.input_file, subject, study_date)

    # 7. 記事を生成
    try:
        article_data = generate_study_article(
            memo_text=memo_text,
            subject=subject,
            past_context=past_context,
            style_guide=style_guide,
            study_date=study_date,
        )
        print(f"✨ 記事生成完了: 「{article_data.get('title', '無題')}」")
    except Exception as e:
        print(f"❌ 記事生成中にエラー: {e}")
        return

    # 8. ファイルに保存
    md_path, meta_path = save_article(article_data, args.input_file, study_date)

    # 9. はてなブログ（勉強専用）に投稿
    if not args.skip_publish:
        publish_to_hatena(md_path, meta_path)
    else:
        print(f"⏭️ はてなブログへの投稿はスキップされました")
        print(f"   手動投稿: python scripts/hatena_publisher.py {md_path} --meta {meta_path}")


if __name__ == "__main__":
    main()
