import json
import os
import math
import argparse
from datetime import datetime, timezone, timedelta

# ── 感情タイプ別の減衰係数 (1日あたり) ──
# 感情が言及されない日が続くほど active_sentiment が中性値に近づく
EMOTION_DECAY_RATES = {
    "喜び": 0.30,      # 昂りは短命。1日でかなり冷める
    "達成感": 0.15,    # 数日間は充実感が残る
    "不安": 0.05,      # 解決されない限りほぼ消えない
    "怒り": 0.20,      # 早めに冷める
    "その他": 0.10,    # デフォルト
}

# ── ベクトル検索によるノード解決 ──
_EMBED_SIMILARITY_THRESHOLD = 0.85

def _cosine_similarity(a, b):
    """2つのベクトルのコサイン類似度を計算する。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_embeddings(texts):
    """Gemini Embedding APIでテキストリストのembeddingを取得する。"""
    try:
        import google.generativeai as genai
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("   ⚠️ GOOGLE_API_KEY が未設定のためベクトル検索をスキップ")
            return []
        genai.configure(api_key=api_key)
        result = genai.embed_content(
            model="models/gemini-embedding-001",
            content=texts,
        )
        return result["embedding"]
    except Exception as e:
        print(f"   ⚠️ Embedding API エラー: {e}")
        return []


def _resolve_target_by_vector(target_id, master_nodes_dict, _cache={}):
    """ベクトル検索でターゲットIDに最も意味的に近いマスターノードを探す。

    結果はキャッシュして同一マージ内での重複API呼び出しを防ぐ。
    """
    if target_id in _cache:
        return _cache[target_id]

    # ターゲットのラベル部分を抽出
    target_label = target_id.split(":", 1)[-1] if ":" in target_id else target_id
    target_type = target_id.split(":", 1)[0] if ":" in target_id else ""

    # マスターグラフの候補ノードを収集
    candidates = []
    for nid, node in master_nodes_dict.items():
        node_type = node.get("type", "")
        node_label = node.get("label", "")
        # タイプが大きく異なる場合は除外
        if target_type and target_type not in ("目標", "プロジェクト") and node_type not in ("目標", "プロジェクト", target_type):
            continue
        if target_type in ("目標", "プロジェクト") and node_type not in ("目標", "プロジェクト"):
            continue
        if node_label:
            candidates.append((nid, node_label))

    if not candidates:
        _cache[target_id] = None
        return None

    # embeddingを取得
    texts = [target_label] + [c[1] for c in candidates]
    embeddings = _get_embeddings(texts)
    if len(embeddings) < 2:
        _cache[target_id] = None
        return None

    target_emb = embeddings[0]
    best_sim = -1.0
    best_id = None
    for i, (nid, label) in enumerate(candidates):
        sim = _cosine_similarity(target_emb, embeddings[i + 1])
        if sim > best_sim:
            best_sim = sim
            best_id = nid

    if best_sim >= _EMBED_SIMILARITY_THRESHOLD:
        print(f"   🔍 ベクトル検索: '{target_label}' → '{master_nodes_dict[best_id].get('label', best_id)}' (類似度: {best_sim:.3f})")
        _cache[target_id] = best_id
        return best_id
    else:
        print(f"   ⚠️ ベクトル検索: '{target_label}' に該当なし (最大類似度: {best_sim:.3f})")
        _cache[target_id] = None
        return None

def _resolve_label_by_vector(label, node_type, master_nodes_dict, _cache={}):
    """Pass 1用: ラベルとタイプからマスターグラフ内の類似ノードをベクトル検索で探す。

    日記型ノードやタイプが大きく異なるノードは除外する。
    """
    cache_key = f"{node_type}:{label}"
    if cache_key in _cache:
        return _cache[cache_key]

    # 日記型はスキップ
    if node_type in ('日記', 'diary'):
        _cache[cache_key] = None
        return None

    # 目標とプロジェクトは相互に検索可能
    GOAL_TYPES = {'目標', 'プロジェクト', 'goal', 'project'}
    type_group_match = node_type in GOAL_TYPES

    candidates = []
    for nid, node in master_nodes_dict.items():
        n_type = node.get('type', '')
        n_label = node.get('label', '')
        if not n_label or n_type in ('日記', 'diary'):
            continue
        # タイプの整合性チェック
        if type_group_match:
            if n_type not in GOAL_TYPES:
                continue
        elif node_type and n_type != node_type:
            continue
        candidates.append((nid, n_label))

    if not candidates:
        _cache[cache_key] = None
        return None

    texts = [label] + [c[1] for c in candidates]
    embeddings = _get_embeddings(texts)
    if len(embeddings) < 2:
        _cache[cache_key] = None
        return None

    target_emb = embeddings[0]
    best_sim = -1.0
    best_id = None
    for i, (nid, clabel) in enumerate(candidates):
        sim = _cosine_similarity(target_emb, embeddings[i + 1])
        if sim > best_sim:
            best_sim = sim
            best_id = nid

    if best_sim >= _EMBED_SIMILARITY_THRESHOLD:
        print(f"   🔍 Pass1ベクトル検索: '{label}' → '{master_nodes_dict[best_id].get('label', best_id)}' (類似度: {best_sim:.3f})")
        _cache[cache_key] = best_id
        return best_id
    else:
        _cache[cache_key] = None
        return None

def load_graph(filepath):
    """Loads a graph JSON file. Returns an empty structure if file doesn't exist."""
    if not os.path.exists(filepath):
        print(f"ℹ️  Master graph not found at {filepath}. Creating new one.")
        return {"nodes": [], "edges": [], "metadata": {}}
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️  Error decoding JSON from {filepath}. Returning empty graph.")
        return {"nodes": [], "edges": [], "metadata": {}}

