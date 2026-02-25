# SKILL.md — PomeraToKnowledge プロジェクト知識

このファイルはAIエージェントがこのプロジェクトを扱う際に参照すべき知識・ルール・デバッグ知見をまとめたものです。

---

## プロジェクト概要

ポメラで書いた日記をGmailで送信し、GitHub Actionsで自動解析・ナレッジグラフ化して
GitHub Pagesで可視化するパイプライン。

- **エントリポイント:** Gmail → GAS(gas_gmail_trigger.js) → GitHub Actions → GitHub Pages
- **メインUI:** https://koxtuichi.github.io/PomeraToKnowledge/
- **主要ファイル:**
  - `index.html` — ダッシュボード（SPA: switchView関数でビュー切り替え）
  - `scripts/llm_graph_builder.py` — Gemini APIでナレッジグラフを構築
  - `scripts/sync_email.py` — Gmailからメールを取得して処理
  - `scripts/finance_parser.py` — FINCTXメールを解析して家計context生成
  - `scripts/finance_analyzer.py` — ナレッジグラフ×家計contextでリスク評価
  - `graph_data.js` — ナレッジグラフデータ（index.htmlに読み込まれる）
  - `knowledge_graph.jsonld` — グラフ本体（JSON-LD形式）
  - `finance_report.json` — 家計ダッシュボード用データ

---

## 重要な設計ルール

### ビュー切り替え（index.html）

```javascript
const ALL_VIEWS = ['advisor', 'knowbe', 'saiteki', 'family', 'graph', 'finance'];
```

新しいビューを追加するときは必ず以下4箇所を更新すること:

1. `ALL_VIEWS` 配列に追加
2. `switchView()` 内に `if (view === 'xxx') renderXxxView();` を追加
3. `mobileSwitch()` 内にも同じく追加
4. `syncMobileNav()` と `syncSidebarNav()` の `viewMap` にインデックスを追加

ナビゲーションリンクは `window.location.href='xxx.html'` で別ページに飛ばさず、
`switchView('xxx')` / `mobileSwitch('xxx')` を使うこと。

---

## GitHub Actions の注意点

### client_payload.body のシェル渡し問題

GASから `repository_dispatch` で送るメール本文（日本語・改行含む）を
ワークフロー内でシェル引数として渡すと壊れる。

**NG:**
```yaml
run: python scripts/finance_parser.py --body "${{ github.event.client_payload.body }}"
```

**OK（環境変数経由）:**
```yaml
env:
  FINCTX_BODY: ${{ github.event.client_payload.body }}
run: python scripts/finance_parser.py
```

Pythonスクリプト側で `os.environ.get("FINCTX_BODY", "")` で受け取る。

---

## 家計パイプライン

### データの流れ

```
[FINCTX]メール → GAS → repository_dispatch
  → GitHub Actions (finance_update.yml)
    → finance_parser.py  → finance_context.json
    → finance_analyzer.py × knowledge_graph.jsonld → finance_report.json
    → index.html の家計タブで表示 (renderFinanceView)
```

### 欲しいものリストの出所

`finance_report.json` の `wishlist_risk` は `knowledge_graph.jsonld` の
`type: "購入希望"` ノードから自動抽出される。
FINCTXメールに書く必要はなく、**日記に「欲しい」「買いたい」と書けば自動追加**される。

### finance_context.json の値が全て0になる場合

`FINCTX_BODY` 環境変数が空のとき（FINCTXメール未送信）は全て0になる。
正常。FINCTXメール送信後に再実行されれば値が入る。

---

## 買い物リスト・アクションの完了フィルタ

`scripts/llm_graph_builder.py` の `analyze_updated_state` 関数内で
日記テキストに「買った」「完了した」等の表現があるアイテムを除外するフィルタがある。

### 消耗品（定期購入品）の扱い

猫の餌・犬のシーツ等の消耗品は `is_recurring: true` を付けること。
このフラグがあるアイテムは完了フィルタの対象外になる（買ったと書いても除外されない）。

LLMプロンプトで消耗品には `is_recurring: true` を付けるよう指示すること。

### COMPLETION_PATTERNS (除外トリガーワード)

```python
COMPLETION_PATTERNS = [
    "買った", "注文した", "購入した", "届いた", "入手した",
    "完了した", "やった", "やりました", "済んだ", "終わった", "終わりました",
    "実行した", "解決した", "達成した", "クリアした",
    "注文済み", "購入済み", "完了済み",
]
```

