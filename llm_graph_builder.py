import os
import json
import argparse
from datetime import datetime
import requests
from typing import Dict, Any, List

# Local Import (Assuming graph_merger.py is in the same directory)
try:
    import graph_merger
except ImportError:
    # For standalone testing or different path structures, provide a dummy
    print("⚠️  graph_merger module not found. Persistence features will be limited.")
    class text_merger:
        def load_graph(path): return {"nodes": [], "edges": [], "metadata": {}}
        def merge_graphs(master, daily): return daily

# ── 設定 ──
# export GOOGLE_API_KEY="your-api-key"
API_KEY = os.getenv("GOOGLE_API_KEY")

# ── プロンプト定義 ──

EXTRACTION_SYSTEM_PROMPT = """
You are an expert Knowledge Graph Engineer and Psychologist.
Your goal is to convert the user's diary entry into a structured Knowledge Graph in JSON-LD compatible format.

### Target Schema (JSON)
The output must be a single JSON object with "nodes" and "edges" arrays.

#### Node Structure
{
  "id": "unique_id (e.g., person:name, event:name, insight:summary)",
  "label": "Display Name (Japanese)",
  "type": "Select from: [self, person, event, place, project, emotion, insight, concept, goal, diary]",
  "detail": "Brief description or context (Japanese)",
  "sentiment": "Float from -1.0 (Negative) to 1.0 (Positive). Optional.",
  "status": "String. For Goals: [Active, Completed, Dropped]. For Events: [Scheduled, Completed, Skipped]. Default: None.",
  "date": "ISO8601 Date String (YYYY-MM-DD). Required for 'Scheduled' events.",
  "tags": ["Array of strings. e.g., 'Cognitive Distortion: All-or-Nothing', 'Growth', 'Conflict']",
  "community": "Integer (0-10) for clustering topics. Optional."
}

#### Edge Structure
{
  "source": "source_node_id",
  "target": "target_node_id",
  "type": "Select from: [MENTIONS, AT, PARTICIPATES, ABOUT, CAUSAL, DISCOVERS, FEELING, TRIGGERED_BY, EVOLVED_TO, CONFLICTS_WITH, SOLVES, BARRIER, PLANS, TARGETS]",
  "label": "Short description of the relationship (Japanese)"
}

### Analysis Guidelines
1. **Implicit Causality**: Identify causal links (e.g., A triggered B). Use type "CAUSAL" or "TRIGGERED_BY".
2. **Cognitive Distortions (CBT)**: If the user shows negative thought patterns (e.g., "I always fail"), tag the node with "Cognitive Distortion: [Type]".
3. **Sentiment**: Assign sentiment scores based on the emotional tone.
4. **Knowledge Clusters**: Group related nodes into communities (e.g., Work=1, Family=2, Health=3).

### Special Tag Parsing (User Constraints)
The user utilizes specific tags in the text. You MUST parse them as follows:
- `予定::YYYY/MM/DD Event Name` -> Create a Node of type `event` with status `Scheduled` and property `date`.
    - Edge: `person:self` -> `PLANS` -> `event:node_id`
- `目標::Goal Name` -> Create a Node of type `goal` with status `Active`.
    - Edge: `person:self` -> `TARGETS` -> `goal:node_id`
- **Other `Key::Value` Tags**:
    - Treat `Key` as the relationship type (or a hint for it) and `Value` as the node content.
    - Example: `気分::最高` -> Create `emotion` node "最高", Edge: `person:self` --[FEELING]--> `emotion:最高`.
    - Example: `アイデア::アプリ案` -> Create `idea` (or `concept`) node "アプリ案", Edge: `person:self` --[DISCOVERS]--> `concept:アプリ案`.

### Output Requirements
**IMPORTANT: All "label" and "detail" fields in nodes and edges MUST be in Japanese.**
"""

ANALYSIS_SYSTEM_PROMPT = """
You are a wise and empathetic Psychologist/Philosopher who is deeply engaged in a dialogue with the user.
Your goal is to provide deep, meaningful insights based on the user's diary and past behavior, using a natural, conversational tone.

### Key Guidelines (CRITICAL)
1. **NO STRUCTURED FORMAT**: Do NOT use bullet points, numbered lists, bold headers, or sections like "Plan vs Actual".
2. **NATURAL NARRATIVE**: Write as a continuous stream of thought, like a letter or a deep conversation. Segue naturally between topics.
3. **PSYCHOLOGICAL DEPTH**: Weave specific psychological frameworks (CBT, Self-Determination Theory, Network Theory) into the narrative WITHOUT explicitly naming them as headers.
    - Instead of "Cognitive Distortion: All-or-Nothing", say "It seems you might be falling into the trap of thinking it has to be perfect or nothing at all..."
4. **CONNECTION**: Explicitly connect today's events with past patterns (Master Context). Show the user you remember their history.
5. **TONE**: Professional yet intimate, intellectual yet accessible. Avoid robotic or overly enthusiastic "AI" tones.

### Input Context
You will see:
1. **Daily Graph**: Today's graph data.
2. **Master Context**: Past active goals and scheduled events.

### Structure of Your Response (Hidden)
Although the output should NOT look structured, mentally organize your response as follows:
1. **Empathy & Validation**: Acknowledge the day's feeling and events.
2. **Pattern Recognition**: Connect specific actions to past behaviors or psychological tendencies (Meta-Cognition).
3. **Deep Insight**: Offer a core realization or reframing of the situation.
4. **Gentle Nudge**: Suggest a subtle shift in perspective or action for tomorrow (Context-Aware Advice).

### Final Output Requirement
Return ONLY the narrative text. No markdown formatting for structure (except casual paragraphs).
Language: Japanese.
"""

