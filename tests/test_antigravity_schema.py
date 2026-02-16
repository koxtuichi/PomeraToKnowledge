"""Antigravityスキーマの整合性テスト"""
import sys
import os
import json
from datetime import datetime

# テスト対象モジュールへのパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import graph_merger


class TestAntigravitySchema:
    """Antigravityスキーマの基本的な整合性をテストする。"""

    def test_mergeable_types_contains_constraint(self):
        """mergeable_types に制約ノードが含まれることを確認。"""
        # graph_merger.merge_graphs 内の mergeable_types を検証
        # 関数を実行して実際に制約ノードがマージされることを確認
        master = {"nodes": [], "edges": [], "metadata": {}}
        daily = {
            "nodes": [
                {
                    "id": "制約:時間不足",
                    "label": "時間不足",
                    "type": "制約",
                    "detail": "仕事と育児で掃除の時間が取れない",
                    "constraint_type": "時間不足"
                }
            ],
            "edges": []
        }
        result = graph_merger.merge_graphs(master, daily)
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["type"] == "制約"
        assert result["nodes"][0]["label"] == "時間不足"

    def test_merge_constraint_with_task(self):
        """制約ノードとタスクノードが正しくマージされ、阻害するエッジが保持されることを確認。"""
        master = {"nodes": [], "edges": [], "metadata": {}}
        daily = {
            "nodes": [
                {
                    "id": "タスク:掃除",
                    "label": "ペット部屋の掃除",
                    "type": "タスク",
                    "status": "未着手",
                    "detail": "フローリングの粘着跡を除去する"
                },
                {
                    "id": "制約:粘着剤",
                    "label": "粘着剤の固着",
                    "type": "制約",
                    "detail": "粘着カバーの跡が取れない",
                    "constraint_type": "物理的障害"
                }
            ],
            "edges": [
                {
                    "source": "制約:粘着剤",
                    "target": "タスク:掃除",
                    "type": "阻害する",
                    "label": "粘着剤が取れないため掃除が難航"
                }
            ]
        }
        result = graph_merger.merge_graphs(master, daily)
        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1
        assert result["edges"][0]["type"] == "阻害する"

    def test_merge_energy_edge(self):
        """原動力になるエッジが正しく保持されることを確認。"""
        master = {"nodes": [], "edges": [], "metadata": {}}
        daily = {
            "nodes": [
                {
                    "id": "タスク:開発",
                    "label": "ポメラ自動化の開発",
                    "type": "タスク",
                    "status": "進行中"
                },
                {
                    "id": "感情:楽しさ",
                    "label": "開発の楽しさ",
                    "type": "感情",
                    "sentiment": 0.9
                }
            ],
            "edges": [
                {
                    "source": "感情:楽しさ",
                    "target": "タスク:開発",
                    "type": "原動力になる",
                    "label": "楽しさがモチベーション"
                }
            ]
        }
        result = graph_merger.merge_graphs(master, daily)
        assert len(result["edges"]) == 1
        assert result["edges"][0]["type"] == "原動力になる"

    def test_diary_type_japanese(self):
        """日本語の日記タイプが weight=1 で維持されることを確認。"""
        master = {"nodes": [], "edges": [], "metadata": {}}
        daily = {
            "nodes": [
                {
                    "id": "日記:2026-02-16",
                    "label": "2026-02-16の日記",
                    "type": "日記",
                    "date": "2026-02-16",
                    "weight": 1
                }
            ],
            "edges": []
        }
        result = graph_merger.merge_graphs(master, daily)
        assert result["nodes"][0]["weight"] == 1

        # もう一度マージしても weight が増えないこと
        result2 = graph_merger.merge_graphs(result, daily)
        assert result2["nodes"][0]["weight"] == 1

    def test_duplicate_label_remapping(self):
        """同じラベルのノードがマスターと日次で異なるIDを持つ場合、リマップされることを確認。"""
        master = {
            "nodes": [
                {
                    "id": "タスク:掃除_old",
                    "label": "ペット部屋の掃除",
                    "type": "タスク",
                    "status": "未着手",
                    "first_seen": "2026-02-15T10:00:00",
                    "last_seen": "2026-02-15T10:00:00",
                    "weight": 1,
                    "tags": []
                }
            ],
            "edges": [],
            "metadata": {}
        }
        daily = {
            "nodes": [
                {
                    "id": "タスク:掃除_new",
                    "label": "ペット部屋の掃除",
                    "type": "タスク",
                    "status": "進行中"
                }
            ],
            "edges": []
        }
        result = graph_merger.merge_graphs(master, daily)

        # 同じラベルのノードが1つにまとめられること
        cleaning_nodes = [n for n in result["nodes"] if n["label"] == "ペット部屋の掃除"]
        assert len(cleaning_nodes) == 1
        # ステータスが更新されること
        assert cleaning_nodes[0]["status"] == "進行中"

    def test_metadata_update(self):
        """マージ後にメタデータが更新されることを確認。"""
        master = {"nodes": [], "edges": [], "metadata": {}}
        daily = {
            "nodes": [
                {"id": "タスク:test", "label": "テスト", "type": "タスク"}
            ],
            "edges": []
        }
        result = graph_merger.merge_graphs(master, daily)
        assert "last_updated" in result["metadata"]
        assert result["metadata"]["node_count"] == 1
        assert result["metadata"]["edge_count"] == 0

    def test_knowledge_graph_jsonld_schema(self):
        """knowledge_graph.jsonld のスキーマが正しいことを確認。"""
        jsonld_path = os.path.join(os.path.dirname(__file__), '..', 'knowledge_graph.jsonld')
        if os.path.exists(jsonld_path):
            with open(jsonld_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            assert "nodes" in data
            assert "edges" in data
            assert "metadata" in data
            assert data["metadata"].get("schema_version") == "2.0-antigravity"


# pytest互換のテスト実行
if __name__ == "__main__":
    t = TestAntigravitySchema()
    tests = [m for m in dir(t) if m.startswith('test_')]
    passed = 0
    failed = 0
    for test_name in tests:
        try:
            getattr(t, test_name)()
            print(f"  ✅ {test_name}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {test_name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {test_name}: {e}")
            failed += 1
    print(f"\n結果: {passed} passed, {failed} failed")