---

## finance_analyzer.py の型安全性

LLMが `cost` を文字列 (`"15000"`) で返す場合があるため、
`int()` でキャストするガードが必須。

```python
try:
    cost = int(raw_cost) if raw_cost is not None else None
except (ValueError, TypeError):
    cost = None
```

`cost` が `None` の場合はリスク判定をスキップして「要確認」として扱う。

---

## graph_data.js の検証

変更後は必ず検証スクリプトを実行すること:

```bash
python3 scripts/validate_html.py graph_data.js
```

---

## セットアップ系ドキュメント

- `SETUP_GAS_TRIGGER.md` — GAS設定手順
- `SETUP_BLOG_PIPELINE.md` — ブログ生成パイプライン設定

---

## sync_email.py — 日記メール処理の注意点

### 同日に複数回日記を送信した場合

同日に何度もポメラ日記をメールで送ると、**後のメールが前の内容を上書きしていた**。
修正: 同じファイル名が存在する場合は `"w"` ではなく `"a"` 追記モードで保存するよう変更済み。
区切り行 `---` を挿入して複数回送信分をまとめて1ファイルに保管する。

```python
mode = "a" if os.path.exists(filepath) else "w"
with open(filepath, mode, encoding="utf-8") as f:
    if mode == "a":
        f.write("\n\n---\n")
    f.write(body)
```

### メールのスキップ条件

`sync_email.py` は以下の条件でメールをスキップする:

1. `uid in history` — `sync_history.txt` に記録済みのUIDは処理しない
2. `mail_time_utc < cutoff_time` — 24時間以内のメールのみ処理（夜0時を過ぎると当日の件数がリセット）

### 日記がナレッジグラフに反映されない場合のチェックリスト

1. `diary/` ディレクトリにファイルが存在するか確認
2. `sync_history.txt` に該当UIDが記録されているか確認
3. Actions の `Run Sync and Analysis` のログで「No changes to commit」なら
   LLMが同じ内容と判断→日記に新情報が含まれていないか確認
4. `force_reanalyze = true` インプットでワークフローを手動実行すると全日記を再解析できる

---

## gh CLI — GitHub Actions のデバッグに使う

**GitHub の調査はブラウザより gh CLI を優先して使うこと。**
ブラウザはログが見づらく、認証が必要な取得もできない。

### インストール

```bash
brew install gh
```

### 認証

```bash
gh auth login
# → GitHub.com → HTTPS → トークンで認証 → GHトークンをペースト
```

または環境変数で渡す:

```bash
export GH_TOKEN=ghp_xxxxxxxxxxxx
```

### よく使うコマンド

```bash
# 最新のActionsを一覧表示
gh run list --limit 10 -R koxtuichi/PomeraToKnowledge

# 特定のrunの詳細（失敗ステップを探す）
gh run view <run_id> -R koxtuichi/PomeraToKnowledge

# 特定のrunのログをリアルタイムで見る
gh run view <run_id> --log -R koxtuichi/PomeraToKnowledge

# 失敗したジョブのログだけ見る
gh run view <run_id> --log-failed -R koxtuichi/PomeraToKnowledge

# ワークフローを手動トリガー
gh workflow run sync.yml -R koxtuichi/PomeraToKnowledge

# Secretsの一覧（値は見えないがキー名は確認できる）
gh secret list -R koxtuichi/PomeraToKnowledge
```

### GitHub APIをcurlで叩く（認証なしでも使えるもの）

```bash
# Actionsの実行一覧（最近10件）
curl -s "https://api.github.com/repos/koxtuichi/PomeraToKnowledge/actions/runs?per_page=10" \
  | python3 -c "import sys,json; [print(r['id'], r['name'], r['conclusion']) for r in json.load(sys.stdin)['workflow_runs']]"

# 特定のrunのジョブとステップ一覧
curl -s "https://api.github.com/repos/koxtuichi/PomeraToKnowledge/actions/runs/<run_id>/jobs" \
  | python3 -c "import sys,json; [print(j['name'], j['conclusion'], [s['name'] for s in j['steps']]) for j in json.load(sys.stdin)['jobs']]"

# ジョブログはAPIでは認証必須 → gh run view --log を使う
```

