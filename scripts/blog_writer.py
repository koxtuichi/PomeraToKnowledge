"""
blog_writer.py — ポメラ草案 → フィクション短編生成

ポメラで書いた草案をもとに、架空の登場人物による
1話完結のフィクション短編をGemini APIで生成する。
ナレッジグラフはテーマの着想源としてのみ使用し、個人情報は出力しない。
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
# フィクション短編 生成プロンプト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FICTION_SYSTEM_PROMPT = """
# 役割
あなたは星新一のようなショートショートの名手です。
ユーザーが提供する「テーマ」「感情」「教訓」をもとに、
**完全なフィクションの1話完結短編小説**を執筆してください。

# 絶対に守るべきルール
1. 登場人物は全員架空の人物にする。実在の人名・企業名・サービス名は一切使わない。
2. 具体的な日付・住所・金額・組織名など、個人を特定できる情報は書かない。
3. 「テーマのヒント」はあくまで着想の素材であり、事実としてそのまま書かない。
4. これはフィクションであり、実話ではない。読者もそう受け取れる文体にする。

# 物語の構成 — 意外性は必須
物語を「テーマ → テーマの深化 → テーマの着地」で一直線に書いてはならない。
読者が途中で結末を予測できる展開は失敗である。
以下の構成を必ず守ること:

1. **導入（フック）**: 読者を引き込む具体的なシーン。五感で描く。
   ここで読者に「この話はこういう方向だろう」と思わせる。
2. **深化（ミスディレクション）**: 物語の本筋に見える展開を丁寧に描く。
   読者の予想を確信に近づけさせる。ここが罠である。
3. **転覆（ひっくり返し）**: 物語の後半で、読者の予想を裏切る展開を入れる。
   以下のいずれかの技法を使うこと:
   - **視点のズラし**: 実は主人公が思っていた状況と現実が違った
   - **主客逆転**: 助ける側と助けられる側、観察者と被観察者が逆だった
   - **意味の反転**: ずっと否定的に描いていたものが実は肯定的だった、またはその逆
   - **物語の入れ子**: 物語内の出来事が、もう一段上の構造で別の意味を持つ
   - **時間のトリック**: 順序や因果が読者の認識と異なっていた
   - **不条理な帰結**: 論理的なのに予想外の結論に至る
4. **落とし（余韻）**: 短く、乾いた余韻で締める。最後の一文で世界の見え方が変わる。

# 絶対に避けるべきパターン
- テーマの比喩が冒頭から結末まで一貫して同じ方向に進むこと（例: 汚れ→心の傷→時間が癒す）
- 主人公が途中で「気づき」を得て、そのまま穏やかに終わること
- メッセージを作中人物の内省としてそのまま語らせること
- 「教訓」を結末の直前で地の文として説明すること

# 文体のルール
- 星新一のショートショートのように書く。淡白な語り口に毒や皮肉を忍ばせる。
- 登場人物には固有名詞の名前をつけない。「私」「僕」「彼」「彼女」「男」「女」「その人」のように呼ぶ。
- 語りかけるようなトーン。堅すぎず、崩しすぎず。
- 短い文と長い文を混ぜてリズムを作る。
- 「伝えたいこと」は絶対に直接書かない。物語の構造で読者に気づかせる。
- 主人公に悟らせるのではなく、読者に悟らせる。
- 専門的な概念は、物語の中で自然に伝わるように描写する。
- ハウツー記事にしない。あくまで「読み物」として楽しめるものに。
- 製品名やサービス名も固有名詞を使わず、一般的な表現に置き換える。

# 出力形式
以下のJSON形式で出力してください:

{
  "title": "小説のタイトル",
  "body": "本文（はてなブログ用Markdown形式）",
  "description": "メタデスクリプション（120文字以内の物語概要）",
  "categories": ["短編小説", "カテゴリ2"],
  "estimated_read_time": "○分"
}

# 重要な注意事項
- 草案の核心メッセージやテーマは必ず物語に反映させる。ただし反映の仕方に意外性を持たせる。
- 記事の長さは2000〜4000文字程度。読み切れる長さ。
- 見出しは本文中に2〜3個。多すぎない。
- はてなブログのMarkdown形式に従う。

言語: 日本語。
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


