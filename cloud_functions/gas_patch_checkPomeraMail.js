/**
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * Cloud Functions 呼び出し — checkPomeraMail() の差し替え用
 * 
 * 既存の checkPomeraMail() を以下に差し替えてください。
 * triggerGitHubActions() の代わりに Cloud Functions を直接呼びます。
 * 
 * 差し替え対象：gas_gmail_trigger.js の checkPomeraMail() 関数
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 */

// ── Cloud Functions の設定 ──
const CLOUD_FUNCTIONS_URL = 'https://asia-northeast1-pomeradriven.cloudfunctions.net/process-diary';

/**
 * メールの本文をプレーンテキストで取得する。
 * HTMLメールの場合はHTMLタグを除去する。
 */
function getPlainBody(message) {
    var body = message.getPlainBody();
    if (!body || body.trim().length === 0) {
        // HTMLメールの場合
        body = message.getBody();
        body = body.replace(/<br\s*\/?>/gi, '\n');
        body = body.replace(/<\/p>/gi, '\n');
        body = body.replace(/<[^>]+>/g, '');
        body = body.replace(/&nbsp;/g, ' ');
        body = body.replace(/&amp;/g, '&');
        body = body.replace(/&lt;/g, '<');
        body = body.replace(/&gt;/g, '>');
    }
    return body.trim();
}

/**
 * Cloud Functions を HTTP POST で呼ぶ。
 */
function callCloudFunction(url, payload) {
    var options = {
        method: 'post',
        contentType: 'application/json',
        payload: JSON.stringify(payload),
        muteHttpExceptions: true,
        // タイムアウトをCloud Function側と合わせる（最大6分）
        // GASのUrlFetchAppはデフォルト60秒なので延長不可だが、
        // Cloud Functionは非同期で処理するので問題ない
    };

    try {
        var response = UrlFetchApp.fetch(url, options);
        var code = response.getResponseCode();

        if (code === 200) {
            var result = JSON.parse(response.getContentText());
            console.log('✅ Cloud Function 成功: ' + JSON.stringify(result));
            return true;
        } else {
            console.error('❌ Cloud Function エラー: ' + code + ' - ' + response.getContentText().substring(0, 300));
            return false;
        }
    } catch (e) {
        console.error('❌ Cloud Function 呼び出し失敗: ' + e.message);
        return false;
    }
}

/**
 * POMERAメール検知 → Cloud Functions で処理
 * 
 * 変更点:
 *   - メール本文を取得してCloud Functionsに送信
 *   - GitHub Actions の triggerGitHubActions() は呼ばない
 *   - 重複防止の3層防御はそのまま維持
 */
function checkPomeraMail() {
    // 防御1: 排他制御
    var lock = LockService.getScriptLock();
    if (!lock.tryLock(3000)) {
        console.log('⏳ 他のPOMERAトリガーが処理中。スキップします');
        return;
    }

    try {
        var threads = GmailApp.search(CONFIG.GMAIL_QUERY);

        if (threads.length === 0) {
            return;
        }

        console.log('📬 ' + threads.length + ' 件のPOMERAメールを検出');

        var msg = threads[0].getMessages()[threads[0].getMessageCount() - 1];
        var msgId = msg.getId();

        // 防御3: メッセージID重複チェック
        if (isAlreadyProcessed(msgId, 'POMERA')) {
            threads.forEach(function (thread) { thread.markRead(); });
            return;
        }

        // 防御2: 先に既読にして次のポーリングで検知されないようにする
        threads.forEach(function (thread) { thread.markRead(); });

        var subject = threads[0].getFirstMessageSubject();
        var body = getPlainBody(msg);

        if (!body || body.length === 0) {
            console.error('⚠️ メール本文が空です。スキップします');
            return;
        }

        console.log('📝 メール本文: ' + body.length + ' 文字');

        // Cloud Functions を呼ぶ
        var success = callCloudFunction(CLOUD_FUNCTIONS_URL, {
            subject: subject,
            body: body
        });

        if (success) {
            markAsProcessed(msgId, 'POMERA');
            console.log('✅ Cloud Functions で処理完了');
        } else {
            threads.forEach(function (thread) { thread.markUnread(); });
            console.error('⚠️ Cloud Functions 失敗のため未読に戻しました');
        }

    } finally {
        lock.releaseLock();
    }
}
