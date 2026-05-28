import importlib.util
import json
import sys
import types
from pathlib import Path


MODULE_DIR = (
    Path(__file__).resolve().parents[1] / "cloud_functions" / "generate_note_draft"
)
MAIN_PATH = MODULE_DIR / "main.py"


def _sample_node(node_id="日記:2026-03-04"):
    return {
        "id": node_id,
        "type": "日記",
        "date": "2026-03-04",
        "label": "2026-03-04の日記",
        "detail": "仕事の休みを取り、確定申告を完了。別プロジェクトの業務が溜まっていることを確認した日。",
        "analysis_content": {
            "gravity_map": [
                {
                    "task": "別プロジェクトの業務滞留解消",
                    "net_assessment": "やるべきことは明確だが、量に圧倒されている。",
                    "constraints": [
                        {"name": "タスクの積み上がりによる心理的圧迫"},
                        {"name": "本業との兼ね合い"},
                    ],
                }
            ],
            "antigravity_actions": [
                {
                    "target_task": "別プロジェクト業務",
                    "action": "関係者への質問事項とテンプレートに必要な3項目をポメラで箇条書きにする。",
                    "effect": "相手が関わる確認を先に外へ出し、自分の作業待ち時間を減らす。",
                }
            ],
            "insights": [{"finding": "質問を先に切り出すと、待ち時間を減らせる。"}],
        },
    }


class Request:
    method = "POST"

    def __init__(self, payload):
        self.payload = payload

    def get_json(self, silent=True):
        return self.payload


class FakeNeo4jClient:
    nodes = [_sample_node()]
    blocked = set()
    history = []
    claim = {"claimed": True, "generation_id": "gen-new"}
    mark_generation_result = True
    mark_published_result = True
    init_error = None
    marks = []

    def __init__(self):
        if self.__class__.init_error:
            raise self.__class__.init_error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def fetch_diaries(self):
        return self.__class__.nodes

    def fetch_diary(self, diary_id):
        return next(
            (node for node in self.__class__.nodes if node.get("id") == diary_id),
            None,
        )

    def fetch_generation_blocked_ids(self, _lane, _prompt_version):
        return self.__class__.blocked

    def fetch_generation_theme_history(
        self, _lane, _prompt_version, limit=100, exclude_diary_id=None
    ):
        return self.__class__.history[:limit]

    def claim_generation(self, _diary_id, _lane, _prompt_version, _run_id):
        return self.__class__.claim

    def mark_generation(self, generation_id, status, props=None):
        self.__class__.marks.append((generation_id, status, props or {}))
        return self.__class__.mark_generation_result

    def mark_published(self, _diary_id, _lane, _prompt_version, note_url=""):
        return self.__class__.mark_published_result