def extract_relevant_context(graph: Dict[str, Any]) -> str:
    """ナレッジグラフから匿名化されたテーマヒントを抽出する。
    
    個人を特定できる情報は除外し、テーマ・感情・教訓レベルに抽象化する。
    """
    nodes = graph.get("nodes", [])
    
    # 知見からテーマを抽出（ラベルのみ、詳細は除外）
    insights = [n for n in nodes if n.get("type") == "知見"]
    insights_sorted = sorted(insights, key=lambda x: x.get("last_seen", ""), reverse=True)[:5]
    
    # 感情の傾向を抽出（具体的な内容は除外）
    emotions = [n for n in nodes if n.get("type") == "感情"]
    emotions_sorted = sorted(emotions, key=lambda x: x.get("last_seen", ""), reverse=True)[:3]
    
    context = "### テーマのヒント（着想の素材。事実としてそのまま使わないこと）\n"
    
    if insights_sorted:
        context += "\n**最近の気づきのキーワード:**\n"
        for i in insights_sorted:
            # ラベルのみ渡す。詳細や固有名詞は含めない
            label = i.get('label', '')
            context += f"- {label}\n"
    
    if emotions_sorted:
        context += "\n**最近の感情トーン:**\n"
        for e in emotions_sorted:
            sentiment = e.get('sentiment', 0)
            tone = "ポジティブ" if sentiment > 0 else "ネガティブ" if sentiment < 0 else "ニュートラル"
            context += f"- {tone}な感情\n"
    
    return context


def parse_draft_template(draft_text: str) -> Dict[str, str]:
    """テンプレート形式の草案をパースする。
    
    テンプレートのフィールド:
    - テーマ
    - ジャンル
    - トーン
    - 伝えたいこと
    - エピソード
    - 読後感
    
    テンプレートに沿っていない場合は、全文を「エピソード」として扱う。
    """
    fields = {
        "テーマ": "",
        "ジャンル": "",
        "トーン": "",
        "伝えたいこと": "",
        "エピソード": "",
        "読後感": ""
    }
    
    # テンプレート形式かどうかを判定
    known_keys = list(fields.keys())
    has_template = any(f"{key}:" in draft_text or f"{key}：" in draft_text for key in known_keys[:3])
    
    if not has_template:
        # テンプレートなし: 全文をエピソードとして扱う
        fields["エピソード"] = draft_text.strip()
        return fields
    
    # テンプレートをパース
    current_key = None
    current_lines = []
    
    for line in draft_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            if current_key:
                current_lines.append("")
            continue
        
        # 新しいキーの検出
        matched_key = None
        for key in known_keys:
            if stripped.startswith(f"{key}:") or stripped.startswith(f"{key}："):
                matched_key = key
                break
        
        if matched_key:
            # 前のキーの内容を保存
            if current_key:
                fields[current_key] = "\n".join(current_lines).strip()
            current_key = matched_key
            # コロン以降の値を取得
            sep = "：" if f"{matched_key}：" in stripped else ":"
            value = stripped.split(sep, 1)[1].strip()
            current_lines = [value] if value else []
        else:
            current_lines.append(stripped)
    
    # 最後のキーの内容を保存
    if current_key:
        fields[current_key] = "\n".join(current_lines).strip()
    
    return fields


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メインフロー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_fiction(draft_text: str, context: str) -> Dict[str, Any]:
    """草案とコンテキストからフィクション短編を生成する。"""
    
    # 草案をパース
    fields = parse_draft_template(draft_text)
    
    # パースされたフィールドからプロンプトを組み立て
    draft_section = "### 物語の素材\n\n"
    
    if fields["テーマ"]:
        draft_section += f"**テーマ:** {fields['テーマ']}\n"
    if fields["ジャンル"]:
        draft_section += f"**ジャンル:** {fields['ジャンル']}\n"
    if fields["トーン"]:
        draft_section += f"**トーン:** {fields['トーン']}\n"
    if fields["伝えたいこと"]:
        draft_section += f"\n**物語を通じて伝えたいメッセージ:**\n{fields['伝えたいこと']}\n"
    if fields["エピソード"]:
        draft_section += f"\n**物語の種になるエピソード（これはあくまで着想。そのまま使わず、架空の物語に変換すること）:**\n{fields['エピソード']}\n"
    if fields["読後感"]:
        draft_section += f"\n**読後に残したい感情:** {fields['読後感']}\n"
    
    prompt = f"""
{FICTION_SYSTEM_PROMPT}

{context}

{draft_section}

### 指示
上記の素材をもとに、完全なフィクション短編小説を1本執筆してください。
登場人物は全員架空の人物にし、実在の人物・企業・サービス名は一切使わないでください。
草案のテーマやメッセージは物語に反映させつつも、個人を特定できない創作物にしてください。
"""
    
    print("📝 フィクション短編を生成中...")
    json_text = call_gemini_api(prompt)
    return json.loads(json_text)


