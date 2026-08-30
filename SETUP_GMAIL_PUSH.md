# Gmail Push / Cloud Functions セットアップ手順

PomeraからGmailへ送られたメールを、Google Apps Scriptを使わずに処理する構成です。
推奨はGmail Push通知ですが、OAuthクライアントのGmailスコープ承認が整うまでは
Cloud Scheduler + IMAPポーリングでも運用できます。どちらもGASは使いません。

```
Pomera -> Gmail -> Gmail API watch -> Pub/Sub -> gmail-ingress
  -> process-diary / process-blog / process-story / process-secblog
```

## 1. Google Cloud API を有効化する

```bash
gcloud services enable \
  gmail.googleapis.com \
  pubsub.googleapis.com \
  cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  eventarc.googleapis.com \
  cloudscheduler.googleapis.com
```

## 2. Pub/Sub トピックを作る

```bash
gcloud pubsub topics create gmail-push
gcloud pubsub topics add-iam-policy-binding gmail-push \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

Gmail API Push通知では、GmailがPub/Subへ publish できるように
`gmail-api-push@system.gserviceaccount.com` へ `roles/pubsub.publisher` を付与します。

## 3. Gmail OAuth 情報を用意する

Gmail APIの `watch` と `history.list` を使うため、OAuthクライアントとrefresh tokenを用意します。

必要なスコープ:

```text
https://www.googleapis.com/auth/gmail.modify
```

`gmail.modify` は処理後に `UNREAD` ラベルを外すために使います。既読化しない場合は
`.env.gmail.yaml` の `GMAIL_MARK_READ` を `"false"` にします。

refresh tokenは、Google Cloud ConsoleでOAuthクライアントを作成し、OAuth 2.0 Playground
などで上記スコープを承認して取得します。取得した値は `.env.gmail.yaml` にだけ置き、
リポジトリにはコミットしません。

OAuthがまだ用意できない場合は、既存の `GMAIL_APP_PASSWORD` を使うIMAPポーリング方式で
先にGASを廃止できます。

## 4. 環境変数ファイルを作る

```bash
cp .env.gmail.example.yaml .env.gmail.yaml
```

少なくとも以下を設定します。

```yaml
GMAIL_ACCOUNT: your-account@gmail.com
GMAIL_APP_PASSWORD: your-gmail-app-password
GMAIL_OAUTH_CLIENT_ID: your-oauth-client-id.apps.googleusercontent.com
GMAIL_OAUTH_CLIENT_SECRET: your-oauth-client-secret
GMAIL_OAUTH_REFRESH_TOKEN: your-oauth-refresh-token
GMAIL_PUBSUB_TOPIC: projects/pomeradriven/topics/gmail-push
GITHUB_TOKEN: your-github-token
GOOGLE_API_KEY: your-gemini-api-key
```

`PROCESS_*_URL` は既存Cloud FunctionsのURLです。空の `PROCESS_FINANCE_URL` は
対応する関数をデプロイした後に設定します。

`POMERA_INTERNAL_TOKEN` を設定すると、`gmail-ingress` は既存処理関数へ
`X-Pomera-Internal-Token` ヘッダーを付けて転送します。同じ値を
`process-diary` / `process-blog` / `process-story` / `process-secblog` 側にも
環境変数として設定すると、直接呼び出しを拒否できます。空のままなら従来通り認証なしで動きます。

## 5A. IMAPポーリング方式で先にデプロイする

OAuthがブロックされる、または未準備の場合はこちらを使います。

```bash
./cloud_functions/gmail_ingress/deploy_polling.sh
```

デプロイされる関数:

| 関数 | 種別 | 役割 |
| --- | --- | --- |
| `poll-gmail` | HTTP + Scheduler | 未読メールをIMAPで取得し、既存処理関数へ転送 |

Cloud Scheduler job `poll-gmail-every-minute` は1分おきに実行されます。
これはGASの1分トリガーをCloud Functionsへ置き換える運用です。
初回に未読メールが多い場合でも詰まらないよう、`GMAIL_POLL_MAX_MESSAGES` で
1回あたりの確認件数を制限できます。

## 5B. Gmail Push方式でデプロイする

Schedulerから認証付きで `refresh-gmail-watch` を呼ぶためのサービスアカウントを指定します。

```bash
SCHEDULER_SERVICE_ACCOUNT=your-scheduler-sa@pomeradriven.iam.gserviceaccount.com \
  ./cloud_functions/gmail_ingress/deploy.sh