def _days_since(last_seen_str: str) -> int:
    """last_seen文字列から今日までの経過日数を返す。パース失敗時は0。"""
    try:
        dt = datetime.fromisoformat(last_seen_str)
        # タイムゾーンが付いていない場合はローカル扱い
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        return max(0, (now - dt).days)
    except Exception:
        return 0


def _make_edge_key_set(graph: dict) -> set:
    """グラフ内のエッジを source|target|type 形式のキーセットに変換する。"""
    keys = set()
    for e in graph.get('edges', []):
        key = f"{e.get('source', '')}|{e.get('target', '')}|{e.get('type', 'UNKNOWN')}"
        keys.add(key)
    return keys


def _calc_trend(history: list) -> str:
    """emotion_history の直近3件の active_sentiment から傾向を計算する。"""
    recent = [h.get("active_sentiment") for h in history[-3:] if h.get("active_sentiment") is not None]
    if len(recent) < 2:
        return "安定"
    diff = recent[-1] - recent[0]
    if diff > 0.05:
        return "上昇"
    elif diff < -0.05:
        return "下降"
    return "安定"


def apply_emotion_decay(master: dict, daily_node_ids: set, today_str: str) -> None:
    """感情ノードの active_sentiment を減衰させ、emotion_history に今日分を追記する。

    - 今日言及された感情ノード: active_sentiment を sentiment 水準に戻す
    - 今日言及されなかった感情ノード: emotion_category に応じた係数で減衰
    """
    for node in master.get("nodes", []):
        if node.get("type") != "感情":
            continue

        sentiment = node.get("sentiment", 0)
        active = node.get("active_sentiment", sentiment)
        category = node.get("emotion_category", "その他")
        trigger = node.get("trigger")

        if node["id"] in daily_node_ids:
            # 今日言及 → active_sentiment を sentiment 水準に戻す
            new_active = sentiment
        else:
            # 言及なし → カテゴリ別の係数で減衰。0に向かって近づく
            decay = EMOTION_DECAY_RATES.get(category, EMOTION_DECAY_RATES["その他"])
            # active_sentiment は 0 に収束 (完全に忘れる)
            new_active = round(active * (1 - decay), 4)

        node["active_sentiment"] = new_active

        # emotion_history に今日分を追記 (重複防止)
        history = node.get("emotion_history", [])
        if not any(h.get("date") == today_str for h in history):
            history.append({
                "date": today_str,
                "sentiment": sentiment,
                "active_sentiment": new_active,
                "trigger": trigger if node["id"] in daily_node_ids else None
            })
        node["emotion_history"] = history

        # peak_sentiment と trend を更新
        all_sentiments = [h["sentiment"] for h in history if h.get("sentiment") is not None]
        node["peak_sentiment"] = max(all_sentiments) if all_sentiments else sentiment
        node["trend"] = _calc_trend(history)

    active_emotions = [n for n in master.get("nodes", []) if n.get("type") == "感情"]
    print(f"💫 Emotion decay applied: {len(active_emotions)} emotion nodes updated.")