def save_essay(essay_data: Dict[str, Any], source_file: str) -> tuple:
    """生成されたエッセイをファイルに保存する。"""
    if not os.path.exists(BLOG_READY_DIR):
        os.makedirs(BLOG_READY_DIR)
    
    date_str = datetime.now().strftime('%Y%m%d')
    title = essay_data.get("title", "無題")
    
    # ファイル名をサニタイズ
    import re
    safe_title = re.sub(r'[\\/*?:"<>|]', '', title)[:50]
    
    # Markdown記事の保存
    md_filename = f"{date_str}_{safe_title}.md"
    md_path = os.path.join(BLOG_READY_DIR, md_filename)
    
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(essay_data.get("body", ""))
    
    # メタデータの保存
    meta_filename = f"{date_str}_{safe_title}.json"
    meta_path = os.path.join(BLOG_READY_DIR, meta_filename)
    
    meta = {
        "title": title,
        "description": essay_data.get("description", ""),
        "categories": essay_data.get("categories", []),
        "estimated_read_time": essay_data.get("estimated_read_time", ""),
        "source_file": source_file,
        "generated_at": datetime.now().isoformat()
    }
    
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    
    print(f"✅ エッセイを保存しました: {md_path}")
    print(f"✅ メタデータを保存しました: {meta_path}")
    
    return md_path, meta_path


def publish_to_hatena(md_path: str, meta_path: str):
    """はてなブログに下書き投稿する。"""
    cmd = ["python3", HATENA_PUBLISHER_SCRIPT, md_path, "--meta", meta_path]
    print("🚀 はてなブログへの投稿を開始...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"⚠️ はてなブログへの投稿に失敗しました (returncode={result.returncode})")
    else:
        print("✅ はてなブログへの投稿が完了しました")


def main():
    parser = argparse.ArgumentParser(description="ポメラ草案 → 1話完結エッセイ → はてなブログ投稿")
    parser.add_argument("input_file", help="草案テキストファイルのパス")
    parser.add_argument("--skip-publish", action="store_true", help="はてなブログへの投稿をスキップ")
    parser.add_argument("--master-graph", default=MASTER_GRAPH_PATH, help="ナレッジグラフのパス")
    
    args = parser.parse_args()
    
    # 1. 草案の読み込み
    try:
        import unicodedata
        args.input_file = unicodedata.normalize('NFC', args.input_file)
        with open(args.input_file, "r", encoding="utf-8") as f:
            draft_text = f.read()
    except FileNotFoundError:
        print(f"❌ ファイルが見つかりません: {args.input_file}")
        return
    
    if not draft_text.strip():
        print("❌ 草案が空です。")
        return
    
    print(f"📄 草案を読み込みました: {args.input_file}")
    print(f"   文字数: {len(draft_text)}")
    
    # 2. ナレッジグラフからコンテキストを取得
    context = ""
    graph = load_knowledge_graph()
    if graph:
        context = extract_relevant_context(graph)
        print(f"📊 ナレッジグラフからコンテキストを抽出しました")
    
    # 3. フィクション短編を生成
    try:
        essay_data = generate_fiction(draft_text, context)
        print(f"✨ 短編生成完了: 「{essay_data.get('title', '無題')}」")
    except Exception as e:
        print(f"❌ 短編生成中にエラー: {e}")
        return
    
    # 4. ファイルに保存
    md_path, meta_path = save_essay(essay_data, args.input_file)
    
    # 5. はてなブログに投稿
    if not args.skip_publish:
        publish_to_hatena(md_path, meta_path)
    else:
        print("⏭️ はてなブログへの投稿はスキップされました")


if __name__ == "__main__":
    main()