def call_gemini_api(prompt: str, model: str = "gemini-2.0-flash", response_mime_type: str = "text/plain") -> str:
    if not API_KEY:
        raise ValueError("GOOGLE_API_KEY is not set.")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    params = {"key": API_KEY}
    
    headers = {"Content-Type": "application/json"}
    
    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
         "generationConfig": {
            "response_mime_type": response_mime_type
        }
    }
    
    response = requests.post(url, headers=headers, json=data, params=params)
    
    if response.status_code != 200:
        raise Exception(f"API Error: {response.status_code} - {response.text}")
        
    result = response.json()
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise Exception(f"Unexpected API response format: {result}")

def extract_graph(text: str) -> Dict[str, Any]:
    prompt = f"""
    {EXTRACTION_SYSTEM_PROMPT}

    ### User Diary Entry
    {text}
    """
    print("🔄 Extracting graph...")
    json_text = call_gemini_api(prompt, model="gemini-3-flash-preview", response_mime_type="application/json")
    return json.loads(json_text)

def get_master_context(master_graph: Dict[str, Any]) -> str:
    """Extracts relevant context (Active Goals, Recent Scheduled Events) from Master Graph."""
    nodes = master_graph.get("nodes", [])
    
    active_goals = [n for n in nodes if n.get("type") == "goal" and n.get("status") == "Active"]
    scheduled_events = [n for n in nodes if n.get("type") == "event" and n.get("status") == "Scheduled"]
    
    # Sort events by date (if available) - simplified for now
    context_str = "### Master Graph Context (Past State)\n"
    
    if active_goals:
        context_str += "**Active Goals:**\n"
        for g in active_goals:
            context_str += f"- {g.get('label')}: {g.get('detail')}\n"
    
    if scheduled_events:
        context_str += "\n**Scheduled Events (Future/Pending):**\n"
        for e in scheduled_events:
             date = e.get("date", "Unknown Date")
             context_str += f"- [{date}] {e.get('label')}: {e.get('detail')}\n"
             
    if not active_goals and not scheduled_events:
        context_str += "No active goals or scheduled events found in history.\n"
        
    return context_str

def analyze_graph_with_context(daily_graph: Dict[str, Any], master_context: str) -> str:
    prompt = f"""
    {ANALYSIS_SYSTEM_PROMPT}

    {master_context}

    ### Today's Graph Data (JSON)
    {json.dumps(daily_graph, ensure_ascii=False, indent=2)}
    """
    print("🔄 Analyzing graph with context...")
    return call_gemini_api(prompt, model="gemini-3-flash-preview")