def apply_weight_decay(master: dict, daily_node_ids: set, daily_edge_keys: set) -> None:
    """今回のマージで登場しなかったノードとエッジのweightを、
    last_seenからの経過日数に応じて小刻みに減衰させる。

    - 減衰量: 0.05 / 日 (マージ未登場1回につき)
    - 下限  : 0.1
    - 日記型ノードは対象外
    """
    DECAY_PER_DAY = 0.05
    MIN_WEIGHT = 0.1
    DIARY_TYPES = {'日記', 'diary'}

    # --- ノード ---
    for node in master.get('nodes', []):
        if node.get('type') in DIARY_TYPES:
            continue
        if node['id'] in daily_node_ids:
            # 今回登場したノードは減衰しない
            continue

        missed_days = _days_since(node.get('last_seen', '')) if node.get('last_seen') else 1
        # 少なくとも今回のマージ分1回は減衰させる
        missed_days = max(1, missed_days)
        decay = DECAY_PER_DAY * missed_days
        node['weight'] = max(MIN_WEIGHT, round(node.get('weight', 1) - decay, 4))

    # --- エッジ ---
    for edge in master.get('edges', []):
        key = f"{edge.get('source', '')}|{edge.get('target', '')}|{edge.get('type', 'UNKNOWN')}"
        if key in daily_edge_keys:
            continue

        missed_days = _days_since(edge.get('last_seen', '')) if edge.get('last_seen') else 1
        missed_days = max(1, missed_days)
        decay = DECAY_PER_DAY * missed_days
        edge['weight'] = max(MIN_WEIGHT, round(edge.get('weight', 1) - decay, 4))

    # ログ
    decayed_nodes = [n for n in master.get('nodes', []) if n['id'] not in daily_node_ids and n.get('type') not in DIARY_TYPES]
    print(f"⏳ Weight decay applied: {len(decayed_nodes)} nodes / {len(master.get('edges', [])) - len(daily_edge_keys)} edges")


