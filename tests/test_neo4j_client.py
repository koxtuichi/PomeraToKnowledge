"""Neo4jClient のユニットテスト (モック使用)。

実際の Neo4j 接続なしに neo4j_client.py の主要ロジックを検証する。
"""

import sys
import os
import json
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import neo4j_client as nc
from neo4j_client import Neo4jClient


# ──────────────────────────────────────────
# ヘルパー: ドライバーをモックして Neo4jClient を生成
# ──────────────────────────────────────────

def _make_client():
    """GraphDatabase.driver をモックした Neo4jClient を返す。"""
    with patch("neo4j_client.GraphDatabase.driver") as mock_driver_cls:
        mock_driver = MagicMock()
        mock_driver_cls.return_value = mock_driver
        client = Neo4jClient(
            uri="neo4j+s://test.databases.neo4j.io",
            username="neo4j",
            password="test_password",
        )
        client._mock_driver = mock_driver
    return client


# ──────────────────────────────────────────
# _serialize_props
# ──────────────────────────────────────────

class TestSerializeProps(unittest.TestCase):

    def test_none_values_excluded(self):
        props = {"a": 1, "b": None, "c": "hello"}
        result = Neo4jClient._serialize_props(props)
        self.assertNotIn("b", result)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["c"], "hello")

    def test_json_props_serialized(self):
        """_JSON_PROPS に登録されたキーは JSON 文字列に変換される。"""
        props = {"tags": ["python", "neo4j"], "analysis_content": {"score": 0.9}}
        result = Neo4jClient._serialize_props(props)
        self.assertIsInstance(result["tags"], str)
        self.assertEqual(json.loads(result["tags"]), ["python", "neo4j"])
        self.assertIsInstance(result["analysis_content"], str)

    def test_dict_value_serialized(self):
        """_JSON_PROPS 以外の dict も JSON 文字列に変換される。"""
        props = {"extra": {"key": "value"}}
        result = Neo4jClient._serialize_props(props)
        self.assertIsInstance(result["extra"], str)
        self.assertEqual(json.loads(result["extra"]), {"key": "value"})

    def test_string_already_serialized_not_double_encoded(self):
        """すでに文字列の _JSON_PROPS フィールドはそのまま保持される。"""
        props = {"tags": '["python"]'}
        result = Neo4jClient._serialize_props(props)
        self.assertEqual(result["tags"], '["python"]')

    def test_scalar_values_unchanged(self):
        props = {"weight": 1.5, "date": "2026-01-01", "count": 42}
        result = Neo4jClient._serialize_props(props)
        self.assertEqual(result["weight"], 1.5)
        self.assertEqual(result["date"], "2026-01-01")
        self.assertEqual(result["count"], 42)


# ──────────────────────────────────────────
# _deserialize_props
# ──────────────────────────────────────────

class TestDeserializeProps(unittest.TestCase):

    def test_json_props_deserialized(self):
        props = {"tags": '["python", "neo4j"]', "weight": 1.0}
        result = Neo4jClient._deserialize_props(props)
        self.assertEqual(result["tags"], ["python", "neo4j"])
        self.assertEqual(result["weight"], 1.0)

    def test_dict_string_deserialized(self):
        props = {"analysis_content": '{"score": 0.9}'}
        result = Neo4jClient._deserialize_props(props)
        self.assertEqual(result["analysis_content"], {"score": 0.9})

    def test_plain_string_unchanged(self):
        props = {"label": "テストノード"}
        result = Neo4jClient._deserialize_props(props)
        self.assertEqual(result["label"], "テストノード")

    def test_invalid_json_string_kept_as_string(self):
        props = {"tags": "not valid json ["}
        result = Neo4jClient._deserialize_props(props)
        self.assertEqual(result["tags"], "not valid json [")

    def test_roundtrip_serialize_deserialize(self):
        """serialize → deserialize のラウンドトリップで元の値に戻ること。"""
        original = {
            "tags": ["python", "neo4j"],
            "emotion_history": [{"date": "2026-01-01", "value": 0.8}],
            "weight": 1.5,
            "label": "テスト",
        }
        serialized = Neo4jClient._serialize_props(original)
        restored = Neo4jClient._deserialize_props(serialized)
        self.assertEqual(restored["tags"], original["tags"])
        self.assertEqual(restored["emotion_history"], original["emotion_history"])
        self.assertEqual(restored["weight"], original["weight"])
        self.assertEqual(restored["label"], original["label"])


