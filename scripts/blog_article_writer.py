"""
blog_article_writer.py — ポメラ草案 → ブログ記事生成

ポメラで書いたメモをもとに、Gemini APIで読みやすいブログ記事を生成する。
ナレッジグラフから関連テーマを引用して記事に深みを持たせる。
生成後、hatena_publisher.py を呼び出してはてなブログに下書き投稿する。
"""

import os
import json
import re
import argparse
import subprocess
from datetime import datetime
import requests
from typing import Dict, Any, Optional, Tuple

# 設定
API_KEY = os.getenv("GOOGLE_API_KEY")
MASTER_GRAPH_PATH = "knowledge_graph.jsonld"
BLOG_READY_DIR = "blog_ready"
HATENA_PUBLISHER_SCRIPT = "scripts/hatena_publisher.py"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ブログ記事 生成プロンプト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BLOG_SYSTEM_PROMPT = """
# 役割
あなたはプロのテックブロガーであり、エッセイストです。
ユーザーがポメラで書いた「メモ」や「考えたこと」をもとに、
**読者が楽しく読めるブログ記事**を執筆してください。

# 記事のスタイル
- 個人ブログらしい、親しみやすい語り口で書く
- 「です・ます」調で統一する
- 読者に語りかけるような文体にする
- 専門用語は噛み砕いて説明する
- 体験談や具体例を交えて、説得力を持たせる
- 適度にユーモアを織り交ぜる
- 読み終わったあとに「なるほど」と思える内容にする

# 記事の構成
以下の構成で記事を書いてください:

1. **導入**: 読者の興味を引くフックから始める。日常の風景や疑問から入ると良い。
2. **本論**: メモの核心を膨らませる。体験→考察→発見の流れで展開する。
   - 見出しを2〜4個つけて読みやすく区切る
   - 具体的なエピソードと抽象的な考察を交互に配置する
   - 「〇〇だと思っていた。でも実は△△だった」のような気づきの構造を入れる
3. **まとめ**: 読者へのメッセージで締める。押しつけがましくなく、余韻を残す。

# 絶対に守るべきルール
1. メモの内容をそのままコピペしない。必ず記事として再構成する
2. 個人を特定できる情報は書かない。固有名詞は必要に応じて一般化する
3. 「以上です」「いかがでしたか？」のような定型文は使わない
4. SEOを意識しすぎた不自然な文章は避ける
5. 記事の冒頭にタイトルは書かない

# 品質のチェックポイント
- 最初の3行で読者が続きを読みたくなるか
- 見出しだけ読んでも記事の流れがわかるか
- 「だから何？」と思われるポイントがないか
- 読後に何か一つでも持ち帰れるものがあるか

# 出力形式
以下のJSON形式で出力してください:

{
  "title": "ブログ記事のタイトル（30文字以内、興味を引くもの）",
  "body": "本文（はてなブログ用Markdown形式）",
  "description": "メタデスクリプション（120文字以内の記事概要）",
  "categories": ["カテゴリ1", "カテゴリ2"],
  "estimated_read_time": "○分"
}

# 重要な注意事項
- 記事の長さは1500〜3000文字程度。スマホで読み切れる長さ
- 見出しは本文中に2〜4個。多すぎない
- はてなブログのMarkdown形式に従う
- カテゴリは内容に合ったものを2〜3個提案する

言語: 日本語。
JSON以外のテキストは一切含めないでください。
"""

