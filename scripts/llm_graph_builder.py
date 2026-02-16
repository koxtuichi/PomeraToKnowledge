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
        def load_graph(path): return {"@context": {}, "@type": "KnowledgeGraph", "nodes": [], "edges": [], "metadata": {}}
        def merge_graphs(master, daily):
             # Simple merge for dummy implementation
             master["nodes"].extend(daily.get("nodes", []))
             master["edges"].extend(daily.get("edges", []))
             return master

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
  "type": "Select from: [self, person, event, task, place, project, emotion, insight, concept, goal, diary]",
  "detail": "Brief description or context (Japanese)",
  "sentiment": "Float from -1.0 (Negative) to 1.0 (Positive). Optional.",
  "status": "String. For Tasks/Goals: [Active, Completed, Dropped]. For Events: [Scheduled, Completed, Skipped]. Default: None.",
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
- `Task::Task Name` or `To-Do::Task Name` -> Create a Node of type `task` with status `Active`.
    - If the text says "done", "completed", "finished" in context, set status to `Completed`.
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

RESOLUTION_SYSTEM_PROMPT = """
You are a Data Consistency Expert.
Your task is to identify semantic duplicates between a list of "New Nodes" and "Existing Nodes" in a Knowledge Graph.

### Rules
1. **Strict Semantic Matching**: Only match nodes that refer to the EXACT SAME concept, entity, or event, despite minor wording differences.
   - Example 1: "GitHub Actionsの制約" (New) == "GitHub Actionsの制限" (Existing) -> MATCH
   - Example 2: "ポメラDM250" (New) == "ポメラ" (Existing) -> NO MATCH (Specific vs General) -> UNLESS context implies identity.
   - Example 3: "妻" (New) == "さやか" (Existing) -> MATCH (if context establishes this).
   - Example 4: "Monster Design" (New) == "Monster Design Practice" (Existing) -> MATCH

2. **Output Format**: JSON object mapping { "new_node_id": "existing_node_id" }.
   - Only include pairs where a match is found.
   - If no matches, return generic empty JSON `{}`.
   - The key is the ID of the NEW node, the value is the ID of the EXISTING node.

3. Consider node 'type' as a strong hint. Distinct types (e.g., Place vs Person) usually don't match.
"""

