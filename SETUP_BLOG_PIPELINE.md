# ブログ自動公開パイプライン セットアップ手順

ポメラから「BLOG」件名のメールを送ると、AIが1話完結エッセイを生成し、はてなブログに下書き投稿する仕組みです。

---

## 1. はてなブログの準備

### アカウント情報

| 項目 | 値 |
|------|-----|
| はてなID | kakikukekoichi |
| ブログID | kakikukekoichi.hatenablog.com |
| ブログURL | https://kakikukekoichi.hatenablog.com/ |

### APIキーの確認

1. [はてなブログ](https://blog.hatena.ne.jp/) にログイン
2. ブログの「設定」→「詳細設定」
3. 「AtomPub」セクションでAPIキーを確認

---

## 2. Cloud Functions 環境変数の設定

`process-blog` の環境変数に以下を設定します。

| 環境変数名 | 値 |
|-----------|-----|
| `HATENA_ID` | `kakikukekoichi` |
| `HATENA_BLOG_ID` | `kakikukekoichi.hatenablog.com` |
| `HATENA_API_KEY` | はてなブログのAPIキー |

既存の `GOOGLE_API_KEY`, `GCS_BUCKET`, `GITHUB_REPO`, `GITHUB_TOKEN` も引き続き使います。

---

## 3. Gmail Push 入口の設定

GASは使いません。`SETUP_GMAIL_PUSH.md` に沿って `gmail-ingress` と
`refresh-gmail-watch` をデプロイしてください。

`gmail-ingress` は件名に `BLOG` を含み、`POMERA` を含まない未読メールを
`process-blog` に転送します。

---

## 4. テスト実行

1. ポメラで以下のようなテスト草案を書く:
   ```
   テーマ: ポメラという道具の魅力
   伝えたいこと: デジタルなのにアナログ感がある
   
   ・画面はモノクロ
   ・ネットに繋がらない
   ・だからこそ集中できる
   ・書くことに特化した潔さ
   ```
2. 件名「BLOG テスト記事」でGmailに送信
3. `gmail-ingress` のログで `BLOG` に分類されることを確認
4. `process-blog` のログで記事生成が完了することを確認
5. はてなブログの管理画面で「下書き」に記事が作成されていることを確認

---

## 5. 使い方

### 日常的な使い方

1. **ポメラで草案を書く** — 箇条書き、伝えたいポイント、テーマなどを自由に
2. **件名「BLOG」でGmailに送信** — メール本文に草案を書く
3. **自動的にエッセイが生成** — AIがナレッジグラフの蓄積と組み合わせて記事化
4. **はてなブログで確認** — 下書きとして投稿されるので、スマホで内容確認
5. **公開ボタンを押す** — OKなら公開

### 草案の書き方のコツ

- テーマや伝えたいことを最初に明記する
- 箇条書きでポイントを並べる
- 具体的なエピソードがあれば短くメモしておく
- 感情や気づきも書いておくとエッセイの深みが増す

---

## トラブルシューティング

| 症状 | 対処法 |
|------|--------|
| ブログに記事が投稿されない | `process-blog` の `HATENA_API_KEY` 環境変数を確認 |
| エッセイの品質が低い | 草案にもう少し具体的なエピソードを追加 |
| 二重投稿された | `blog_published/publish_history.json` を確認 |
| メールが処理されない | `gmail-ingress` のログ、件名、未読状態を確認 |
| `process-blog` に届かない | `.env.gmail.yaml` の `PROCESS_BLOG_URL` を確認 |