def main():
    parser = argparse.ArgumentParser(description="Pomera Diary to Knowledge Graph & Analysis")
    parser.add_argument("input_file", help="Path to the daily diary text file")
    parser.add_argument("--output_graph", default="daily_graph.json", help="Output path for Daily Graph JSON")
    parser.add_argument("--master_graph", default="master_graph.json", help="Path to Master Graph JSON")
    parser.add_argument("--output_report", default="daily_report.md", help="Output path for Analysis Report")
    
    args = parser.parse_args()

    # 1. Load Diary
    try:
        with open(args.input_file, "r", encoding="utf-8") as f:
            diary_text = f.read()
    except FileNotFoundError:
        print(f"❌ Input file not found: {args.input_file}")
        return

    # 2. Load Master Graph (for Context & Merging)
    print(f"📂 Loading Master Graph: {args.master_graph}")
    master_graph = graph_merger.load_graph(args.master_graph)
    master_context_str = get_master_context(master_graph)

    # 3. Extract Daily Graph
    try:
        daily_graph = extract_graph(diary_text)
        
        # Meta data
        current_date_str = datetime.now().strftime("%Y-%m-%d")
        daily_graph["metadata"] = {
            "generated_at": datetime.now().isoformat(),
            "source_file": args.input_file,
            "node_count": len(daily_graph.get("nodes", [])),
            "edge_count": len(daily_graph.get("edges", []))
        }

        # Add a diary node if not already present (for today's entry)
        diary_node_id = f"diary:{current_date_str}"
        if not any(node.get("id") == diary_node_id for node in daily_graph.get("nodes", [])):
            daily_graph.get("nodes", []).append({
                "id": diary_node_id,
                "label": f"{current_date_str}の日記",
                "type": "diary",
                "date": current_date_str,
                "detail": "今日の日記エントリ",
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "weight": 1
            })

        # --- ENFORCE CONNECTIVITY (User -> Diary -> Entities) ---
        user_node_id = "person:self"
        
        # 1. Ensure User Node Exists
        if not any(node.get("id") == user_node_id for node in daily_graph.get("nodes", [])):
            daily_graph.get("nodes", []).append({
                "id": user_node_id,
                "label": "自分",
                "type": "self",
                "detail": "日記の作成者",
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "weight": 1
            })

        # 2. Connect User -> Diary
        daily_graph.get("edges", []).append({
             "source": user_node_id,
             "target": diary_node_id,
             "relationship": "WROTE",
             "weight": 1
        })

        # 3. Connect Diary -> All Other Nodes (that are not User or Diary)
        # This ensures no node is left isolated
        for node in daily_graph.get("nodes", []):
            nid = node.get("id")
            if nid == user_node_id or nid == diary_node_id:
                continue
            
            # Check if edge already exists (to avoid double linking if LLM already extracted it)
            # Simplified check: just checking source/target pair
            edge_exists = any(
                (e.get("source") == diary_node_id and e.get("target") == nid) or
                (e.get("source") == nid and e.get("target") == diary_node_id)
                for e in daily_graph.get("edges", [])
            )
            
            if not edge_exists:
                daily_graph.get("edges", []).append({
                    "source": diary_node_id,
                    "target": nid,
                    "relationship": "MENTIONS",
                    "weight": 1
                })

        # 4. Save Daily Graph JSON
        with open(args.output_graph, "w", encoding="utf-8") as f:
            json.dump(daily_graph, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"❌ Error during extraction: {e}")
        return

    # 5. Merge into Master Graph
    print("🔄 Merging into Master Graph...")
    updated_master = None
    try:
        # Load the daily graph again
        with open(args.output_graph, "r", encoding="utf-8") as f:
            daily_graph_for_merge = json.load(f)
        
        updated_master = graph_merger.merge_graphs(master_graph, daily_graph_for_merge)
        
        # Save Master Graph
        with open(args.master_graph, "w", encoding="utf-8") as f:
            json.dump(updated_master, f, ensure_ascii=False, indent=2)
        print(f"✅ マスターグラフを更新しました: {args.master_graph}")
        
    except Exception as e:
        print(f"❌ マージ中にエラーが発生しました: {e}")
        # Fallback: Use daily graph mixed with master context for analysis if merge fails
        updated_master = master_graph


    # 5. Analyze with Context
    try:
        analysis_text = analyze_graph_with_context(daily_graph, master_context_str)
        
        # Save Report
        with open(args.output_report, "w", encoding="utf-8") as f:
            f.write(f"# 日次分析レポート ({datetime.now().date()})\n\n")
            f.write(f"**対象ファイル: {os.path.basename(args.input_file)}**\n\n")
            f.write(analysis_text)
            
            # --- CUMULATIVE SUMMARY (If multiple entries today) ---
            # Search master graph for nodes created today
            today_entities = [n for n in updated_master.get("nodes", []) 
                             if n.get("last_seen", "").startswith(datetime.now().strftime("%Y-%m-%d"))]
            if len(today_entities) > 5: # Some reasonable threshold for "has context"
                f.write("\n\n---\n## 本日の累積インサイト\n")
                f.write("※本日複数の更新がありました。これまでの情報を統合した状況です。\n")
                # Briefly list key interests found today
                interests = [n.get("label") for n in today_entities if n.get("type") not in ["diary", "self"]]
                f.write(f"- **主な関心事:** {', '.join(interests[:10])}\n")

        print(f"✅ 分析レポートを保存しました: {args.output_report}")
        
    except Exception as e:
        print(f"❌ 分析中にエラーが発生しました: {e}")

    # 6. Update Visualization (index.html)
    try:
        html_path = "index.html"
        if os.path.exists(html_path):
            update_html_visualization(html_path, updated_master)
            print(f"✅ 可視化画面を更新しました: {html_path}")
        else:
            print(f"⚠️  {html_path} が見つかりません。可視化の更新をスキップします。")
    except Exception as e:
        print(f"❌ 可視化更新中にエラーが発生しました: {e}")

def update_html_visualization(html_path: str, graph_data: Dict[str, Any]):
    """Injects the graph data into the GRAPH_DATA variable in index.html using markers"""
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        start_marker = "// GRAPH_DATA_START"
        end_marker = "// GRAPH_DATA_END"
        
        start_idx = html_content.find(start_marker)
        end_idx = html_content.find(end_marker)
        
        if start_idx != -1 and end_idx != -1:
            # Create the new data block
            new_block = f"{start_marker}\n    const GRAPH_DATA = {json.dumps(graph_data, ensure_ascii=False, indent=2)};\n    "
            
            # Replace content between start_idx and end_idx (keeping the end marker)
            new_html = html_content[:start_idx] + new_block + html_content[end_idx:]
            
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(new_html)
            print(f"✅ 可視化画面を更新しました: {html_path}")
        else:
            print(f"⚠️ マーカーが見つかりません: {html_path}. 修復スクリプトを実行してください...")
            print(f"{html_path} に {start_marker} と {end_marker} が含まれているか確認してください")

    except Exception as e:
        print(f"❌ HTML更新エラー: {e}")

if __name__ == "__main__":
    main()