REVIEW_PROMPT = """
あなたはブログの編集者です。以下のブログ記事を読み、品質をチェックしてください。

## チェック項目
以下の各項目について、問題があれば具体的に指摘してください。

1. **読みやすさ**: 文章のリズムは良いか。一文が長すぎないか。
2. **構成**: 導入→本論→まとめの流れが自然か。見出しの配置は適切か。
3. **具体性**: 抽象的な話ばかりで退屈になっていないか。具体例はあるか。
4. **読者目線**: 読者が「自分にも関係ある」と感じられるか。押しつけがましくないか。
5. **タイトル**: 記事の内容を反映しつつ、興味を引くタイトルか。

## 出力形式
以下のJSON形式で出力してください:

{
  "passed": true/false,
  "issues": [
    {
      "type": "読みやすさ",
      "detail": "具体的な問題箇所と理由",
      "suggestion": "改善案"
    }
  ]
}

問題がなければ passed を true にし、issues は空配列にしてください。
1つでも問題があれば passed を false にしてください。
JSON以外のテキストは一切含めないでください。
"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ユーティリティ
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


def load_knowledge_graph() -> Optional[Dict[str, Any]]:
    """ナレッジグラフを読み込む。"""
    if not os.path.exists(MASTER_GRAPH_PATH):
        print("⚠️ ナレッジグラフが見つかりません。草案のみで記事を生成します。")
        return None
    
    try:
        with open(MASTER_GRAPH_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ ナレッジグラフの読み込みに失敗: {e}")
        return None


def extract_blog_context(graph: Dict[str, Any]) -> str:
    """ナレッジグラフからブログ記事に役立つコンテキストを抽出する。

    最近の知見・感情・タスクの傾向から、記事の切り口に使える情報を提供する。
    """
    nodes = graph.get("nodes", [])
    
    # 知見からテーマを抽出
    insights = [n for n in nodes if n.get("type") == "知見"]
    insights_sorted = sorted(insights, key=lambda x: x.get("last_seen", ""), reverse=True)[:8]
    
    # 感情の傾向を抽出
    emotions = [n for n in nodes if n.get("type") == "感情"]
    emotions_sorted = sorted(emotions, key=lambda x: x.get("last_seen", ""), reverse=True)[:5]
    
    # タスクの傾向を抽出
    tasks = [n for n in nodes if n.get("type") == "タスク"]
    tasks_sorted = sorted(tasks, key=lambda x: x.get("last_seen", ""), reverse=True)[:5]
    
    context = "### 筆者の最近の関心事（記事に深みを持たせるための背景情報）\n"
    
    if insights_sorted:
        context += "\n**最近の気づき:**\n"
        for i in insights_sorted:
            label = i.get('label', '')
            detail = i.get('detail', '')
            if detail:
                context += f"- {label}: {detail[:80]}\n"
            else:
                context += f"- {label}\n"
    
    if emotions_sorted:
        context += "\n**最近の感情傾向:**\n"
        for e in emotions_sorted:
            label = e.get('label', '')
            sentiment = e.get('sentiment', 0)
            tone = "ポジティブ" if sentiment > 0 else "ネガティブ" if sentiment < 0 else "ニュートラル"
            context += f"- {label}（{tone}）\n"
    
    if tasks_sorted:
        context += "\n**最近取り組んでいること:**\n"
        for t in tasks_sorted:
            label = t.get('label', '')
            context += f"- {label}\n"
    
    return context


def parse_blog_memo(memo_text: str) -> Dict[str, str]:
    """ブログ用メモをパースする。

    テンプレート形式にも自由形式にも対応する。
    テンプレートのフィールド:
    - テーマ
    - カテゴリ
    - 伝えたいこと
    - メモ
    """
    fields = {
        "テーマ": "",
        "カテゴリ": "",
        "伝えたいこと": "",
        "メモ": ""
    }
    
    known_keys = list(fields.keys())
    has_template = any(f"{key}:" in memo_text or f"{key}：" in memo_text for key in known_keys[:2])
    
    if not has_template:
        fields["メモ"] = memo_text.strip()
        return fields
    
    current_key = None
    current_lines = []
    
    for line in memo_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            if current_key:
                current_lines.append("")
            continue
        
        matched_key = None
        for key in known_keys:
            if stripped.startswith(f"{key}:") or stripped.startswith(f"{key}："):
                matched_key = key
                break
        
        if matched_key:
            if current_key:
                fields[current_key] = "\n".join(current_lines).strip()
            current_key = matched_key
            sep = "：" if f"{matched_key}：" in stripped else ":"
            value = stripped.split(sep, 1)[1].strip()
            current_lines = [value] if value else []
        else:
            current_lines.append(stripped)
    
    if current_key:
        fields[current_key] = "\n".join(current_lines).strip()
    
    return fields


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メインフロー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_generation_prompt(fields: Dict[str, str], context: str) -> str:
    """生成プロンプトを組み立てる。"""
    memo_section = "### ブログのネタ（ポメラで書いたメモ）\n\n"
    
    if fields["テーマ"]:
        memo_section += f"**テーマ:** {fields['テーマ']}\n"
    if fields["カテゴリ"]:
        memo_section += f"**カテゴリ:** {fields['カテゴリ']}\n"
    if fields["伝えたいこと"]:
        memo_section += f"\n**伝えたいこと:**\n{fields['伝えたいこと']}\n"
    if fields["メモ"]:
        memo_section += f"\n**メモの内容:**\n{fields['メモ']}\n"
    
    return f"""
{BLOG_SYSTEM_PROMPT}

