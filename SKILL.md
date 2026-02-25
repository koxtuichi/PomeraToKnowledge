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
