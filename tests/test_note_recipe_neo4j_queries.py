import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUERY_SCRIPT = ROOT / "scripts" / "note_recipe_neo4j_queries.py"
spec = importlib.util.spec_from_file_location("note_recipe_neo4j_queries", QUERY_SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_fetch_note_recipe_materials_normalizes_cypher_rows():
    class FakeSession:
        query = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def run(self, query, **params):
            self.query = query
            assert params["diary_ids"] == ["日記:2026-04-20"]
            assert "言及する" in params["diary_rel_types"]
            assert "進捗として" in params["context_rel_types"]
            return [
                {
                    "diary_id": "日記:2026-04-20",
                    "diary": {
                        "id": "日記:2026-04-20",
                        "type": "日記",
                        "detail": "車を購入できた。納車が待ち遠しい。",
                    },
                    "diaries": [
                        {
                            "id": "日記:20260420",
                            "type": "日記",
                            "date": "2026-04-20",
                            "detail": "中古店とオンラインショップを見て、購入まで進んだ。",
                        }
                    ],
                    "direct": [
                        {
                            "node": {
                                "id": "目標:車を買う",
                                "type": "目標",
                                "label": "車を買う",
                                "status": "達成",
                                "current_state": "車は購入済み。納車待ち。",
                                "update_history": [{"date": "2026-04-20", "summary": "購入できた"}],
                            }
                        },
                        {
                            "node": {
                                "id": "制約:先約待ち",
                                "type": "制約",
                                "label": "先約待ち",
                                "detail": "先約がいて買えるか不明だった。",
                            }
                        },
                        {
                            "node": {
                                "id": "解決策:納車準備",
                                "type": "解決策",
                                "label": "納車準備",
                                "detail": "保険と置き場所を確認する。",
                            }
                        },
                    ],
                    "nearby": [],
                }
            ]

    class FakeDriver:
        def __init__(self):
            self.session_obj = FakeSession()

        def session(self):
            return self.session_obj

    class FakeClient:
        def __init__(self):
            self._driver = FakeDriver()

    client = FakeClient()
    materials = module.fetch_note_recipe_materials(client, ["日記:2026-04-20"])
    material = materials["日記:2026-04-20"]

    assert "UNWIND $diary_ids" in client._driver.session_obj.query
    assert "s.date = diary_date" in client._driver.session_obj.query
    assert "CASE" in client._driver.session_obj.query
    assert material.problem == "先約がいて買えるか不明だった。"
    assert material.current_status == "車は購入済み。納車待ち。"
    assert material.next_step == "保険と置き場所を確認する。"
    assert "先約がいて買えるか不明だった。" in material.pain_points


def test_fetch_note_recipe_materials_uses_analysis_content_fallbacks():
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def run(self, query, **params):
            return [
                {
                    "diary_id": "日記:2026-05-01",
                    "diary": {
                        "id": "日記:20260501",
                        "type": "日記",
                        "detail": "仕事の提案が重く、次の一歩が見えない。",
                    },
                    "diaries": [
                        {
                            "id": "日記:2026-05-01",
                            "type": "日記",
                            "date": "2026-05-01",
                            "detail": "",
                            "analysis_content": {
                                "gravity_map": [
                                    {
                                        "task": "仕事の提案",
                                        "net_assessment": "仕事の論点が多く停滞している。",
                                        "constraints": [{"name": "情報が混ざっている"}],
                                    }
                                ],
                                "antigravity_actions": [{"action": "5分だけ論点を1つに絞る。"}],
                                "insights": [{"finding": "論点を減らすと動き出しやすい。"}],
                            },
                        }
                    ],
                    "direct": [],
                    "nearby": [],
                }
            ]

    class FakeClient:
        _driver = type("FakeDriver", (), {"session": lambda self: FakeSession()})()

    material = module.fetch_note_recipe_materials(FakeClient(), ["日記:2026-05-01"])[
        "日記:2026-05-01"
    ]

    assert material.problem == "仕事の提案"
    assert material.current_status == "仕事の論点が多く停滞している。"
    assert material.next_step == "5分だけ論点を1つに絞る。"
    assert material.pain_points == ["情報が混ざっている"]