{context}

{memo_section}

### 指示
上記のメモをもとに、読者が楽しく読めるブログ記事を1本執筆してください。
メモの内容をそのまま使うのではなく、ブログ記事として再構成してください。
背景情報がある場合は、記事に深みを持たせるために活用してください。
"""


def review_article(article_body: str) -> Tuple[bool, list]:
    """生成されたブログ記事をレビューする。"""
    prompt = f"""
{REVIEW_PROMPT}

### レビュー対象のブログ記事
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


def generate_blog_article(memo_text: str, context: str, max_revisions: int = 1) -> Dict[str, Any]:
    """メモとコンテキストからブログ記事を生成する。

    生成後に自己レビューを行い、品質に問題があれば
    フィードバックを反映して再生成する。
    """
    
    fields = parse_blog_memo(memo_text)
    
    prompt = build_generation_prompt(fields, context)
    print("📝 ブログ記事を生成中...")
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
{BLOG_SYSTEM_PROMPT}

{context}

{build_generation_prompt(fields, context)}

### 前回の生成結果に対するレビューフィードバック
以下の問題が指摘されました。これらを全て修正した上で、記事を書き直してください。

{feedback_section}

### 前回の本文（参考）
{article_body[:1000]}...

### 指示
上記のフィードバックを反映し、問題を修正した新しいバージョンのブログ記事を執筆してください。
記事の骨格は維持しつつ、指摘された品質問題を解消してください。
"""
        
        print(f"📝 フィードバック反映版を生成中... (リビジョン {revision + 1}/{max_revisions})")
        json_text = call_gemini_api(revision_prompt)
        article_data = json.loads(json_text)
    
    return article_data


def save_article(article_data: Dict[str, Any], source_file: str) -> tuple:
    """生成されたブログ記事をファイルに保存する。"""
    if not os.path.exists(BLOG_READY_DIR):
        os.makedirs(BLOG_READY_DIR)
    
    date_str = datetime.now().strftime('%Y%m%d')
    title = article_data.get("title", "無題")
    
    safe_title = re.sub(r'[\\/*?:"<>|]', '', title)[:50]
    
    md_filename = f"{date_str}_{safe_title}.md"
    md_path = os.path.join(BLOG_READY_DIR, md_filename)
    
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(article_data.get("body", ""))
    
    meta_filename = f"{date_str}_{safe_title}.json"
    meta_path = os.path.join(BLOG_READY_DIR, meta_filename)
    
    meta = {
        "title": title,
        "description": article_data.get("description", ""),
        "categories": article_data.get("categories", []),
        "estimated_read_time": article_data.get("estimated_read_time", ""),
        "source_file": source_file,
        "generated_at": datetime.now().isoformat(),
        "type": "blog_article"
    }
    
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    
    print(f"✅ ブログ記事を保存しました: {md_path}")
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


def main():
    parser = argparse.ArgumentParser(description="ポメラメモ → ブログ記事 → はてなブログ投稿")
    parser.add_argument("input_file", help="メモテキストファイルのパス")
    parser.add_argument("--skip-publish", action="store_true", help="はてなブログへの投稿をスキップ")
    parser.add_argument("--master-graph", default=MASTER_GRAPH_PATH, help="ナレッジグラフのパス")
    
    args = parser.parse_args()
    
    # 1. メモの読み込み
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
    
    print(f"📄 メモを読み込みました: {args.input_file}")
    print(f"   文字数: {len(memo_text)}")
    
    # 2. ナレッジグラフからコンテキストを取得
    context = ""
    graph = load_knowledge_graph()
    if graph:
        context = extract_blog_context(graph)
        print("📊 ナレッジグラフからコンテキストを抽出しました")
    
    # 3. ブログ記事を生成
    try:
        article_data = generate_blog_article(memo_text, context)
        print(f"✨ 記事生成完了: 「{article_data.get('title', '無題')}」")
    except Exception as e:
        print(f"❌ 記事生成中にエラー: {e}")
        return
    
    # 4. ファイルに保存
    md_path, meta_path = save_article(article_data, args.input_file)
    
    # 5. はてなブログに投稿
    if not args.skip_publish:
        publish_to_hatena(md_path, meta_path)
    else:
        print("⏭️ はてなブログへの投稿はスキップされました")


if __name__ == "__main__":
    main()
