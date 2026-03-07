/**
 * PomeraToKnowledge — Gmail → Cloud Functions トリガー
 * 
 * 全ての処理をCloud Functionsに移行した完全版。
 * GASの役割: メール検知 → Cloud FunctionsにHTTPリクエスト
 * 
 * ■ Cloud Functions エンドポイント
 *   - process-diary:   日記 → ナレッジグラフ更新
 *   - process-blog:    ブログ草案 → 記事生成 → はてな投稿
 *   - process-story:   小説テーマ → フィクション生成 → はてな投稿
 *   - process-finance: 家計テキスト → 分析レポート生成
 * 
 * ■ 重複防止策（3層防御）
 *   1. LockService: 同時実行を排他制御
 *   2. 既読化を先に実行: 次のポーリングで検知されない
 *   3. メッセージID記録: 処理済みメールをスキップ
 */

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 設定
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

var CONFIG = {
    GITHUB_OWNER: 'koxtuichi',
    GITHUB_REPO: 'PomeraToKnowledge',
    GMAIL_QUERY: 'subject:POMERA is:unread newer_than:1h',
    LABEL_NAME: 'PomeraProcessed'
};

// Cloud Functions のURL
var CLOUD_FUNCTIONS_BASE = 'https://asia-northeast1-pomeradriven.cloudfunctions.net';

var CLOUD_FUNCTIONS = {
    DIARY: CLOUD_FUNCTIONS_BASE + '/process-diary',
    BLOG: CLOUD_FUNCTIONS_BASE + '/process-blog',
    STORY: CLOUD_FUNCTIONS_BASE + '/process-story',
    FINANCE: CLOUD_FUNCTIONS_BASE + '/process-finance',
    SNS_APPROVAL: CLOUD_FUNCTIONS_BASE + '/process-sns-approval'
};

var BLOG_CONFIG = {
    GMAIL_QUERY: 'subject:BLOG is:unread newer_than:1h -subject:POMERA'
};

var STORY_CONFIG = {
    GMAIL_QUERY: 'subject:STORY is:unread newer_than:1h -subject:POMERA -subject:BLOG'
};

var FINCTX_CONFIG = {
    GMAIL_QUERY: 'subject:FINCTX is:unread newer_than:24h'
};

