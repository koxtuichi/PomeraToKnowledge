import json
import os
import sys
import argparse
from datetime import datetime, timedelta
import google.generativeai as genai
from typing import Dict, Any

# Local Import
try:
    import graph_merger
except ImportError:
    print("⚠️  graph_merger module not found. Persistence features will be limited.")
    sys.exit(1)

# Load environment variables
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    # Try alternate name just in case
    api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ GOOGLE_API_KEY not found in environment variables.")
    print("Please export GOOGLE_API_KEY='your_key_here'")
    sys.exit(1)

genai.configure(api_key=api_key)

MASTER_GRAPH_FILE = "master_graph.json"
WEEKLY_REPORT_FILE = "weekly_review_{date}.md"
HTML_FILE = "index.html"

SYSTEM_PROMPT = """
あなたは熟練したライフコーチ兼データアナリストです。あなたの任務は、過去1週間のユーザーの日記とナレッジグラフデータに基づいて、「週次レビュー（Weekly Review）」を作成することです。

## 入力データ
1. **日次サマリー**: 過去1週間の日々の分析の要約。
2. **主要エンティティ**: この期間に言及された重要な人物、プロジェクト、目標。
3. **感情トレンド**: 感情スコアの推移。

## 出力フォーマット (Markdown)
以下の構成でレポートを作成してください（すべて日本語で）。

# 週次レビュー: [開始日] - [終了日]

## 1. 📈 ハイライトとトレンド
- **感情の推移**: ユーザーの気分はどう変化しましたか？（例：「週の初めは高かったが、中頃にXの影響で落ち込み、週末に回復した」）
- **主要イベント**: 今週最も影響力のあった1〜3つの出来事。
- **最大の成果 (Big Wins)**: 何が最大の達成でしたか？

## 2. 🎯 ゴール進捗分析
- 現在のアクティブな戦略とその結果をレビューします。
- **特定されたブロッカー**: 進捗を妨げた繰り返される課題は何ですか？
- **特定されたブースター**: 一貫して高い感情や生産性をもたらした活動は何ですか？

## 3. 💡 インサイトとパターン認識
- 一見無関係に見える出来事の間の点と点を繋げてください。
- 頻繁に現れた「認知の歪み」があれば指摘してください。

## 4. 🚀 来週の戦略 (Future Action)
- 次週に向けた具体的なフォーカスエリアを3つ提案してください。
- 試すべき具体的な「行動変容」を1つ提案してください（例：「夜ではなく朝に書く」など）。

## トーン
支持的で、分析的かつ客観的であること。読みやすくするために箇条書き（Bullet Points）を使用してください。
"""