def merge_graphs(master, daily):
    """Merges a daily graph into the master graph."""
    
    # --- 1. Merge Nodes ---
    master_nodes = {n['id']: n for n in master.get('nodes', [])}
    
    # Map label+type to ID for duplicate detection
    # only for specific types where names should be unique identifiers
    label_map = {} 
    mergeable_types = {'人物', '場所', 'プロジェクト', '概念', '目標', '感情', '知見', 'タスク', '出来事', '制約', 'person', 'place', 'project', 'concept', 'goal', 'emotion', 'insight', 'task', 'event'}
    
    # First, build a label_map from the MASTER
    for n in master.get('nodes', []):
        if n.get('label'):
            l_key = n.get('label')
            if l_key not in label_map or n.get('type') in mergeable_types:
                label_map[l_key] = n['id']
    new_node_count = 0
    updated_node_count = 0
    id_remap = {} 

    # Pass 1: Global Label Normalization
    # Goal: Ensure every label maps to exactly ONE canonical ID (preferring Master IDs if available)
    for node in daily.get('nodes', []):
        raw_id = node['id']
        nlabel = node.get('label')
        
        if nlabel:
            if nlabel in label_map:
                # This label already exists (either in Master or established earlier in this Daily batch)
                target_id = label_map[nlabel]
                if raw_id != target_id:
                    print(f"🔄 Remapping node: {raw_id} -> {target_id} (Label: '{nlabel}')")
                    id_remap[raw_id] = target_id
                    node['id'] = target_id
            else:
                # ラベル完全一致なし → ベクトル検索でマスター内の類似ノードを探す
                ntype = node.get('type', '')
                resolved_id = _resolve_label_by_vector(nlabel, ntype, master_nodes)
                if resolved_id:
                    print(f"🔄 Remapping node (vector): {raw_id} -> {resolved_id} (Label: '{nlabel}')")
                    id_remap[raw_id] = resolved_id
                    node['id'] = resolved_id
                    label_map[nlabel] = resolved_id
                else:
                    # 本当に新しいノード
                    label_map[nlabel] = raw_id

    # Pass 2: Property Merging with Normalized IDs
    # Now that all nodes in 'daily' have their IDs normalized to either a Master ID or a Canonical Daily ID,
    # we can safely merge them.
    for node in daily.get('nodes', []):
        nid = node['id']
        ntype = node.get('type')
        current_time = datetime.now().isoformat()

        # REMOVAL LOGIC: If this node was remapped, we need to check if the OLD raw ID
        # is still lingering in master_nodes (this is how duplicates stay alive)
        # However, because we iterate over 'daily', we handle the 'raw_id -> target_id' transition.
        # Let's ensure ANY node with this label that isn't the current 'nid' gets cleared.
        label = node.get('label')
        if label:
            canonical_id = label_map.get(label)
            # Find any other nodes in master that have this label but different ID and purge them
            to_delete = [old_id for old_id, old_node in master_nodes.items() 
                         if old_node.get('label') == label and old_id != canonical_id]
            for old_id in to_delete:
                print(f"🗑️  Removing duplicate node from Master: {old_id} (Label: '{label}')")
                del master_nodes[old_id]

        if nid in master_nodes:
            # Update existing node in master
            existing = master_nodes[nid]
            
            # Simple overwrite with latest data from daily
            existing['label'] = node.get('label', existing.get('label'))
            existing['detail'] = node.get('detail', existing.get('detail'))
            
            # Type update (prefer mergeable_types)
            if ntype in mergeable_types:
                existing['type'] = ntype
            
            if 'status' in node:
                print(f"   🔄 Updating status for {nid}: {existing.get('status')} -> {node['status']}")
                existing['status'] = node['status']
            
            if 'date' in node:
                existing['date'] = node['date']
            
            if 'analysis_content' in node:
                existing['analysis_content'] = node['analysis_content']
            
            if 'sentiment' in node:
                existing['sentiment'] = node['sentiment']

            if existing.get('type') in ('diary', '日記'):
                existing['weight'] = 1
            else:
                existing['weight'] = existing.get('weight', 1) + node.get('weight', 1)
            
            existing_tags = set(existing.get('tags', []))
            new_tags = set(node.get('tags', []))
            existing['tags'] = sorted(list(existing_tags.union(new_tags)))
            
            existing['last_seen'] = current_time
            updated_node_count += 1
        else:
            # This is a truly new node (new unique label)
            node['first_seen'] = current_time
            node['last_seen'] = current_time
            node['weight'] = node.get('weight', 1)
            master_nodes[nid] = node
            new_node_count += 1

    # Finalize master nodes list
    master['nodes'] = list(master_nodes.values())

    # --- 2. Merge Edges ---
    master_edges = {}
    for e in master.get('edges', []):
        try:
            key = f"{e.get('source', '')}|{e.get('target', '')}|{e.get('type', 'UNKNOWN')}"
            master_edges[key] = e
        except Exception:
            continue
        
    new_edge_count = 0
    updated_edge_count = 0
        
    for edge in daily.get('edges', []):
        # Apply remapping for edges too
        source = id_remap.get(edge['source'], edge['source'])
        target = id_remap.get(edge['target'], edge['target'])
        
        try:
            if source == target:
                continue
            key = f"{source}|{target}|{edge.get('type', 'UNKNOWN')}"
        except Exception:
            continue

        current_time = datetime.now().isoformat()
        
        if key in master_edges:
            # Update existing edge
            existing = master_edges[key]
            existing['weight'] = existing.get('weight', 1) + 1
            existing['last_seen'] = current_time
            existing['label'] = edge.get('label', existing.get('label')) # Update label to latest context
            updated_edge_count += 1
        else:
            # Add new edge
            # Ensure we use remapped IDs
            new_edge = edge.copy()
            new_edge['source'] = source
            new_edge['target'] = target
            new_edge['first_seen'] = current_time
            new_edge['last_seen'] = current_time
            new_edge['weight'] = 1
            master_edges[key] = new_edge
            new_edge_count += 1
            
    master['edges'] = list(master_edges.values())
    
    # --- 2.5 言及エッジで参照されたノードの last_seen を更新 ---
    # 日記ノードから「言及する」エッジで繋がっているノードは、
    # デイリーグラフに直接ノードとして抽出されなくても、言及があった事実を
    # last_seen に反映する。これにより目標の進捗追跡が正確になる。
    # ID不一致時はGemini Embedding APIでベクトル検索を行い、意味的に最も
    # 近いノードにフォールバックする。
    mention_updated = 0
    vector_resolved = 0
    current_time_mention = datetime.now().isoformat()
    master_nodes_dict = {n['id']: n for n in master['nodes']}
    
    for edge in daily.get('edges', []):
        if edge.get('type') == '言及する':
            target_id = id_remap.get(edge['target'], edge['target'])
            if target_id in master_nodes_dict:
                # ID完全一致
                master_nodes_dict[target_id]['last_seen'] = current_time_mention
                mention_updated += 1
            else:
                # ベクトル検索フォールバック
                resolved_id = _resolve_target_by_vector(target_id, master_nodes_dict)
                if resolved_id:
                    master_nodes_dict[resolved_id]['last_seen'] = current_time_mention
                    mention_updated += 1
                    vector_resolved += 1
                    # 次回以降ID一致するようにリマップを記録
                    id_remap[edge['target']] = resolved_id
    
    master['nodes'] = list(master_nodes_dict.values())
    
    if mention_updated:
        msg = f"   🔗 言及エッジ経由で {mention_updated} ノードの last_seen を更新しました。"
        if vector_resolved:
            msg += f" (うち {vector_resolved} 件はベクトル検索で解決)"
        print(msg)

    # --- 3. Update Metadata ---
    if 'metadata' not in master:
        master['metadata'] = {}
        
    master['metadata']['last_updated'] = datetime.now().isoformat()
    master['metadata']['node_count'] = len(master['nodes'])
    master['metadata']['edge_count'] = len(master['edges'])
    
    print(f"✅ Merge Complete!")
    print(f"   Nodes: {new_node_count} new, {updated_node_count} updated.")
    print(f"   Edges: {new_edge_count} new, {updated_edge_count} updated.")

    # --- 4. Weight時間減衰 ---
    daily_node_ids = set(n['id'] for n in daily.get('nodes', []))
    apply_weight_decay(master, daily_node_ids, _make_edge_key_set(daily))

    # --- 5. 感情の active_sentiment 減衰 ---
    today_str = datetime.now().strftime("%Y-%m-%d")
    apply_emotion_decay(master, daily_node_ids, today_str)

    # --- 6. Neo4j Aura Free への書き込み (二重書き) ---
    _sync_to_neo4j(daily, master, daily_node_ids, _make_edge_key_set(daily), today_str)

    return master


