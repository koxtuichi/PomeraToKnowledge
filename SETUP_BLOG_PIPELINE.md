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

## 2. GitHub Secrets の設定

リポジトリの Settings → Secrets and variables → Actions で以下を追加:

| Secret名 | 値 |
|-----------|-----|
| `HATENA_ID` | `kakikukekoichi` |
| `HATENA_BLOG_ID` | `kakikukekoichi.hatenablog.com` |
| `HATENA_API_KEY` | はてなブログのAPIキー |

既存のSecrets（`GOOGLE_API_KEY`, `GMAIL_ACCOUNT`, `GMAIL_APP_PASSWORD`）はそのまま使用します。

---

## 3. GAS トリガーの追加設定

### 3-1. スクリプトの更新

1. [script.google.com](https://script.google.com) で「PomeraToKnowledge Trigger」を開く
2. `scripts/gas_gmail_trigger.js` の最新内容で全体を更新する
3. 保存

### 3-2. トリガーの追加

1. 左メニューの ⏰「トリガー」をクリック
2. 「トリガーを追加」をクリック
3. 以下のように設定:
   - **実行する関数**: `checkBlogMail`
   - **イベントのソース**: 時間主導型
   - **時間ベースのトリガーのタイプ**: 分ベースのタイマー
   - **間隔**: 1分おき
4. 「保存」をクリック

---

## 4. テスト実行

### 4-1. GASからのテスト

1. GASエディタで `testBlogTrigger` 関数を選択
2. ▶ 実行ボタンをクリック
3. GitHub Actions のページで Blog ワークフローが起動されたことを確認

### 4-2. ポメラからのテスト

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
3. 1-2分後、GitHub Actions が起動
4. はてなブログの管理画面で「下書き」に記事が作成されていることを確認

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
| ブログに記事が投稿されない | GitHub Secretsの `HATENA_API_KEY` を確認 |
| エッセイの品質が低い | 草案にもう少し具体的なエピソードを追加 |
| 二重投稿された | `blog_published/publish_history.json` を確認 |
| ワークフローが起動しない | GASで `checkBlogMail` のトリガーが設定されているか確認 |