def _load_main(monkeypatch):
    saved = []
    fake_framework = types.ModuleType("functions_framework")
    fake_framework.http = lambda fn: fn
    fake_gcs = types.ModuleType("gcs_io")

    def save_json(path, payload):
        saved.append(("json", path, payload))
        return f"gs://fake/{path}"

    def save_text(path, payload):
        saved.append(("text", path, payload))
        return f"gs://fake/{path}"

    fake_gcs.save_json = save_json
    fake_gcs.save_text = save_text

    monkeypatch.syspath_prepend(str(MODULE_DIR))
    monkeypatch.setitem(sys.modules, "functions_framework", fake_framework)
    monkeypatch.setitem(sys.modules, "gcs_io", fake_gcs)
    spec = importlib.util.spec_from_file_location("generate_note_draft_main_test", MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.Neo4jDiaryClient = FakeNeo4jClient
    return module, saved


def _reset_fake_client():
    FakeNeo4jClient.nodes = [_sample_node()]
    FakeNeo4jClient.blocked = set()
    FakeNeo4jClient.history = []
    FakeNeo4jClient.claim = {"claimed": True, "generation_id": "gen-new"}
    FakeNeo4jClient.mark_generation_result = True
    FakeNeo4jClient.mark_published_result = True
    FakeNeo4jClient.init_error = None
    FakeNeo4jClient.marks = []


def _response_tuple_to_payload(result):
    body, status, _headers = result
    return json.loads(body), status


def test_generate_note_draft_success_saves_theme_metadata(monkeypatch):
    _reset_fake_client()
    main, saved = _load_main(monkeypatch)

    payload, status = _response_tuple_to_payload(
        main.generate_note_draft(Request({"run_id": "success-run"}))
    )

    assert status == 200
    assert payload["source"] == "neo4j"
    assert payload["theme_profile"]["theme_cluster"] == "work_unblock"
    assert payload["theme_decision"]["history_count"] == 0
    article_meta = next(item for item in saved if item[1].endswith("article.json"))[2]
    state_snapshot = next(item for item in saved if item[1].endswith("state_snapshot.json"))[2]
    assert "theme_profile" in article_meta
    assert "theme_decision" in state_snapshot["article_history"][0]
    assert FakeNeo4jClient.marks[-1][2]["theme_cluster"] == "work_unblock"


def test_generate_note_draft_stops_on_theme_conflict(monkeypatch):
    _reset_fake_client()
    main, saved = _load_main(monkeypatch)
    diary = main.collect_diaries([_sample_node()])[0]
    FakeNeo4jClient.history = [
        {
            "generation": {
                "id": "gen-old",
                "status": "published",
                "title": "過去記事",
                **diary.theme_profile,
            }
        }
    ]

    payload, status = _response_tuple_to_payload(
        main.generate_note_draft(Request({"run_id": "conflict-run"}))
    )

    assert status == 409
    assert payload["reason"] == "neo4j_theme_conflict"
    assert payload["theme_conflicts"][0]["matched_generation_id"] == "gen-old"
    stop_report = next(item for item in saved if item[1].endswith("stop_report.json"))[2]
    assert stop_report["theme_conflicts"][0]["matched_generation_id"] == "gen-old"


def test_generate_note_draft_stops_when_neo4j_unavailable(monkeypatch):
    _reset_fake_client()
    main, _saved = _load_main(monkeypatch)
    FakeNeo4jClient.init_error = RuntimeError("neo4j down")

    payload, status = _response_tuple_to_payload(
        main.generate_note_draft(Request({"run_id": "neo4j-down"}))
    )

    assert status == 503
    assert payload["reason"] == "neo4j_unavailable"
    assert payload["fallback_attempted"] is False


def test_generate_note_draft_stops_on_claim_conflict(monkeypatch):
    _reset_fake_client()
    main, _saved = _load_main(monkeypatch)
    FakeNeo4jClient.claim = {
        "claimed": False,
        "generation_id": "gen-existing",
        "status": "generated",
    }

    payload, status = _response_tuple_to_payload(
        main.generate_note_draft(Request({"run_id": "claim-conflict"}))
    )

    assert status == 409
    assert payload["reason"] == "neo4j_generation_already_exists"
    assert payload["existing_generation"]["generation_id"] == "gen-existing"


def test_mark_published_reports_not_found_and_success(monkeypatch):
    _reset_fake_client()
    main, _saved = _load_main(monkeypatch)
    FakeNeo4jClient.mark_published_result = False

    payload, status = _response_tuple_to_payload(
        main.generate_note_draft(
            Request({"action": "mark_published", "diary_id": "日記:2026-03-04"})
        )
    )

    assert status == 404
    assert payload["reason"] == "neo4j_generation_not_found"

    FakeNeo4jClient.mark_published_result = True
    payload, status = _response_tuple_to_payload(
        main.generate_note_draft(
            Request({"action": "mark_published", "diary_id": "日記:2026-03-04"})
        )
    )

    assert status == 200
    assert payload["action"] == "mark_published"
