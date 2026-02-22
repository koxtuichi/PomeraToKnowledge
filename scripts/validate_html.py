#!/usr/bin/env python3
"""graph_data.js の整合性を検証するスクリプト。

使い方:
    python3 scripts/validate_html.py             # デフォルト: ./graph_data.js を検証
    python3 scripts/validate_html.py graph_data.js

終了コード:
    0: 検証成功
    1: 検証失敗
"""
import json
import re
import sys
import os


def validate(js_path: str) -> bool:
    print(f"🔍 検証対象: {js_path}")

    # ─── ファイルの存在確認 ─────────────────────────────────────────
    if not os.path.exists(js_path):
        print(f"❌ ファイルが見つかりません: {js_path}")
        return False

    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # ─── マーカーの確認 ────────────────────────────────────────────
    start_count = content.count("// GRAPH_DATA_START")
    end_count = content.count("// GRAPH_DATA_END")
    if start_count != 1 or end_count != 1:
        print(f"❌ マーカーが不正です (START: {start_count}個, END: {end_count}個)")
        return False
    print("✅ マーカー: OK")

    # ─── JSON の抽出とパース ────────────────────────────────────────
    m = re.search(r"const GRAPH_DATA = (\{.*\});", content, re.DOTALL)
    if not m:
        print("❌ GRAPH_DATA の宣言が見つかりません")
        return False

    try:
        graph_data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"❌ JSON パースエラー: {e}")
        return False

    # ─── 構造の確認 ────────────────────────────────────────────────
    if not isinstance(graph_data.get("nodes"), list):
        print("❌ nodes がリストではありません")
        return False
    if not isinstance(graph_data.get("edges"), list):
        print("❌ edges がリストではありません")
        return False

    node_count = len(graph_data["nodes"])
    edge_count = len(graph_data["edges"])
    print(f"✅ JSON パース: OK")
    print(f"   ノード数: {node_count}")
    print(f"   エッジ数: {edge_count}")

    if node_count == 0:
        print("⚠️  ノードが 0 件です。データが空の可能性があります。")

    print("✅ 検証完了: graph_data.js は正常です")
    return True


if __name__ == "__main__":
    js_path = sys.argv[1] if len(sys.argv) > 1 else "graph_data.js"
    success = validate(js_path)
    sys.exit(0 if success else 1)