ANALYSIS_SYSTEM_PROMPT = """
Analysis Guidelines
1. **Be a "Running Partner"**: You are not just summarizing. You are running alongside the user, updating the mental model of their life.
2. **Update the Big Picture**: How does today's entry shift the trajectory of their Active Goals?
3. **Connect the Dots**: Explicitly link today's events/thoughts to nodes from the past (Existing Context).
   - "This reminds me of [Event X] two days ago..."
   - "This solves the blocker [Barrier Y] you mentioned..."
4. **No "Weekly" or "Monthly" framing**: Always speak to the *NOW* and the *IMMEDIATE FUTURE*, based on the accumulated past.

### Structure of Your Response
Output two distinct parts separated by the delimiter `===DETAILS===`.

**Part 1: Coach's Comment (The "Hook")**
- A concise, warm, and impactful message (3-5 sentences).
- Focus on the most significant shift or insight from today's update.

`===DETAILS===`

**Part 2: Integrated Analysis (The "Body")**
- A cohesive narrative that weaves today's new info into the existing Knowledge Graph.
- Discuss **Goals** (Progress/Stalls), **Patterns** (Cognitive/Behavioral), and **Next Actions**.
- Use bold text for key insights.

### Final Output Requirement
Return the text in the format:
[Part 1 Text]
===DETAILS===
[Part 2 Text]

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
        if "candidates" in result and result["candidates"]:
             return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
             print(f"DEBUG: Empty candidates in response: {result}")
             return "{}" # Return empty JSON string fallback
    except (KeyError, IndexError):
        raise Exception(f"Unexpected API response format: {result}")

def resolve_semantic_duplicates(daily_graph: Dict[str, Any], master_graph: Dict[str, Any]) -> Dict[str, Any]:
    """Identifies and merges semantic duplicates using LLM."""
    print("🔍 Checking for semantic duplicates with Master Graph...")
    
    daily_nodes = daily_graph.get("nodes", [])
    master_nodes = master_graph.get("nodes", [])
    
    if not master_nodes or not daily_nodes:
        return daily_graph
        
    # Optimization: Filter to mergeable types
    mergeable_types = {'project', 'concept', 'goal', 'emotion', 'insight', 'event', 'person', 'place'}
    
    new_candidates = [n for n in daily_nodes if n.get('type') in mergeable_types]
    if not new_candidates:
        return daily_graph
        
    master_candidates = [n for n in master_nodes if n.get('type') in mergeable_types]
    if not master_candidates:
        return daily_graph
        
    # Create summarized lists for LLM (limit tokens)
    # If master list is too huge, we might need vector search (future work).
    # For now, we take unique labels.
    
    new_list_str = "\n".join([f"- {n['id']} ({n.get('type')}): {n.get('label')}" for n in new_candidates])
    master_list_str = "\n".join([f"- {n['id']} ({n.get('type')}): {n.get('label')}" for n in master_candidates])
    
    # Send to LLM
    prompt = f"""
    {RESOLUTION_SYSTEM_PROMPT}

    ### New Nodes (Daily)
    {new_list_str}

    ### Existing Nodes (Master)
    {master_list_str}
    
    Return JSON mapping.
    """
    
    try:
        json_text = call_gemini_api(prompt, model="gemini-2.0-flash", response_mime_type="application/json")
        mapping = json.loads(json_text)
        
        if not mapping:
            print("✅ No duplicates found.")
            return daily_graph
            
        print(f"🔄 Found {len(mapping)} semantic duplicates. Merging...")
        for new_id, existing_id in mapping.items():
            print(f"   - {new_id} -> {existing_id}")
            
            # Update Daily Graph IDs
            # 1. Update Nodes
            for n in daily_graph.get("nodes", []):
                if n['id'] == new_id:
                    n['id'] = existing_id
                    # We keep the new label/detail? Let graph_merger handle property merge.
                    # Ideally, we adopt the existing ID so graph_merger treats it as an UPDATE.
                    
            # 2. Update Edges
            for e in daily_graph.get("edges", []):
                if e['source'] == new_id: e['source'] = existing_id
                if e['target'] == new_id: e['target'] = existing_id
                
        return daily_graph

    except Exception as e:
        print(f"⚠️ Semantic resolution failed: {e}. Proceeding without resolution.")
        return daily_graph

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
    # Deprecated: Using master graph directly now
    pass

def analyze_updated_state(master_graph: Dict[str, Any], current_diary_node: Dict[str, Any]) -> str:
    """Analyzes the FULL updated state of the user."""
    
    # Extract relevant context (simplify to avoid token overflow)
    # 1. Active Goals
    active_goals = [n for n in master_graph.get("nodes", []) if n.get("type") == "goal" and n.get("status") == "Active"]
    
    # 2. Recent Insights (last 7 days?)
    recent_insights = sorted(
        [n for n in master_graph.get("nodes", []) if n.get("type") == "insight"],
        key=lambda x: x.get("last_seen", ""), reverse=True
    )[:10]
    
    # 3. Recent Scheduled Events
    scheduled_events = [n for n in master_graph.get("nodes", []) if n.get("type") == "event" and n.get("status") == "Scheduled"]

    # 4. Pending Tasks (New Logic)
    # Extract tasks that are NOT completed
    pending_tasks = [n for n in master_graph.get("nodes", []) if n.get("type") == "task" and n.get("status") != "Completed"]
    
    # 5. Recent Diary Context (Consolidated View)
    # Find last 5 diary nodes
    all_diary_nodes = sorted(
        [n for n in master_graph.get("nodes", []) if n.get("type") == "diary"],
        key=lambda x: x.get("date", ""), reverse=True
    )[:5] # Last 5 entries including today

    recent_diary_context = "### Recent Diary Flow (Consolidated)\n"
    if not all_diary_nodes:
        recent_diary_context += "No recent diary entries found.\n"
    else:
        for d_node in all_diary_nodes:
            d_date = d_node.get("date", "Unknown")
            d_id = d_node.get("id")
            
            # Find nodes mentioned by this diary
            mentioned_nodes = []
            for edge in master_graph.get("edges", []):
                if edge.get("source") == d_id and edge.get("relationship") == "MENTIONS":
                    target_id = edge.get("target")
                    target_node = next((n for n in master_graph.get("nodes", []) if n["id"] == target_id), None)
                    if target_node:
                        mentioned_nodes.append(f"{target_node.get('label')} ({target_node.get('type')})")
            
            mentions_str = ", ".join(mentioned_nodes) if mentioned_nodes else "No specific mentions."
            recent_diary_context += f"- **{d_date}**: {mentions_str}\n"

    
    context_summary = "### Current Life Context\n"
    if active_goals:
        context_summary += "**Active Goals:**\n" + "\n".join([f"- {n.get('label')}: {n.get('detail')}" for n in active_goals]) + "\n"
    if recent_insights:
        context_summary += "**Recent Insights:**\n" + "\n".join([f"- {n.get('label')}" for n in recent_insights]) + "\n"
    if scheduled_events:
        context_summary += "**Upcoming Events:**\n" + "\n".join([f"- {n.get('date')} {n.get('label')}" for n in scheduled_events]) + "\n"
    if pending_tasks:
        context_summary += "**Pending Tasks (To-Do):**\n" + "\n".join([f"- {n.get('label')}" for n in pending_tasks]) + "\n"
        
    prompt = f"""
    {ANALYSIS_SYSTEM_PROMPT}

    {context_summary}

    {recent_diary_context}

    ### Today's New Entry Data
    {json.dumps(current_diary_node, ensure_ascii=False, indent=2)}
    
    ### Task
    Based on the "Recent Diary Flow" above (which includes today and previous days), provide a **SINGLE consolidated advice** that addresses the user's ongoing situation and trajectory. 
    Do not analyze just today in isolation. Connect the dots across the recent days (e.g., 2/14 -> 2/15 -> 2/16).
    """
    print("🔄 Analyzing updated state (Consolidated)...")
    return call_gemini_api(prompt, model="gemini-2.0-flash")

def main():
    parser = argparse.ArgumentParser(description="Pomera Diary to Knowledge Graph & Analysis")
    parser.add_argument("input_file", help="Path to the daily diary text file")
    parser.add_argument("--output_graph", default="daily_graph.json", help="Output path for Daily Graph JSON")
    parser.add_argument("--master_graph", default="knowledge_graph.jsonld", help="Path to Master Graph JSON-LD")
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
    try:
        master_graph = graph_merger.load_graph(args.master_graph)
    except Exception as e:
        print(f"⚠️ Failed to load master graph, initializing new one: {e}")
        master_graph = {
            "@context": {
                "nodes": { "@id": "http://schema.org/thing", "@container": "@set" },
                "edges": { "@id": "http://schema.org/link", "@container": "@set" }
            },
            "@type": "KnowledgeGraph",
            "nodes": [],
            "edges": [],
            "metadata": {}
        }
    master_context_str = get_master_context(master_graph)

    # 3. Extract Daily Graph
    try:
        import unicodedata
        # Normalize to NFC to handle macOS filename differences
        args.input_file = unicodedata.normalize('NFC', args.input_file)
        
        daily_graph = extract_graph(diary_text)
        
        # Meta data
        # Try to extract date from filename first, else use today
        import re
        filename_date = None
        # Pattern for "20260216_POMERA2026年2月15日.txt" -> Extract 2026年2月15日 part and convert
        # Or simpler: just looks for YYYY-MM-DD or YYYYMMDD in filename if available
        # But user format is specific: YYYYMMDD_POMERA(Date)
        
        # Attempt to parse specific format "POMERAyyyy年m月d日"
        match = re.search(r'POMERA(\d{4})年(\d{1,2})月(\d{1,2})日', args.input_file)
        if match:
            y, m, d = match.groups()
            current_date_str = f"{y}-{int(m):02d}-{int(d):02d}"
            print(f"📅 Extracted Date from Filename: {current_date_str}")
        else:
            # Fallback to today
            current_date_str = datetime.now().strftime("%Y-%m-%d")
            print(f"⚠️ Could not extract date from filename '{args.input_file}'. Using today: {current_date_str}")

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

        # --- NEW: Semantic Deduplication ---
        daily_graph = resolve_semantic_duplicates(daily_graph, master_graph)

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


    # 5. Analyze with Context (Now using Updated Master)
    try:
        # Identify the diary node we just added/updated
        diary_node_id = f"diary:{current_date_str}"
        current_diary_node = next((n for n in updated_master.get("nodes", []) if n["id"] == diary_node_id), None)
        
        if current_diary_node:
            analysis_text = analyze_updated_state(updated_master, current_diary_node)
            
            # Save Report
            with open(args.output_report, "w", encoding="utf-8") as f:
                f.write(f"# 最新分析レポート ({datetime.now().date()})\n\n")
                f.write(f"**分析対象:** {current_date_str} の更新および全期間のコンテキスト\n\n")
                f.write(analysis_text)
            print(f"✅ 分析レポートを保存しました: {args.output_report}")
            
            # Inject into graph
            current_diary_node["analysis_content"] = analysis_text
            
            # Re-save Master
            with open(args.master_graph, "w", encoding="utf-8") as f:
                json.dump(updated_master, f, ensure_ascii=False, indent=2)
            print(f"✅ グラフの {diary_node_id} に最新分析結果を統合しました")
            
        else:
            print("⚠️ Diary node not found in updated master. Skipping analysis.")

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