```

デプロイされる関数:

| 関数 | 種別 | 役割 |
| --- | --- | --- |
| `gmail-ingress` | Pub/Sub trigger | Gmail通知を受け、対象メールを既存処理関数へ転送 |
| `refresh-gmail-watch` | HTTP | Gmail `watch` を更新 |

Cloud Scheduler job `refresh-gmail-watch-daily` は毎日9時（Asia/Tokyo）に実行されます。
Gmail `watch` は少なくとも7日に1回更新が必要なので、日次更新にしています。

## 6. 初回 watch を作成する

デプロイ後、Scheduler jobを手動実行するか、`refresh-gmail-watch` を認証付きで呼びます。

```bash
gcloud scheduler jobs run refresh-gmail-watch-daily --location=asia-northeast1
```

成功するとGCSの `gmail_push/state.json` に `watch_history_id` と `watch_expiration` が保存されます。

## 7. 動作確認

1. 件名に `POMERA` を含む未読メールをGmailへ送る
2. `gmail-ingress` のログで対象メールが `POMERA` に分類されることを確認
3. `process-diary` のログで日記処理が完了することを確認
4. `graph_data.js` / `knowledge_graph.jsonld` / `reports/` がGitHubに反映されることを確認

ブログ系は件名で分類されます。

| 件名に含む文字 | 転送先 |
| --- | --- |
| `POMERA` | `process-diary` |
| `DIARY` | `process-diary` |
| `BLOG` | `process-blog` |
| `STORY` | `process-story` |
| `SECBLOG` | `process-secblog` |
| `FINCTX` | `PROCESS_FINANCE_URL` 設定時のみ |

## 8. GASの扱い

この構成ではGoogle Apps Scriptは使いません。既存のGASトリガーは停止し、
Apps Scriptプロジェクトは削除して問題ありません。

## 9. 料金の目安

この用途では、増える固定的なGoogle Cloudリソースは `gmail-ingress`、
`refresh-gmail-watch`、Pub/Sub topic、Scheduler job 1本です。

| 項目 | 見積もり観点 |
| --- | --- |
| Cloud Functions / Cloud Run functions | request-based free tier にリクエスト・CPU秒・GiB秒の無料枠がある。日記処理が重いので、支配要因は通知数より `process-diary` の実行時間 |
| Pub/Sub | Gmail通知は小さいため、通常は月10GiB無料枠にかなり余裕がある |
| Cloud Scheduler | `refresh-gmail-watch-daily` 1ジョブだけなら3ジョブ/月の無料枠内 |
| Gmail API | API自体に課金はないが、OAuth設定と割り当て制限に注意 |
| Gemini / Neo4j / Cloud Storage / Logging | 既存パイプライン側の利用量に依存。今回の入口移行でAI処理回数が増えなければ大きくは変わらない |

実運用後は、Cloud Loggingで `gmail-ingress` の通知数と `process-diary` の平均実行時間を見て、
月次の実行時間を確認します。

## トラブルシューティング

| 症状 | 対処法 |
| --- | --- |
| Gmail通知が来ない | Pub/Subトピック名、Gmail publish権限、`watch_expiration` を確認 |
| `historyId` が古い | `gmail_push/state.json` の `history_reset_reason` を確認し、必要なら手動バックフィル |
| メールが処理されない | 件名、未読状態、`GMAIL_REQUIRE_UNREAD` を確認 |
| 既存処理関数への転送に失敗 | `PROCESS_*_URL` と対象Cloud Functionのログを確認 |
| 二重処理される | `gmail_push/state.json` の `processed_message_ids` とPub/Sub retryを確認 |
