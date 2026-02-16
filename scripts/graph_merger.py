import json
import os
import argparse
from datetime import datetime

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
                # New label: establish this raw_id as the canonical ID for this label
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
    
    # --- 3. Update Metadata ---
    if 'metadata' not in master:
        master['metadata'] = {}
        
    master['metadata']['last_updated'] = datetime.now().isoformat()
    master['metadata']['node_count'] = len(master['nodes'])
    master['metadata']['edge_count'] = len(master['edges'])
    
    print(f"✅ Merge Complete!")
    print(f"   Nodes: {new_node_count} new, {updated_node_count} updated.")
    print(f"   Edges: {new_edge_count} new, {updated_edge_count} updated.")

    return master

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