# ──────────────────────────────────────────
# 接続・初期化
# ──────────────────────────────────────────

class TestNeo4jClientInit(unittest.TestCase):

    def test_missing_uri_raises(self):
        with self.assertRaises(ValueError):
            Neo4jClient(uri="", username="neo4j", password="pw")

    def test_missing_password_raises(self):
        with self.assertRaises(ValueError):
            Neo4jClient(uri="neo4j+s://test.io", username="neo4j", password="")

    def test_driver_created_with_correct_args(self):
        with patch("neo4j_client.GraphDatabase.driver") as mock_driver_cls:
            mock_driver_cls.return_value = MagicMock()
            client = Neo4jClient(
                uri="neo4j+s://test.io",
                username="testuser",
                password="testpass",
            )
            mock_driver_cls.assert_called_once_with(
                "neo4j+s://test.io", auth=("testuser", "testpass")
            )

    def test_env_vars_used_when_no_args(self):
        with patch.dict(os.environ, {
            "NEO4J_URI": "neo4j+s://env.io",
            "NEO4J_USERNAME": "envuser",
            "NEO4J_PASSWORD": "envpass",
        }):
            with patch("neo4j_client.GraphDatabase.driver") as mock_driver_cls:
                mock_driver_cls.return_value = MagicMock()
                client = Neo4jClient()
                mock_driver_cls.assert_called_once_with(
                    "neo4j+s://env.io", auth=("envuser", "envpass")
                )


# ──────────────────────────────────────────
# test_connection
# ──────────────────────────────────────────

class TestTestConnection(unittest.TestCase):

    def test_returns_true_on_success(self):
        client = _make_client()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        client._mock_driver.session.return_value = mock_session
        mock_session.run.return_value.single.return_value = {"ok": 1}

        self.assertTrue(client.test_connection())

    def test_returns_false_on_exception(self):
        client = _make_client()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        client._mock_driver.session.return_value = mock_session
        mock_session.run.side_effect = Exception("connection refused")

        self.assertFalse(client.test_connection())


# ──────────────────────────────────────────
# upsert_node
# ──────────────────────────────────────────

class TestUpsertNode(unittest.TestCase):

    def _get_mock_session(self, client):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        client._mock_driver.session.return_value = mock_session
        return mock_session

    def test_node_without_id_skipped(self):
        client = _make_client()
        session = self._get_mock_session(client)
        client.upsert_node({"type": "タスク", "label": "IDなし"})
        session.run.assert_not_called()

    def test_node_with_id_calls_merge(self):
        client = _make_client()
        session = self._get_mock_session(client)
        client.upsert_node({"id": "タスク:test", "type": "タスク", "label": "テスト"})
        session.run.assert_called_once()
        cypher, *_ = session.run.call_args[0]
        self.assertIn("MERGE", cypher)
        self.assertIn("SET n += $props", cypher)

    def test_cypher_no_invalid_dynamic_label(self):
        """upsert_node の Cypher に $(ntype) のような無効構文が含まれないこと。"""
        client = _make_client()
        session = self._get_mock_session(client)
        client.upsert_node({"id": "タスク:test", "type": "タスク", "label": "テスト"})
        cypher = session.run.call_args[0][0]
        self.assertNotIn("$(", cypher, "動的ラベル設定の無効構文が含まれています")


# ──────────────────────────────────────────
# upsert_node_batch_simple
# ──────────────────────────────────────────

class TestUpsertNodeBatchSimple(unittest.TestCase):

    def _get_mock_session(self, client):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        client._mock_driver.session.return_value = mock_session
        return mock_session

    def test_returns_count(self):
        client = _make_client()
        session = self._get_mock_session(client)
        nodes = [
            {"id": "n1", "label": "ノード1", "type": "タスク"},
            {"id": "n2", "label": "ノード2", "type": "感情"},
        ]
        count = client.upsert_node_batch_simple(nodes)
        self.assertEqual(count, 2)

    def test_skips_nodes_without_id(self):
        client = _make_client()
        session = self._get_mock_session(client)
        nodes = [
            {"label": "IDなし", "type": "タスク"},
            {"id": "n1", "label": "OK", "type": "タスク"},
        ]
        count = client.upsert_node_batch_simple(nodes)
        self.assertEqual(count, 1)

    def test_each_node_calls_session_run(self):
        client = _make_client()
        session = self._get_mock_session(client)
        nodes = [
            {"id": "n1", "label": "A", "type": "タスク"},
            {"id": "n2", "label": "B", "type": "タスク"},
        ]
        client.upsert_node_batch_simple(nodes)
        self.assertEqual(session.run.call_count, 2)

    def test_serializes_list_props(self):
        client = _make_client()
        session = self._get_mock_session(client)
        nodes = [{"id": "n1", "tags": ["a", "b"], "type": "タスク"}]
        client.upsert_node_batch_simple(nodes)
        _, kwargs = session.run.call_args
        props = kwargs.get("props", session.run.call_args[0][2] if len(session.run.call_args[0]) > 2 else {})
        # run の呼び出し引数から props を取り出す
        call_kwargs = session.run.call_args[1]
        self.assertIsInstance(call_kwargs.get("props", {}).get("tags", ""), str)