def _sync_to_neo4j(daily: dict, master: dict, daily_node_ids: set, daily_edge_keys: set, today_str: str) -> None:
    """マージ後に差分ノード・エッジを Neo4j へ同期する。
    
    接続情報が未設定、またはパッケージが未インストールの場合はスキップ。
    """
    try:
        import os
        import sys
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        if _script_dir not in sys.path:
            sys.path.insert(0, _script_dir)

        from neo4j_client import Neo4jClient

        uri = os.getenv("NEO4J_URI", "")
        if not uri:
            # .env から読み込みを試みる
            try:
                from dotenv import load_dotenv
                load_dotenv(os.path.join(_script_dir, "..", ".env"))
                uri = os.getenv("NEO4J_URI", "")
            except ImportError:
                pass

        if not uri:
            print("ℹ️  NEO4J_URI 未設定のため Neo4j 同期をスキップします。")
            return

        print("🔗 Neo4j Aura Free へ同期中...")
        client = Neo4jClient()

        # デイリーグラフのノード・エッジのみ送信 (差分同期)
        node_count = client.upsert_node_batch_simple(daily.get("nodes", []))
        edge_count = client.upsert_edge_batch_simple(daily.get("edges", []))
        print(f"   📤 ノード {node_count}件 / エッジ {edge_count}件 を同期しました。")

        # 感情減衰をNeo4jにも反映
        client.apply_emotion_decay_cypher(daily_node_ids, today_str)

        # ウェイト減衰をNeo4jにも反映
        client.apply_weight_decay_cypher(daily_node_ids, daily_edge_keys)

        client.close()
        print("✅ Neo4j 同期完了")

    except ImportError as e:
        print(f"ℹ️  Neo4j クライアント未準備のためスキップ: {e}")
    except Exception as e:
        print(f"⚠️  Neo4j 同期エラー (処理は継続): {e}")


def main():
    parser = argparse.ArgumentParser(description="Merge a daily knowledge graph into the master graph.")
    parser.add_argument("--master", help="Path to master graph JSON", default="master_graph.json")
    parser.add_argument("--daily", help="Path to daily graph JSON", required=True)
    parser.add_argument("--output", help="Path to output master graph JSON (defaults to overwriting master)", default=None)
    
    args = parser.parse_args()
    
    output_path = args.output if args.output else args.master
    
    print(f"📂 Loading Master: {args.master}")
    master_graph = load_graph(args.master)
    
    print(f"📂 Loading Daily:  {args.daily}")
    daily_graph = load_graph(args.daily)
    
    updated_master = merge_graphs(master_graph, daily_graph)
    
    # Ensure directory exists for output
    output_dir = os.path.dirname(os.path.abspath(output_path))
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(updated_master, f, indent=2, ensure_ascii=False)
        
    print(f"💾 Saved updated master graph to: {output_path}")

if __name__ == "__main__":
    main()
