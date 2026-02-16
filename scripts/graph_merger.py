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
    mergeable_types = {'person', 'place', 'project', 'concept', 'goal', 'emotion', 'insight'}
    
    for n in master.get('nodes', []):
        if n.get('type') in mergeable_types and n.get('label'):
            key = f"{n['type']}:{n['label']}"
            label_map[key] = n['id']

    new_node_count = 0
    updated_node_count = 0
    id_remap = {} # Remap dictionary for merged nodes

    for node in daily.get('nodes', []):
        nid = node['id']
        ntype = node.get('type')
        nlabel = node.get('label')
        current_time = datetime.now().isoformat()
        
        # Check for duplicate by Label
        if nid not in master_nodes and ntype in mergeable_types and nlabel:
            key = f"{ntype}:{nlabel}"
            if key in label_map:
                existing_id = label_map[key]
                print(f"🔄 Merging duplicate node: {nid} -> {existing_id} (Label: {nlabel})")
                id_remap[nid] = existing_id
                nid = existing_id # Use existing ID
        
        if nid in master_nodes:
            # Update existing node
            existing = master_nodes[nid]
            
            # Key properties: Overwrite with latest or merge?
            # Strategy: Overwrite label/detail/type to keep it current.
            # But keep a history if needed? For now, simple overwrite.
            existing['label'] = node.get('label', existing.get('label'))
            existing['detail'] = node.get('detail', existing.get('detail'))
            existing['type'] = node.get('type', existing.get('type'))
            
            # Key properties update: Status and Date
            # If the new node has a status (e.g., Completed), overwrite the old one.
            if 'status' in node:
                print(f"   🔄 Updating status for {nid}: {existing.get('status')} -> {node['status']}")
                existing['status'] = node['status']
            
            # Update date if provided (e.g., rescheduling)
            if 'date' in node:
                existing['date'] = node['date']
            
            # Merge Analysis Content
            if 'analysis_content' in node:
                existing['analysis_content'] = node['analysis_content']
            
            # Merge Sentiment (Average? or Latest?) -> Let's take Weighted Average or just Latest
            # For simplicity & responsiveness: take Latest.
            if 'sentiment' in node:
                existing['sentiment'] = node['sentiment']

            # Update numericals
            # Weight: Add the new weight (importance accumulation)
            # EXCEPTION: For 'diary' nodes, weight should always be 1 (don't accumulate on re-runs)
            if existing.get('type') == 'diary':
                existing['weight'] = 1
            else:
                existing['weight'] = existing.get('weight', 1) + node.get('weight', 1)
            
            # Merge tags
            existing_tags = set(existing.get('tags', []))
            new_tags = set(node.get('tags', []))
            combined_tags = list(existing_tags.union(new_tags))
            existing['tags'] = sorted(combined_tags) # Sort for consistency
            
            # Metadata
            existing['last_seen'] = current_time
            if 'first_seen' not in existing:
                existing['first_seen'] = current_time # Should exist, but safety check
            
            updated_node_count += 1
        else:
            # Add new node
            # Update ID if it was remapped (though logic above handles it, explicit safety)
            # If it was a NEW node that didn't match anything, it falls here.
            node['first_seen'] = current_time
            node['last_seen'] = current_time
            node['weight'] = node.get('weight', 1)
            master_nodes[nid] = node
            
            # Add to label map for future dupes in same batch
            if ntype in mergeable_types and nlabel:
                key = f"{ntype}:{nlabel}"
                label_map[key] = nid
                
            new_node_count += 1

    # Reconstruct master nodes list
    master['nodes'] = list(master_nodes.values())

    # --- 2. Merge Edges ---
    master_edges = {}
    # Use a composite key to identify unique edges
    for e in master.get('edges', []):
        try:
            key = f"{e.get('source', '')}|{e.get('target', '')}|{e.get('type', 'UNKNOWN')}"
            master_edges[key] = e
        except Exception:
            continue
        
    new_edge_count = 0
    updated_edge_count = 0
        
    for edge in daily.get('edges', []):
        # Remap IDs if needed
        source = id_remap.get(edge['source'], edge['source'])
        target = id_remap.get(edge['target'], edge['target'])
        
        try:
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
