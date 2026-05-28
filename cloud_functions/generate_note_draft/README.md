# generate-note-draft

Neo4j の日記ノードだけを入力にして、note 下書き用 Markdown を生成する HTTP Cloud Function。

## 方針

- 入力元は Neo4j のみ。
- `knowledge_graph.jsonld` / `graph_data.js` への fallback はしない。
- Neo4j 接続不可、候補なし、品質チェック失敗時は停止レポートを返す。
- Markdown 成果物と品質レポートは GCS に保存する。
- 重複生成状態は Neo4j の `NoteGeneration` ノードで管理する。
- 既に生成・公開済みの記事と近いテーマは候補から外す。

## Environment Variables

- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `NEO4J_DATABASE` optional
- `GCS_BUCKET` default: `pomera-knowledge-data`
- `NOTE_READY_PREFIX` default: `note_ready`
- `NOTE_FAILED_PREFIX` default: `note_failed`
- `NOTE_LANE` default: `note_daily_recipe`
- `NOTE_PROMPT_VERSION` default: `2026-05-28-v1`
- `NOTE_THEME_HISTORY_LIMIT` default: `100`

## Deploy Notes

Deploy as a separate function. Do not deploy it as `process-diary` or `process-blog`.

```bash
gcloud functions deploy generate-note-draft \
  --gen2 \
  --runtime=python311 \
  --region=asia-northeast1 \
  --source=cloud_functions/generate_note_draft \
  --entry-point=generate_note_draft \
  --trigger-http \
  --set-env-vars=GCS_BUCKET=pomera-knowledge-data,NOTE_LANE=note_daily_recipe,NOTE_PROMPT_VERSION=2026-05-28-v1 \
  --set-secrets=NEO4J_URI=NEO4J_URI:latest,NEO4J_USERNAME=NEO4J_USERNAME:latest,NEO4J_PASSWORD=NEO4J_PASSWORD:latest
```

Keep the function private unless there is a separate caller authentication layer.
The code does not implement request authentication by itself.

## Request

Generate next eligible article:

```bash
curl -X POST "$FUNCTION_URL" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Generate from a specific diary:

```bash
curl -X POST "$FUNCTION_URL" \
  -H "Content-Type: application/json" \
  -d '{"diary_id":"日記:2026-03-04"}'
```

Allow an explicit theme overlap only for manual recovery:

```bash
curl -X POST "$FUNCTION_URL" \
  -H "Content-Type: application/json" \
  -d '{"diary_id":"日記:2026-03-04","allow_theme_overlap":true}'
```

Mark a generated diary as published:

```bash
curl -X POST "$FUNCTION_URL" \
  -H "Content-Type: application/json" \
  -d '{"action":"mark_published","diary_id":"日記:2026-03-04","note_url":"https://note.com/..."}'
```

## Successful Artifacts

- `note_ready/{run_id}/article.md`
- `note_ready/{run_id}/article.json`
- `note_ready/{run_id}/quality_report.json`
- `note_ready/{run_id}/state_snapshot.json`

`article.json` and `state_snapshot.json` include:

- `theme_profile`
- `theme_decision`

The generated `NoteGeneration` node stores:

- `theme_cluster`
- `theme_keywords`
- `theme_basis_text`
- `theme_summary`
- `theme_profile_version`
- `theme_profile_source`
- `max_theme_similarity`
- `theme_similarity_threshold`
- `theme_history_count`

Recommended Neo4j constraints/indexes:

```cypher
CREATE CONSTRAINT note_generation_dedupe_key IF NOT EXISTS
FOR (g:NoteGeneration)
REQUIRE g.dedupe_key IS UNIQUE;

CREATE INDEX note_generation_lane_status IF NOT EXISTS
FOR (g:NoteGeneration)
ON (g.lane, g.status);
```

## Failed Artifacts

- `note_failed/{run_id}/stop_report.json`
- `note_failed/{run_id}/quality_report.json` when quality check fails

When all candidates overlap with existing themes, the function stops with:

- `reason`: `neo4j_theme_conflict`
- `theme_conflicts`: matched existing generation, title, note URL, and shared keywords