def load_master_graph():
    if not os.path.exists(MASTER_GRAPH_FILE):
        print(f"❌ Master graph not found: {MASTER_GRAPH_FILE}")
        sys.exit(1)
    with open(MASTER_GRAPH_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_weekly_context(graph, target_date_str, days=7):
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
    start_date = target_date - timedelta(days=days-1)
    
    print(f"📅 Analyzing range: {start_date.strftime('%Y-%m-%d')} to {target_date_str}")

    daily_nodes = []
    key_entities = []
    sentiments = []

    # 1. Filter Diary Nodes
    for node in graph.get("nodes", []):
        if node["type"] == "diary" and node.get("date"):
            try:
                node_date = datetime.strptime(node["date"], "%Y-%m-%d")
                if start_date <= node_date <= target_date:
                    daily_nodes.append(node)
                    if node.get("sentiment"):
                        sentiments.append(f"{node['date']}: {node['sentiment']}")
            except ValueError:
                continue

    # 2. Find Associated Entities (mentions in this period)
    # We look for edges connected to these diary nodes
    diary_ids = set(n["id"] for n in daily_nodes)
    related_node_ids = set()
    
    for edge in graph.get("edges", []):
        if edge["source"] in diary_ids:
            related_node_ids.add(edge["target"])
        elif edge["target"] in diary_ids:
            related_node_ids.add(edge["source"])

    for node in graph.get("nodes", []):
        if node["id"] in related_node_ids and node["type"] not in ["diary", "self"]:
            key_entities.append(f"- {node['label']} ({node['type']}): {node.get('detail', '')}")

    # Sort daily nodes by date
    daily_nodes.sort(key=lambda x: x["date"])

    context = f"## Period: {start_date.strftime('%Y-%m-%d')} to {target_date_str}\n\n"
    
    context += "## Daily Summaries\n"
    if not daily_nodes:
        context += "(No diary entries found for this period)\n"
    else:
        for n in daily_nodes:
            summary = n.get("analysis_content", "No analysis available").split("\n")[0:5] # Take first few lines
            context += f"### {n['date']} (Sentiment: {n.get('sentiment', 0)})\n"
            context += "Summary: " + "\n".join(summary) + "\n...\n\n"

    context += "## Key Entities Mentioned\n"
    context += "\n".join(key_entities[:20]) # Limit to top 20 to avoid context overflow
    
    context += "\n## Sentiment History\n"
    context += "\n".join(sentiments)

    return context, daily_nodes

def generate_report(context):
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    try:
        response = model.generate_content(SYSTEM_PROMPT + "\n\n" + context)
        return response.text
    except Exception as e:
        return f"Error generating report: {e}"

def update_html_visualization(html_path: str, graph_data: Dict[str, Any]):
    """graph_data.js の GRAPH_DATA を更新する。

    index.html 本体ではなく、同じディレクトリの graph_data.js を書き換える。
    """
    import re as _re
    js_path = os.path.join(os.path.dirname(os.path.abspath(html_path)), "graph_data.js")
    try:
        # 書き込み前に基本的な整合性を確認
        if not isinstance(graph_data.get("nodes"), list):
            raise ValueError("graph_data.nodes がリストではありません")

        new_content = (
            "// GRAPH_DATA_START\n"
            f"const GRAPH_DATA = {json.dumps(graph_data, ensure_ascii=False, indent=2)};\n"
            "// GRAPH_DATA_END\n"
        )

        with open(js_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        # 書き込み後に再読みして JSON パースを確認
        with open(js_path, "r", encoding="utf-8") as f:
            written = f.read()
        m = _re.search(r"const GRAPH_DATA = (\{.*\});", written, _re.DOTALL)
        if not m:
            raise ValueError("書き込み後の graph_data.js から GRAPH_DATA を抽出できません")
        json.loads(m.group(1))

        print(f"✅ graph_data.js を更新しました: {len(graph_data['nodes'])} nodes")
    except Exception as e:
        print(f"❌ graph_data.js 更新エラー: {e}")


def save_to_graph_and_visualize(report_text, target_date_str, daily_nodes, full_graph):
    # 1. Create Weekly Review Node
    review_node_id = f"review:weekly:{target_date_str}"
    
    # Check if exists (to update or create)
    # Actually graph_merger handles updates, so we just construct a partial graph
    
    weekly_graph = {
        "nodes": [{
            "id": review_node_id,
            "label": f"週次レビュー ({target_date_str})",
            "type": "review",
            "detail": "LLMによる週次振り返りと次週の提案",
            "analysis_content": report_text,
            "date": target_date_str,
            "sentiment": 0.0, # Neutral container
            "community": 10, # Special community for reviews?
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "weight": 5 # Important node
        }],
        "edges": []
    }
    
    # 2. Link to Diary Nodes
    for diary in daily_nodes:
        weekly_graph["edges"].append({
            "source": review_node_id,
            "target": diary["id"],
            "type": "ABOUT",
            "label": "対象期間として集計",
            "weight": 1
        })
        
    # 3. Merge into Master
    print("🔄 Merging Weekly Review into Master Graph...")
    updated_master = graph_merger.merge_graphs(full_graph, weekly_graph)
    
    # 4. Save Master
    with open(MASTER_GRAPH_FILE, "w", encoding="utf-8") as f:
        json.dump(updated_master, f, indent=2, ensure_ascii=False)
        
    # 5. Update HTML
    update_html_visualization(HTML_FILE, updated_master)

def main():
    parser = argparse.ArgumentParser(description="Generate Weekly Review")
    parser.add_argument("--date", help="Target date (YYYY-MM-DD), defaults to today", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--days", type=int, default=7, help="Number of days to look back")
    parser.add_argument("--no-save", action="store_true", help="Do not save to master graph")
    args = parser.parse_args()

    graph = load_master_graph()
    context, daily_nodes = get_weekly_context(graph, args.date, args.days)
    
    print("🧠 Generating Weekly Review...")
    report = generate_report(context)
    
    filename = WEEKLY_REPORT_FILE.format(date=args.date)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"✅ Report saved to: {filename}")
    
    if not args.no_save:
        save_to_graph_and_visualize(report, args.date, daily_nodes, graph)

if __name__ == "__main__":
    main()