var SNS_CONFIG = {
    GMAIL_QUERY: 'subject:"Re: [SNS承認]" is:unread newer_than:24h'
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// ユーティリティ
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/**
 * メールの本文をプレーンテキストで取得する。
 */
function getPlainBody(message) {
    var body = message.getPlainBody();
    if (!body || body.trim().length === 0) {
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
        muteHttpExceptions: true
    };

    try {
        var response = UrlFetchApp.fetch(url, options);
        var code = response.getResponseCode();

        if (code === 200) {
            var result = JSON.parse(response.getContentText());
            console.log('✅ Cloud Function 成功: ' + JSON.stringify(result));
            return result;
        } else {
            console.error('❌ Cloud Function エラー: ' + code + ' - ' + response.getContentText().substring(0, 300));
            return null;
        }
    } catch (e) {
        console.error('❌ Cloud Function 呼び出し失敗: ' + e.message);
        return false;
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 重複防止ユーティリティ
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function isAlreadyProcessed(messageId, category) {
    var props = PropertiesService.getScriptProperties();
    var key = 'PROCESSED_' + category;
    var raw = props.getProperty(key) || '[]';

    var processedIds;
    try {
        processedIds = JSON.parse(raw);
    } catch (e) {
        processedIds = [];
    }

    if (processedIds.indexOf(messageId) !== -1) {
        console.log('⏭️ メッセージID ' + messageId + ' は処理済み。スキップします');
        return true;
    }
    return false;
}

function markAsProcessed(messageId, category) {
    var props = PropertiesService.getScriptProperties();
    var key = 'PROCESSED_' + category;
    var raw = props.getProperty(key) || '[]';

    var processedIds;
    try {
        processedIds = JSON.parse(raw);
    } catch (e) {
        processedIds = [];
    }

    processedIds.push(messageId);
    if (processedIds.length > 20) {
        processedIds = processedIds.slice(-20);
    }

    props.setProperty(key, JSON.stringify(processedIds));
    console.log('📌 メッセージID ' + messageId + ' を処理済みとして記録');
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// POMERA日記メール検知
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function checkPomeraMail() {
    var lock = LockService.getScriptLock();
    if (!lock.tryLock(3000)) {
        console.log('⏳ 他のPOMERAトリガーが処理中。スキップします');
        return;
    }

    try {
        var threads = GmailApp.search(CONFIG.GMAIL_QUERY);
        if (threads.length === 0) return;

        console.log('📬 ' + threads.length + ' 件のPOMERAメールを検出');

        var msg = threads[0].getMessages()[threads[0].getMessageCount() - 1];
        var msgId = msg.getId();

        if (isAlreadyProcessed(msgId, 'POMERA')) {
            threads.forEach(function (t) { t.markRead(); });
            return;
        }

        threads.forEach(function (t) { t.markRead(); });

        var subject = threads[0].getFirstMessageSubject();
        var body = getPlainBody(msg);

        if (!body || body.length === 0) {
            console.error('⚠️ メール本文が空です');
            return;
        }

        var result = callCloudFunction(CLOUD_FUNCTIONS.DIARY, {
            subject: subject,
            body: body
        });

        if (result) {
            markAsProcessed(msgId, 'POMERA');
            console.log('✅ Cloud Functions で日記処理完了');

            // SNS投稿が生成された場合、承認メールを送信
            if (result.sns_generated_posts && result.sns_generated_posts.length > 0) {
                sendSnsApprovalEmail(result.sns_generated_posts);
            }
        } else {
            threads.forEach(function (t) { t.markUnread(); });
            console.error('⚠️ Cloud Functions 失敗のため未読に戻しました');
        }

    } finally {
        lock.releaseLock();
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// BLOG メール検知
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function checkBlogMail() {
    var lock = LockService.getScriptLock();
    if (!lock.tryLock(3000)) {
        console.log('⏳ 他のBLOGトリガーが処理中。スキップします');
        return;
    }

    try {
        var threads = GmailApp.search(BLOG_CONFIG.GMAIL_QUERY);
        if (threads.length === 0) return;

        console.log('📝 ' + threads.length + ' 件のBLOGメールを検出');

        var msg = threads[0].getMessages()[threads[0].getMessageCount() - 1];
        var msgId = msg.getId();
        var subject = threads[0].getFirstMessageSubject();
        var body = getPlainBody(msg);

        if (isAlreadyProcessed(msgId, 'BLOG')) {
            threads.forEach(function (t) { t.markRead(); });
            return;
        }

        threads.forEach(function (t) { t.markRead(); });

        var success = callCloudFunction(CLOUD_FUNCTIONS.BLOG, {
            subject: subject,
            body: body
        });

        if (success) {
            markAsProcessed(msgId, 'BLOG');
            console.log('✅ Cloud Functions でブログ処理完了');
        } else {
            threads.forEach(function (t) { t.markUnread(); });
            console.error('⚠️ Cloud Functions 失敗のため未読に戻しました');
        }

    } finally {
        lock.releaseLock();
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// STORY メール検知
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function checkStoryMail() {
    var lock = LockService.getScriptLock();
    if (!lock.tryLock(3000)) {
        console.log('⏳ 他のSTORYトリガーが処理中。スキップします');
        return;
    }

    try {
        var threads = GmailApp.search(STORY_CONFIG.GMAIL_QUERY);
        if (threads.length === 0) return;

        console.log('📖 ' + threads.length + ' 件のSTORYメールを検出');

        var msg = threads[0].getMessages()[threads[0].getMessageCount() - 1];
        var msgId = msg.getId();
        var subject = threads[0].getFirstMessageSubject();
        var body = getPlainBody(msg);

        if (isAlreadyProcessed(msgId, 'STORY')) {
            threads.forEach(function (t) { t.markRead(); });
            return;
        }

        threads.forEach(function (t) { t.markRead(); });

        var success = callCloudFunction(CLOUD_FUNCTIONS.STORY, {
            subject: subject,
            body: body
        });

        if (success) {
            markAsProcessed(msgId, 'STORY');
            console.log('✅ Cloud Functions で小説処理完了');
        } else {
            threads.forEach(function (t) { t.markUnread(); });
            console.error('⚠️ Cloud Functions 失敗のため未読に戻しました');
        }

    } finally {
        lock.releaseLock();
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// FINCTX 家計コンテキスト メール検知
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function checkFinCtxMail() {
    var lock = LockService.getScriptLock();
    if (!lock.tryLock(3000)) {
        console.log('⏳ 他のFINCTXトリガーが処理中。スキップします');
        return;
    }

    try {
        var threads = GmailApp.search(FINCTX_CONFIG.GMAIL_QUERY);
        if (threads.length === 0) return;

        console.log('💰 ' + threads.length + ' 件のFINCTXメールを検出');

        var msg = threads[0].getMessages()[threads[0].getMessages().length - 1];
        var msgId = msg.getId();
        var subject = msg.getSubject();
        var body = getPlainBody(msg);

        if (isAlreadyProcessed(msgId, 'FINCTX')) {
            threads.forEach(function (t) { t.markRead(); });
            return;
        }

        threads.forEach(function (t) { t.markRead(); });

        var success = callCloudFunction(CLOUD_FUNCTIONS.FINANCE, {
            subject: subject,
            body: body
        });

        if (success) {
            markAsProcessed(msgId, 'FINCTX');
            console.log('✅ Cloud Functions で家計処理完了');
        } else {
            threads.forEach(function (t) { t.markUnread(); });
            console.error('⚠️ Cloud Functions 失敗のため未読に戻しました');
        }

    } finally {
        lock.releaseLock();
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// テスト用
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function testDiaryTrigger() {
    var result = callCloudFunction(CLOUD_FUNCTIONS.DIARY, {
        subject: '[TEST] POMERAテスト送信',
        body: 'テスト日記です。Cloud Functionsの動作確認。'
    });
    console.log(result ? '✅ 日記テスト成功！' : '❌ 日記テスト失敗');
}

function testBlogTrigger() {
    var result = callCloudFunction(CLOUD_FUNCTIONS.BLOG, {
        subject: '[TEST] BLOGテスト送信',
        body: 'テスト: ポメラで書くことの楽しさについて'
    });
    console.log(result ? '✅ ブログテスト成功！' : '❌ ブログテスト失敗');
}

function testStoryTrigger() {
    var result = callCloudFunction(CLOUD_FUNCTIONS.STORY, {
        subject: '[TEST] STORYテスト送信',
        body: 'テーマ: テクノロジーと人間\nジャンル: SF\nトーン: 哲学的\n伝えたいこと: 便利さの裏にある代償'
    });
    console.log(result ? '✅ 小説テスト成功！' : '❌ 小説テスト失敗');
}

function testFinanceTrigger() {
    var result = callCloudFunction(CLOUD_FUNCTIONS.FINANCE, {
        subject: '[TEST] FINCTXテスト送信',
        body: '収入: Knowbe 650000円\n副業: Saiteki 80000円\nセゾンゴールド 171412円'
    });
    console.log(result ? '✅ 家計テスト成功！' : '❌ 家計テスト失敗');
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 処理済みID管理用ユーティリティ
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function showProcessedIds() {
    var props = PropertiesService.getScriptProperties();
    var categories = ['POMERA', 'BLOG', 'STORY', 'FINCTX'];

    categories.forEach(function (cat) {
        var raw = props.getProperty('PROCESSED_' + cat) || '[]';
        console.log(cat + ': ' + raw);
    });
}

function resetProcessedIds() {
    var props = PropertiesService.getScriptProperties();
    var categories = ['POMERA', 'BLOG', 'STORY', 'FINCTX', 'SNS_APPROVAL'];

    categories.forEach(function (cat) {
        props.deleteProperty('PROCESSED_' + cat);
        console.log('🗑️ ' + cat + ' の処理済みIDをリセットしました');
    });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SNS 承認メール送信
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/**
 * SNS投稿の承認メールを自分に送信する。
 * Geminiが生成した投稿文を確認して、返信するだけで承認される。
 */
function sendSnsApprovalEmail(snsPosts) {
    var bodyLines = ['以下のSNS投稿がGeminiによって生成されました。', ''];
    bodyLines.push('▼ このメールに返信するだけで全ての投稿が承認されます。');
    bodyLines.push('▼ 最適な時間帯に自動的にThreadsに投稿されます。');
    bodyLines.push('');
    bodyLines.push('━━━━━━━━━━━━━━━━━━━━━━━━━━');

    for (var i = 0; i < snsPosts.length; i++) {
        var post = snsPosts[i];
        bodyLines.push('');
        bodyLines.push('【投稿 ' + (i + 1) + '】ID: ' + post.id);
        bodyLines.push('');
        bodyLines.push('元のテキスト:');
        bodyLines.push(post.original);
        bodyLines.push('');
        bodyLines.push('生成された投稿文:');
        bodyLines.push('─────────────────');
        bodyLines.push(post.generated);
        bodyLines.push('─────────────────');
        bodyLines.push('');
    }

    bodyLines.push('━━━━━━━━━━━━━━━━━━━━━━━━━━');
    bodyLines.push('');
    bodyLines.push('承認する場合: このメールに返信してください');

    var myEmail = Session.getActiveUser().getEmail();
    GmailApp.sendEmail(myEmail, '[SNS承認] Threads投稿の確認', bodyLines.join('\n'));
    console.log('📧 SNS承認メールを送信しました');
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SNS 承認メール検知
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/**
 * SNS承認メールの返信を検知し、Cloud Functionで承認処理を実行する。
 * トリガー: 1分ごと
 */
function checkSnsApprovalMail() {
    var lock = LockService.getScriptLock();
    if (!lock.tryLock(3000)) {
        console.log('⏳ 他のSNS承認トリガーが処理中。スキップします');
        return;
    }

    try {
        var threads = GmailApp.search(SNS_CONFIG.GMAIL_QUERY);
        if (threads.length === 0) return;

        console.log('📱 ' + threads.length + ' 件のSNS承認メールを検出');

        for (var t = 0; t < threads.length; t++) {
            var thread = threads[t];
            var messages = thread.getMessages();
            var latestMsg = messages[messages.length - 1];
            var msgId = latestMsg.getId();

            if (isAlreadyProcessed(msgId, 'SNS_APPROVAL')) {
                thread.markRead();
                continue;
            }

            thread.markRead();

            // Cloud Functionで全pending投稿を承認
            var result = callCloudFunction(CLOUD_FUNCTIONS.SNS_APPROVAL, {
                approve_all: true
            });

            if (result) {
                markAsProcessed(msgId, 'SNS_APPROVAL');
                console.log('✅ SNS投稿 ' + result.approved_count + ' 件を承認しました');
            } else {
                thread.markUnread();
                console.error('⚠️ SNS承認処理に失敗しました');
            }
        }

    } finally {
        lock.releaseLock();
    }
}