# ──────────────────────────────────────────
# upsert_edge_batch_simple
# ──────────────────────────────────────────

class TestUpsertEdgeBatchSimple(unittest.TestCase):

    def _get_mock_session(self, client):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        client._mock_driver.session.return_value = mock_session
        return mock_session

    def test_returns_count(self):
        client = _make_client()
        session = self._get_mock_session(client)
        edges = [
            {"source": "n1", "target": "n2", "type": "阻害する"},
        ]
        count = client.upsert_edge_batch_simple(edges)
        self.assertEqual(count, 1)

    def test_skips_self_loop(self):
        client = _make_client()
        session = self._get_mock_session(client)
        edges = [{"source": "n1", "target": "n1", "type": "関連"}]
        count = client.upsert_edge_batch_simple(edges)
        self.assertEqual(count, 0)
        session.run.assert_not_called()

    def test_skips_missing_source_or_target(self):
        client = _make_client()
        session = self._get_mock_session(client)
        edges = [
            {"source": "n1", "type": "関連"},
            {"target": "n2", "type": "関連"},
        ]
        count = client.upsert_edge_batch_simple(edges)
        self.assertEqual(count, 0)

    def test_default_rel_type_used(self):
        client = _make_client()
        session = self._get_mock_session(client)
        edges = [{"source": "n1", "target": "n2"}]
        client.upsert_edge_batch_simple(edges)
        kwargs = session.run.call_args[1]
        self.assertEqual(kwargs["rel_type"], "RELATED_TO")


# ──────────────────────────────────────────
# export_graph
# ──────────────────────────────────────────

class TestExportGraph(unittest.TestCase):

    def test_export_returns_dict_with_keys(self):
        client = _make_client()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        client._mock_driver.session.return_value = mock_session

        # ノード結果
        node_record = MagicMock()
        node_record.__getitem__ = lambda self, key: {"id": "n1", "label": "テスト", "type": "タスク"}
        edge_record = MagicMock()
        edge_record.__getitem__ = lambda self, key: {"source": "n1", "target": "n2", "type": "関連"}

        def run_side_effect(query, **kwargs):
            result = MagicMock()
            if "MATCH (n:Node)" in query and "RELATED_TO" not in query:
                result.__iter__ = MagicMock(return_value=iter([node_record]))
            else:
                result.__iter__ = MagicMock(return_value=iter([edge_record]))
            return result

        mock_session.run.side_effect = run_side_effect

        graph = client.export_graph()
        self.assertIn("nodes", graph)
        self.assertIn("edges", graph)
        self.assertIn("metadata", graph)
        self.assertEqual(graph["metadata"]["exported_from"], "neo4j")

    def test_export_metadata_counts(self):
        client = _make_client()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        client._mock_driver.session.return_value = mock_session

        def run_side_effect(query, **kwargs):
            result = MagicMock()
            result.__iter__ = MagicMock(return_value=iter([]))
            return result

        mock_session.run.side_effect = run_side_effect

        graph = client.export_graph()
        self.assertEqual(graph["metadata"]["node_count"], 0)
        self.assertEqual(graph["metadata"]["edge_count"], 0)


# ──────────────────────────────────────────
# context manager
# ──────────────────────────────────────────

class TestContextManager(unittest.TestCase):

    def test_with_statement_closes_driver(self):
        with patch("neo4j_client.GraphDatabase.driver") as mock_driver_cls:
            mock_driver = MagicMock()
            mock_driver_cls.return_value = mock_driver
            with Neo4jClient(
                uri="neo4j+s://test.io",
                username="neo4j",
                password="pw",
            ) as client:
                pass
            mock_driver.close.assert_called_once()


if __name__ == "__main__":
    import unittest
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
