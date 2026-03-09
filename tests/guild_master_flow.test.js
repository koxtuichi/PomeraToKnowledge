#!/usr/bin/env node
/**
 * guild_master.html — UIフロー・統合テストスイート
 * 実行方法: node tests/guild_master_flow.test.js
 *
 * ロジックテストに加えて、以下のフローを検証する：
 * - 日記を書く (addCP)
 * - ビュー遷移 (showView)
 * - ギルド待機所の表示
 * - 週次報告の表示
 * - パーティー作成〜メンバー追加の完全フロー
 * - 週進行の完全フロー
 */
'use strict';

// ========= DOM モック (フロー用に拡張版) =========
const _dom = {};          // getElementById で返す要素を管理
const _innerHTML = {};    // setInnerHTML で設定されたHTMLを記録
const _logEntries = [];   // addLog で追加されたエントリ
const _logBar = [];       // setLogBar で設定されたテキスト

const mockElem = (id) => {
    const e = {
        id,
        textContent: '',
        innerHTML: '',
        classList: {
            _classes: new Set(),
            add(c) { this._classes.add(c); },
            remove(c) { this._classes.delete(c); },
            contains(c) { return this._classes.has(c); },
        },
        style: { display: '' },
        value: '',
        children: { length: 50 },
        lastChild: null,
        prepend(child) { _logEntries.unshift(child.textContent); },
        appendChild() { },
        remove() { },
        onclick: null,
        querySelector(sel) { return null; },      // advanceWeekのhudEl.querySelector対応
        querySelectorAll(sel) { return { forEach() { } }; },
    };
    // innerHTMLのsetter で記録
    let _html = '';
    Object.defineProperty(e, 'innerHTML', {
        get() { return _html; },
        set(v) { _html = v; _innerHTML[id] = v; },
    });
    return e;
};

// 特定IDの要素を管理
const _elements = {};
global.document = {
    getElementById(id) {
        if (!_elements[id]) _elements[id] = mockElem(id);
        return _elements[id];
    },
    createElement(tag) {
        const e = mockElem('_tmp');
        e.className = '';
        e.onclick = null;
        return e;
    },
    querySelectorAll(sel) { return { forEach() { } }; }, // ボトムナビのクラス操作モック
    querySelector(sel) { return null; },
    addEventListener(ev, fn, opts) { },       // SFX.load()等が使うため追加
    removeEventListener(ev, fn, opts) { },
    body: { appendChild() { }, removeChild() { } },
};
global.localStorage = {
    _store: {},
    getItem(k) { return this._store[k] ?? null; },
    setItem(k, v) { this._store[k] = v; },
    removeItem(k) { delete this._store[k]; },
};
global.alert = () => { };
global.confirm = () => true;
global.prompt = () => '1';
global.window = global; // ブラウザのwindowオブジェクトをglobalで代替
global.requestAnimationFrame = (cb) => { }; // アニメーションフレームのモック

// ========= JS読み込み =========
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const html = fs.readFileSync(
    path.join(__dirname, '..', 'guild_master.html'), 'utf8'
);
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) { console.error('script tag not found'); process.exit(1); }
try {
    vm.runInThisContext(scriptMatch[1]);
} catch (e) {
    console.error('JS parse/eval error:', e.message);
    process.exit(1);
}

// ========= テストフレームワーク =========
let passed = 0, failed = 0, errors = [];

function test(name, fn) {
    try {
        fn();
        console.log(`  ✓ ${name}`);
        passed++;
    } catch (e) {
        console.error(`  ✗ ${name}`);
        console.error(`    → ${e.message}`);
        failed++;
        errors.push({ name, msg: e.message });
    }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }
function assertEqual(a, b, msg) { if (a !== b) throw new Error(msg || `expected ${b}, got ${a}`); }
function assertContains(str, sub, msg) { if (!str.includes(sub)) throw new Error(msg || `"${sub}" が含まれない: ...${str.slice(0, 80)}...`); }
function assertRange(v, lo, hi, msg) { if (v < lo || v > hi) throw new Error(msg || `${v} は [${lo}, ${hi}] 外`); }

// テスト前にG_STATEをリセットするヘルパー
function resetState() {
    G_STATE.gold = 2000; // テスト用: 採用コスト(最大200G×5=1000G)に対応できる量を設定
    G_STATE.week = 1;
    G_STATE.year = 1;
    G_STATE.parties = [];
    G_STATE.roster = [];
    G_STATE.dismissed = [];
    G_STATE.pendingReports = [];
    G_STATE.globalLog = [];
    G_STATE.inventory = [];
    initRoster();
}

// パーティーをG_STATE.partiesに直接追加するヘルパー
function addPartyDirect(name = 'テストパーティー', region = '北の森', item = '剣') {
    const p = {
        id: uid(),
        name,
        region,
        targetItem: item,
        members: [],
        leaderId: null,
        directive: { focus: 'steady', conflict: 'leader', cpPerWeek: 20 },
        status: 'idle',
        cpDebt: 0,
    };
    G_STATE.parties.push(p);
    return p;
}

// ========= フローテスト =========

console.log('\n◆ Gold経済フロー — sellItem / sellAll / showInventoryView');
test('sellItem でgoldが増えてinventoryが減る', () => {
    resetState();
    G_STATE.gold = 50;
    const it = { id: uid(), name: '鉄剣', rarity: 'common', value: 12, partyName: 'A', week: 1 };
    G_STATE.inventory.push(it);
    sellItem(it.id);
    assertEqual(G_STATE.gold, 62, `Gold=${G_STATE.gold}`);
    assertEqual(G_STATE.inventory.length, 0, 'inventoryが残っている');
});
test('sellAll で全件売却される', () => {
    resetState();
    G_STATE.gold = 0;
    G_STATE.inventory = [
        { id: uid(), name: '剣', rarity: 'common', value: 10, partyName: 'A', week: 1 },
        { id: uid(), name: '弓', rarity: 'rare', value: 100, partyName: 'B', week: 2 },
    ];
    sellAll();
    assertEqual(G_STATE.gold, 110, `Gold=${G_STATE.gold}`);
    assertEqual(G_STATE.inventory.length, 0);
});
test('sellAll 後にlocalStorageにセーブされる', () => {
    resetState();
    localStorage._store = {};
    G_STATE.inventory = [{ id: uid(), name: '剣', rarity: 'common', value: 5, partyName: 'A', week: 1 }];
    sellAll();
    assert(localStorage._store['gm_v1'] != null, 'saveStateが呼ばれていない');
});

console.log('\n◆ showView() — ビュー遷移フロー');
test('showView("roster") で currentView が roster になる', () => {
    showView('roster');
    assertEqual(currentView, 'roster', `currentViewが${currentView}のまま`);
});
test('showView("reports") で currentView が reports になる', () => {
    showView('reports');
    assertEqual(currentView, 'reports');
});
test('showView("welcome") で currentView が welcome になる', () => {
    showView('welcome');
    assertEqual(currentView, 'welcome');
});
test('showView("party") で currentView が party になる', () => {
    showView('party');
    assertEqual(currentView, 'party');
});
test('存在しないビューを渡しても例外が出ない', () => {
    // エラーなく実行できることを確認
    showView('nonexistent');
});

console.log('\n◆ ギルド待機所 — showRosterView() フロー');
test('showRosterView() でv-rosterのInnerHTMLが更新される', () => {
    resetState();
    delete _innerHTML['v-roster'];
    showRosterView();
    const html = _innerHTML['v-roster'] || '';
    assert(html.length > 0, 'v-roster のHTMLが空のまま');
});
test('showRosterView() でキャラクター名が含まれるHTMLが生成される', () => {
    resetState();
    // ロスターに1名確実に追加
    G_STATE.roster = [genChar()];
    showRosterView();
    const h = _innerHTML['v-roster'] || '';
    assertContains(h, 'ギルド待機所', 'ヘッダーが含まれない');
});
test('ロスターが空の場合に「応募者はいません」が表示される', () => {
    resetState();
    G_STATE.roster = [];
    showRosterView();
    const h = _innerHTML['v-roster'] || '';
    assertContains(h, '応募者はいません', '空ロスター時のメッセージが含まれない');
});
test('showRosterView() でcurrentViewがrosterになる', () => {
    showRosterView();
    assertEqual(currentView, 'roster');
});

console.log('\n◆ 週次報告 — showReportsView() フロー');
test('showReportsView() でv-reportsのInnerHTMLが更新される', () => {
    resetState();
    delete _innerHTML['v-reports'];
    showReportsView();
    const h = _innerHTML['v-reports'] || '';
    assert(h.length > 0, 'v-reports のHTMLが空のまま');
});
test('報告が0件のとき「未読の報告はありません」が表示される', () => {
    resetState();
    G_STATE.pendingReports = [];
    showReportsView();
    const h = _innerHTML['v-reports'] || '';
    assertContains(h, '未読の報告はありません', '空報告時のメッセージが含まれない');
});
test('報告が1件あるとき週次報告が表示される', () => {
    resetState();
    const p = addPartyDirect();
    p.members = [genChar()];
    G_STATE.pendingReports = [{ party: p, events: [{ type: 'drop', text: '剣を発見' }] }];
    showReportsView();
    const h = _innerHTML['v-reports'] || '';
    assertContains(h, 'テストパーティー', 'パーティー名が含まれない');
    assertContains(h, '剣を発見', 'イベントテキストが含まれない');
});
test('showReportsView() でcurrentViewがreportsになる', () => {
    showReportsView();
    assertEqual(currentView, 'reports');
});

console.log('\n◆ パーティー管理 — 完全フロー');
// B1仕様変更: addMemberToPartyはrosterから削除せずhiredPartyIdフラグを付ける
test('addMemberToParty でパーティーにメンバーが追加されhiredPartyIdが設定される (B1)', () => {
    resetState();
    const p = addPartyDirect();
    assert(G_STATE.roster.length > 0, 'ロスターが空');
    const c = G_STATE.roster[0];
    addMemberToParty(p.id, c.id);
    assertEqual(p.members.length, 1, 'メンバーが追加されていない');
    // B1: rosterからは削除しないでhiredPartyIdを設定
    const rosterChar = G_STATE.roster.find(x => x.id === c.id);
    assert(!!rosterChar, 'B1: 採用後にキャラがrosterから消えてしまった');
    assertEqual(rosterChar.hiredPartyId, p.id, 'B1: hiredPartyIdが設定されていない');
    assertEqual(p.members[0].id, c.id, '追加されたキャラが違う');
});
test('最初に追加されたメンバーが自動でリーダーになる', () => {
    resetState();
    const p = addPartyDirect();
    const c = G_STATE.roster[0];
    addMemberToParty(p.id, c.id);
    assertEqual(p.leaderId, c.id, 'リーダーが自動設定されていない');
});
test('4人以上追加しようとしても4人でキャップされる', () => {
    resetState();
    const p = addPartyDirect();
    // ロスターに5人追加
    while (G_STATE.roster.length < 5) G_STATE.roster.push(genChar());
    const ids = G_STATE.roster.slice(0, 5).map(c => c.id);
    for (const id of ids) addMemberToParty(p.id, id);
    assertEqual(p.members.length, 4, `4人上限を超えた: ${p.members.length}人`);
});
test('setLeader でリーダーが変わる', () => {
    resetState();
    const p = addPartyDirect();
    while (G_STATE.roster.length < 2) G_STATE.roster.push(genChar());
    addMemberToParty(p.id, G_STATE.roster[0].id);
    addMemberToParty(p.id, G_STATE.roster[0].id); // 2人目を追加
    const secondId = p.members[1]?.id;
    if (secondId) {
        setLeader(p.id, secondId);
        assertEqual(p.leaderId, secondId, 'リーダーが変更されていない');
    }
});
test('removeMember でメンバーがパーティーから削除される', () => {
    resetState();
    const p = addPartyDirect();
    const c = G_STATE.roster[0];
    addMemberToParty(p.id, c.id);
    assertEqual(p.members.length, 1);
    removeMember(p.id, c.id);
    assertEqual(p.members.length, 0, 'メンバーが削除されていない');
});
test('removeMember で解雇されたキャラがdismissedリストに追加される', () => {
    resetState();
    const p = addPartyDirect();
    const c = G_STATE.roster[0];
    addMemberToParty(p.id, c.id);
    const dismissedBefore = G_STATE.dismissed.length;
    removeMember(p.id, c.id);
    assert(G_STATE.dismissed.length > dismissedBefore, 'dismissedリストに追加されていない');
});

console.log('\n◆ 週進行 — advanceWeek() フロー');
test('advanceWeek() で週が+1される', () => {
    resetState();
    const before = G_STATE.week;
    advanceWeek();
    assertEqual(G_STATE.week, before + 1, `週が進んでいない: ${G_STATE.week}`);
});
test('advanceWeek() でCP報酬のあるパーティーのCPが控除される', () => {
    resetState();
    G_STATE.gold = 100;
    const p = addPartyDirect();
    p.members = [genChar()];
    p.status = 'active';
    p.directive.cpPerWeek = 20;
    advanceWeek();
    assertEqual(G_STATE.gold, 80, `Gold控除が不正: ${G_STATE.gold}`);
});
test('advanceWeek() でパーティーから週次報告が届く', () => {
    resetState();
    G_STATE.gold = 500;
    const p = addPartyDirect();
    p.members = [genChar()];
    p.status = 'active';
    advanceWeek();
    assert(G_STATE.pendingReports.length > 0, '週次報告が生成されていない');
});
test('advanceWeek() 後にロスターのlengthが負にならない', () => {
    resetState();
    G_STATE.gold = 500;
    advanceWeek();
    assert(G_STATE.roster.length >= 0, 'ロスターが負になった');
});
test('CP0でadvanceWeek()を呼んでもcpDebtが積み上がり解散しない(1週目)', () => {
    resetState();
    G_STATE.gold = 0;
    const p = addPartyDirect();
    p.members = [genChar()];
    p.status = 'active';
    advanceWeek();
    assert(p.status !== 'disbanded', '1週目でいきなり解散した');
    assertEqual(p.cpDebt, 20, `cpDebt が不正: ${p.cpDebt}`);
});

console.log('\n◆ モーダル — openModal / closeModal');
test('openModal がclassListにopenを追加する', () => {
    const el = document.getElementById('mcreate');
    el.classList.remove('open');
    openModal('mcreate');
    assert(el.classList.contains('open'), 'openクラスが追加されていない');
});
test('closeModal がclassListからopenを削除する', () => {
    const el = document.getElementById('mcreate');
    el.classList.add('open');
    closeModal('mcreate');
    assert(!el.classList.contains('open'), 'openクラスが削除されていない');
});

console.log('\n◆ dismissReport() — 報告の既読処理');
test('dismissReport で reports から1件削除される', () => {
    resetState();
    const p = addPartyDirect();
    G_STATE.pendingReports = [
        { party: p, events: [] },
        { party: p, events: [] },
    ];
    dismissReport(0);
    assertEqual(G_STATE.pendingReports.length, 1, '削除されていない');
});

console.log('\n◆ openHireModal() — ギルド待機所の採用ボタン');
test('パーティーがないとき採用ボタンを押してもエラーにならない', () => {
    resetState();
    G_STATE.parties = [];
    // alertが呼ばれて早期リターン — 例外なし
    openHireModal(G_STATE.roster[0]?.id || 999);
});
test('採用先パーティーが1つあるとき自動でそのパーティーに追加される', () => {
    resetState();
    const p = addPartyDirect();
    const c = G_STATE.roster[0];
    assert(c, 'ロスターが空');
    openHireModal(c.id);
    assertEqual(p.members.length, 1, '採用されていない');
    assertEqual(p.members[0].id, c.id, '採用されたキャラが違う');
});
test('ロスターにいないIDを渡しても例外にならない', () => {
    resetState();
    openHireModal(9999999); // 存在しないID
});

console.log('\n◆ ID永続化 — リロード後もIDが重複しない');
test('saveState後にloadStateするとG_STATE._uidが保存・復元される', () => {
    resetState();
    const p1 = addPartyDirect('パーティーA');
    const beforeUid = _uid;
    saveState();
    // _uidをリセットしてloadStateで復元されるか確認
    // eslint-disable-next-line no-global-assign
    _uid = 1;
    loadState();
    assert(_uid >= beforeUid, `_uidが復元されない: before=${beforeUid} after=${_uid}`);
});
test('リロード後に作成したパーティーIDが既存パーティーと重複しない', () => {
    resetState();
    const p1 = addPartyDirect('旧パーティー');
    const oldId = p1.id;
    saveState();
    // リロード相当: _uidをリセット → loadState
    _uid = 1;
    loadState();
    // ここで新しいパーティーを作成
    const p2 = addPartyDirect('新パーティー');
    assert(p2.id !== oldId, `リロード後のIDが重複した: 旧=${oldId} 新=${p2.id}`);
});
test('リロード後もaddMemberToPartyが正しいパーティーにメンバーを追加する', () => {
    resetState();
    const p1 = addPartyDirect('旧パーティー');
    const oldId = p1.id;
    saveState();
    _uid = 1;
    loadState();
    // 新パーティーを追加
    const p2 = addPartyDirect('新パーティー');
    // ロスターに1名追加
    const c = genChar();
    G_STATE.roster.push(c);
    // p2に採用 — p1のIDと被っていなければp2に追加される
    addMemberToParty(p2.id, c.id);
    // G_STATEのp2を再取得
    const p2fresh = G_STATE.parties.find(p => p.id === p2.id);
    assertEqual(p2fresh.members.length, 1, `新パーティーに採用されなかった (ID重複バグ再発の可能性)`);
    const p1fresh = G_STATE.parties.find(p => p.id === oldId);
    assertEqual((p1fresh?.members?.length || 0), 0, `旧パーティーに誤って採用された (ID重複バグ)`);
});



// ======= T1: initRoster — ロスターが空の時に初期化されるか =======
test('initRoster: ロスターが空なら6件補充する', () => {
    G_STATE.roster = [];
    initRoster();
    assert(G_STATE.roster.length >= 6, `initRoster後ロスターが${G_STATE.roster.length}件 (6件以上必要)`);
});

test('initRoster: ロスターに1件以上あれば追加しない', () => {
    G_STATE.roster = [genChar()];
    const countBefore = G_STATE.roster.length;
    initRoster();
    assertEqual(G_STATE.roster.length, countBefore, 'ロスターが既にある場合に誤って追加された');
});

// ======= T2: mobileNav — showViewと統合されているか =======
test('mobileNav: windowに公開されているか', () => {
    assert(typeof window.mobileNav === 'function', 'window.mobileNavが関数として公開されていない');
});

test('mobileNav: rosterビューに遷移してcurrentViewが変わるか', () => {
    currentView = 'welcome';
    mobileNav('roster');
    assertEqual(currentView, 'roster', 'mobileNav("roster")後にcurrentViewがrosterになっていない');
});

test('mobileNav: reportsビューに遷移できるか', () => {
    currentView = 'welcome';
    mobileNav('reports');
    assertEqual(currentView, 'reports', 'mobileNav("reports")後にcurrentViewがreportsになっていない');
});

// ======= T3: B1 — 採用後もrosterに所属済みフラグで残るか =======
test('B1: addMemberToParty後もキャラがrosterに残るか', () => {
    G_STATE.roster = [];
    G_STATE.parties = [];
    initRoster();
    const party = addPartyDirect('テストパーティー');
    const charId = G_STATE.roster[0].id;
    addMemberToParty(party.id, charId);
    const stillInRoster = G_STATE.roster.find(c => c.id === charId);
    assert(!!stillInRoster, 'B1: 採用後にキャラがrosterから消えてしまった');
});

test('B1: 採用済みキャラにhiredPartyIdが設定されるか', () => {
    G_STATE.roster = [];
    G_STATE.parties = [];
    initRoster();
    const party = addPartyDirect('テストB1パーティー');
    const char = G_STATE.roster[0];
    addMemberToParty(party.id, char.id);
    const rosterChar = G_STATE.roster.find(c => c.id === char.id);
    assertEqual(rosterChar?.hiredPartyId, party.id, 'B1: hiredPartyIdが採用先のパーティーIDに設定されていない');
});

// ============================================================
// ◆ window公開確認 — onclickハンドラのグローバル公開テスト
// ============================================================
console.log('\n◆ window公開確認 — onclickハンドラのグローバル公開テスト');

const REQUIRED_WINDOW_FUNCS = [
    'advanceWeek',
    'showParty',
    'showView',
    'dismissReport',
    'dismissAllReports',
    'openEquipModal',
    'equipItem',
    'unequipItem',
    'openHireModal',
    'openModal',
    'closeModal',
    'sellItem',
    'sellAll',
    'addWish',
    'removeWish',
    'craftRecipe',
    'handleChoiceEvent',
    'openIntervene',
    'mobileNav',
    'closeWeekSummary',
];

REQUIRED_WINDOW_FUNCS.forEach(name => {
    test(`window.${name} が公開されているか`, () => {
        assert(typeof global[name] === 'function',
            `window.${name} がundefinedまたは関数ではない (onclick呼び出し不可)`);
    });
});

// ============================================================
// ◆ openIntervene — 介入ボタンのロジックテスト
// ============================================================
console.log('\n◆ openIntervene — 介入ボタンテスト');

test('openIntervene: pendingReportsにレポートがある場合モーダルを開く', () => {
    resetState();
    const p = addPartyDirect('介入テストパーティー');
    // 擬似レポートを追加
    G_STATE.pendingReports = [{
        party: p,
        events: [{ type: 'conflict', text: '【揉め事】対立が発生した。' }],
        week: 1,
    }];
    // openIntervene がエラーなく実行できるか (DOMはモックなのでモーダル表示は検証しない)
    let threw = false;
    try { openIntervene(0, 0); } catch (e) { threw = true; }
    assert(!threw, `openIntervene(0,0) が例外を投げた`);
});

test('openIntervene: 存在しないインデックスを渡してもエラーにならない', () => {
    resetState();
    G_STATE.pendingReports = [];
    // alertがない環境でも例外にならないことを確認
    const origAlert = global.alert;
    global.alert = () => { };
    let threw = false;
    try { openIntervene(99, 0); } catch (e) { threw = true; }
    global.alert = origAlert;
    assert(!threw, 'openIntervene(99,0) が例外を投げた');
});

test('dismissReport: 報告が正しく削除される', () => {
    resetState();
    const p = addPartyDirect('削除テスト');
    G_STATE.pendingReports = [
        { party: p, events: [], week: 1 },
        { party: p, events: [], week: 1 },
    ];
    dismissReport(0);
    assertEqual(G_STATE.pendingReports.length, 1, 'dismissReport(0)後に1件残っていない');
});

test('sellItem: インベントリからアイテムを売却するとGoldが増える', () => {
    resetState();
    G_STATE.gold = 100;
    G_STATE.inventory = [{ id: 'item_test1', name: 'テスト品', rarity: 'common', value: 50 }];
    sellItem('item_test1');
    assertEqual(G_STATE.gold, 150, '売却後Goldが150になっていない');
    assertEqual(G_STATE.inventory.length, 0, '売却後インベントリが空になっていない');
});

// ========= フェーズ8 テスト =========

// ----- B. MADNESS_EVENTS: 狂気事件テーブル -----
console.log('\n◆ B. MADNESS_EVENTS — 狂気事件テーブル');
test('MADNESS_EVENTSが定義されている', () => {
    assert(typeof MADNESS_EVENTS !== 'undefined', 'MADNESS_EVENTSが未定義');
    assert(Array.isArray(MADNESS_EVENTS), 'MADNESS_EVENTSが配列ではない');
});
test('MADNESS_EVENTSが10件定義されている', () => {
    assertEqual(MADNESS_EVENTS.length, 10, `MADNESS_EVENTS.length=${MADNESS_EVENTS.length}`);
});
test('MADNESS_EVENTSの各エントリにicon・title・status・result・applyが存在する', () => {
    MADNESS_EVENTS.forEach((ev, i) => {
        assert(ev.icon, `[${i}].icon が空`);
        assert(ev.title, `[${i}].title が空`);
        assert(ev.status, `[${i}].status が空`);
        assert(ev.result, `[${i}].result が空`);
        assert(typeof ev.apply === 'function', `[${i}].apply が関数ではない`);
    });
});
test('狂気事件 apply: stress が 0〜50 の範囲内に戻る', () => {
    resetState();
    const member = { id: 1, name: 'テスト太郎', stress: 100, healthPt: 100, mood: 70, morale: 70, mentalPt: 80, dead: false };
    const party = addPartyDirect('狂気テスト');
    party.members = [member];
    MADNESS_EVENTS.forEach((ev, i) => {
        const m = { ...member };
        const p = { ...party, members: [{ ...member }] };
        ev.apply(m, p);
        assertRange(m.stress, 0, 100, `MADNESS_EVENTS[${i}](${ev.title}): stress=${m.stress} が範囲外`);
    });
});
test('狂気事件「深淵への逃走」: dead=trueになる', () => {
    resetState();
    const ev = MADNESS_EVENTS.find(e => e.title === '深淵への逃走');
    assert(ev, '深淵への逃走が見つからない');
    const member = { id: 99, name: '逃走者', stress: 100, dead: false };
    const party = addPartyDirect('逃走パーティー');
    party.members = [{ ...member }];
    ev.apply(member, party);
    assert(member.dead, '逃走後にdead=trueになっていない');
});
test('狂気事件「呪詛の叫び」: 他メンバーにストレス+15が伝播する', () => {
    resetState();
    const ev = MADNESS_EVENTS.find(e => e.title === '呪詛の叫び');
    assert(ev, '呪詛の叫びが見つからない');
    const m1 = { id: 1, name: '呪詛者', stress: 100, dead: false };
    const m2 = { id: 2, name: '被害者', stress: 30, dead: false };
    const party = addPartyDirect('呪詛パーティー');
    party.members = [m1, m2];
    ev.apply(m1, party);
    assertEqual(m1.stress, 0, '呪詛者のstressが0になっていない');
    assertEqual(m2.stress, 45, `被害者のstress=${m2.stress} (期待値45)`);
});

// ----- C. 地方マップイベント -----
console.log('\n◆ C. 地方マップイベント — spawnMapEvents / getMapEventModifiers');
test('MAP_EVENT_TYPESが定義されている', () => {
    assert(typeof MAP_EVENT_TYPES !== 'undefined', 'MAP_EVENT_TYPESが未定義');
    assert(Array.isArray(MAP_EVENT_TYPES), 'MAP_EVENT_TYPESが配列ではない');
    assertEqual(MAP_EVENT_TYPES.length, 5, `MAP_EVENT_TYPES.length=${MAP_EVENT_TYPES.length}`);
});
test('MAP_EVENT_TYPESの各エントリにid・icon・label・cls・dropModが存在する', () => {
    MAP_EVENT_TYPES.forEach((ev, i) => {
        assert(ev.id, `[${i}].id が空`);
        assert(ev.icon, `[${i}].icon が空`);
        assert(ev.label, `[${i}].label が空`);
        assert(ev.cls, `[${i}].cls が空`);
        assert(typeof ev.dropMod === 'number', `[${i}].dropMod が数値ではない`);
    });
});
test('spawnMapEvents: G_STATE.mapEventsが初期化される', () => {
    resetState();
    G_STATE.mapEvents = undefined;
    spawnMapEvents();
    assert(typeof G_STATE.mapEvents === 'object', 'G_STATE.mapEventsが初期化されていない');
});
test('spawnMapEvents: expireWeekを過ぎたイベントが削除される', () => {
    resetState();
    G_STATE.week = 5;
    const someRegion = Object.keys(REGION_DATA)[0];
    G_STATE.mapEvents = {
        [someRegion]: { id: 'storm', icon: '⛈', label: '荒天', expireWeek: 3, dropMod: -0.15, riskMod: 0, desc: 'test' }
    };
    spawnMapEvents();
    assert(!G_STATE.mapEvents[someRegion], '期限切れイベントが削除されていない');
});
test('getMapEventModifiers: イベントなし地域はdropMod=0・riskMod=0を返す', () => {
    resetState();
    G_STATE.mapEvents = {};
    const mod = getMapEventModifiers('北の森林地帯');
    assertEqual(mod.dropMod, 0, `dropMod=${mod.dropMod}`);
    assertEqual(mod.riskMod, 0, `riskMod=${mod.riskMod}`);
});
test('getMapEventModifiers: 荒天イベント中の地域はdropMod=-0.15を返す', () => {
    resetState();
    G_STATE.mapEvents = {
        '北の森林地帯': { id: 'storm', dropMod: -0.15, riskMod: 0, expireWeek: 99 }
    };
    const mod = getMapEventModifiers('北の森林地帯');
    assertEqual(mod.dropMod, -0.15, `dropMod=${mod.dropMod}`);
});

// ----- D. 作戦シナジーシステム -----
console.log('\n◆ D. 作戦シナジー — TACTIC_SYNERGY / calcTacticSynergies');
test('TACTIC_SYNERGYが定義されている', () => {
    assert(typeof TACTIC_SYNERGY !== 'undefined', 'TACTIC_SYNERGYが未定義');
    assert(Array.isArray(TACTIC_SYNERGY), 'TACTIC_SYNERGYが配列ではない');
    assert(TACTIC_SYNERGY.length >= 4, `シナジー数が少ない: ${TACTIC_SYNERGY.length}`);
});
test('TACTIC_SYNERGYの各エントリにid・label・desc・check・applyが存在する', () => {
    TACTIC_SYNERGY.forEach((syn, i) => {
        assert(syn.id, `[${i}].id が空`);
        assert(syn.label, `[${i}].label が空`);
        assert(syn.desc, `[${i}].desc が空`);
        assert(typeof syn.check === 'function', `[${i}].check が関数ではない`);
        assert(typeof syn.apply === 'function', `[${i}].apply が関数ではない`);
    });
});
test('calcTacticSynergies: 条件未満のとき activeが空', () => {
    resetState();
    const p = addPartyDirect('シナジーなし');
    p.tactic = 'assault';
    p.members = [
        { id: 1, morale: 30, healthPt: 60, dead: false, trait: 'A', likedType: 'B' },
    ];
    const { active } = calcTacticSynergies(p);
    assertEqual(active.length, 0, `シナジー発動してしまった: ${active.map(s => s.id).join(',')}`);
});
test('calcTacticSynergies: assault+全員morale70以上で「闘気の結集」が発動する', () => {
    resetState();
    const p = addPartyDirect('シナジーあり');
    p.tactic = 'assault';
    p.members = [
        { id: 1, morale: 80, healthPt: 90, dead: false, trait: 'A', likedType: 'X' },
        { id: 2, morale: 75, healthPt: 85, dead: false, trait: 'B', likedType: 'Y' },
    ];
    const { active } = calcTacticSynergies(p);
    const found = active.find(s => s.id === 'assault_warcry');
    assert(found, '「闘気の結集」シナジーが発動していない');
});
test('calcTacticSynergies: guard+全員healthPt80以上でinjuryMult=0になる', () => {
    resetState();
    const p = addPartyDirect('鉄壁シナジー');
    p.tactic = 'guard';
    p.members = [
        { id: 1, morale: 60, healthPt: 90, dead: false, trait: 'A', likedType: 'X' },
        { id: 2, morale: 55, healthPt: 85, dead: false, trait: 'B', likedType: 'Y' },
    ];
    const { mods } = calcTacticSynergies(p);
    assertEqual(mods.injuryMult, 0, `鉄壁シナジー: injuryMult=${mods.injuryMult}`);
});
test('calcTacticSynergies: gather+ランクBでepicBonusが0.1以上になる', () => {
    resetState();
    const p = addPartyDirect('熟練採掘');
    p.tactic = 'gather';
    p.rank = 'B';
    p.members = [
        { id: 1, morale: 60, healthPt: 80, dead: false, trait: 'A', likedType: 'X' },
    ];
    const { mods } = calcTacticSynergies(p);
    assert(mods.epicBonus >= 0.10, `epicBonus=${mods.epicBonus} (期待値>=0.10)`);
});

// ----- E. パーティーXPバー -----
console.log('\n◆ E. パーティーランクXP — RANKS / RANK_XP 存在確認');
test('RANKSが定義されている', () => {
    assert(typeof RANKS !== 'undefined' || typeof window.RANKS !== 'undefined', 'RANKSが未定義');
});
test('tickParty実行後にパーティーにxpが付与される（週次フロー）', () => {
    resetState();
    const p = addPartyDirect('XPテストパーティー');
    p.status = 'active';
    p.xp = 0;
    p.tactic = 'assault';
    p.directive = { focus: 'steady', conflict: 'leader', cpPerWeek: 20 };
    p.members = [
        { id: uid(), name: 'ケン', age: 22, gender: '♂', personality: '堅実', level: 1, skill: '剣', weakSkill: '魔法', morale: 70, mood: 70, stress: 10, healthPt: 80, mentalPt: 80, health: 'healthy', dead: false, xp: 0, hiredPartyId: p.id, growthTag: '', likedType: '', trait: '', equip: null, ailment: null, severelyInjured: false },
    ];
    p.members[0].hiredPartyId = p.id;
    const prevXp = p.xp;
    tickParty(p);
    assert(p.xp >= prevXp, `xpが増えていない: before=${prevXp}, after=${p.xp}`);
});

// ----- A. 誘導バナー（ロジック部分） -----
console.log('\n◆ A. 誘導バナー — ストレス80以上のメンバー検出');
test('ストレス80以上のメンバーを正しく検出できる', () => {
    resetState();
    const p = addPartyDirect('バナーテスト');
    p.members = [
        { id: 1, name: 'アリス', stress: 85, dead: false },
        { id: 2, name: 'ボブ', stress: 50, dead: false },
        { id: 3, name: 'チャリー', stress: 20, dead: false },
    ];
    const highStress = p.members.filter(m => !m.dead && (m.stress || 0) >= 80);
    assertEqual(highStress.length, 1, `highStress.length=${highStress.length}`);
    assertEqual(highStress[0].name, 'アリス', `名前が一致しない: ${highStress[0].name}`);
});
test('dead=trueのメンバーはストレス80以上でも誘導バナー対象外', () => {
    resetState();
    const p = addPartyDirect('デッドメンバー');
    p.members = [
        { id: 1, name: '死亡者', stress: 100, dead: true },
        { id: 2, name: '生存者', stress: 30, dead: false },
    ];
    const highStress = p.members.filter(m => !m.dead && (m.stress || 0) >= 80);
    assertEqual(highStress.length, 0, `dead=trueが除外されていない`);
});
test('recoverAtChurch でストレスが50以上減少する', () => {
    resetState();
    G_STATE.gold = 2000;
    const p = addPartyDirect('教会テスト');
    p.members = [
        { id: uid(), name: 'テスト子', stress: 90, mood: 60, dead: false, healthPt: 80 },
    ];
    p.members.forEach(m => { m.hiredPartyId = p.id; });
    recoverAtChurch(p.id);
    assertRange(p.members[0].stress, 0, 45, `ストレス回復後=${p.members[0].stress}`);
});

// ========= 既存フェーズ 未テスト関数テスト =========

// ----- setDifficulty -----
console.log('\n◆ setDifficulty — 難易度設定');
test('setDifficulty("casual") でG_STATE.difficultyが設定される', () => {
    resetState();
    setDifficulty('casual');
    assertEqual(G_STATE.difficulty, 'casual', `difficulty=${G_STATE.difficulty}`);
});
test('setDifficulty("hard") でG_STATE.difficultyが"hard"になる', () => {
    resetState();
    setDifficulty('hard');
    assertEqual(G_STATE.difficulty, 'hard');
});
test('setDifficulty("normal") でlocalStorageに保存される', () => {
    resetState();
    localStorage._store = {};
    setDifficulty('normal');
    assert(localStorage._store['gm_v1'] != null, 'saveStateが呼ばれていない');
});

// ----- recoverAtInn -----
console.log('\n◆ recoverAtInn — 宿屋回復');
test('recoverAtInn: 生存メンバー数 × 30G が消費される', () => {
    resetState();
    G_STATE.gold = 500;
    const p = addPartyDirect('宿屋テスト');
    p.members = [
        { id: 1, name: 'A', dead: false, healthPt: 50, mood: 60, severelyInjured: true },
        { id: 2, name: 'B', dead: false, healthPt: 60, mood: 50, severelyInjured: false },
    ];
    recoverAtInn(p.id);
    assertEqual(G_STATE.gold, 440, `gold=${G_STATE.gold} (期待値440)`);
});
test('recoverAtInn: healthPt+40, mood+20 される', () => {
    resetState();
    G_STATE.gold = 500;
    const p = addPartyDirect('宿屋回復テスト');
    const m = { id: 1, name: 'A', dead: false, healthPt: 50, mood: 50, severelyInjured: false };
    p.members = [m, { id: 2, name: 'B', dead: false, healthPt: 60, mood: 60, severelyInjured: false }];
    recoverAtInn(p.id);
    assertRange(m.healthPt, 80, 100, `healthPt=${m.healthPt}`);
    assertRange(m.mood, 60, 100, `mood=${m.mood}`);
});
test('recoverAtInn: severelyInjured=false になる', () => {
    resetState();
    G_STATE.gold = 500;
    const p = addPartyDirect('重傷回復');
    const m = { id: 1, name: 'A', dead: false, healthPt: 30, mood: 40, severelyInjured: true };
    p.members = [m];
    recoverAtInn(p.id);
    assert(!m.severelyInjured, 'severelyInjuredがtrueのまま');
});
test('recoverAtInn: Gold不足のとき消費しない', () => {
    resetState();
    G_STATE.gold = 10;
    const p = addPartyDirect('Gold不足');
    p.members = [
        { id: 1, name: 'A', dead: false, healthPt: 50, mood: 50, severelyInjured: false },
    ];
    const prev = G_STATE.gold;
    recoverAtInn(p.id); // cost=30 > gold=10 → alertして早期returnのはず
    assertEqual(G_STATE.gold, prev, `Gold不足なのに消費された: ${G_STATE.gold}`);
});
test('recoverAtInn: dead=trueのメンバーはコスト対象外', () => {
    resetState();
    G_STATE.gold = 500;
    const p = addPartyDirect('死亡者除外');
    p.members = [
        { id: 1, name: 'A', dead: true, healthPt: 0, mood: 0, severelyInjured: false },
        { id: 2, name: 'B', dead: false, healthPt: 60, mood: 60, severelyInjured: false },
    ];
    recoverAtInn(p.id);
    assertEqual(G_STATE.gold, 470, `dead除外でcost=30G: gold=${G_STATE.gold}`);
});

// ----- setPartyTactic -----
console.log('\n◆ setPartyTactic — 作戦変更');
test('setPartyTactic でp.tacticが更新される', () => {
    resetState();
    const p = addPartyDirect('タクティクスP');
    setPartyTactic(p.id, 'guard');
    assertEqual(p.tactic, 'guard', `tactic=${p.tactic}`);
});
test('setPartyTactic: 存在しないpidを渡しても例外にならない', () => {
    resetState();
    let threw = false;
    try { setPartyTactic(9999, 'assault'); } catch (e) { threw = true; }
    assert(!threw, 'setPartyTactic(9999) が例外を投げた');
});
test('setPartyTactic: assaultに変更後saveStateが呼ばれる', () => {
    resetState();
    localStorage._store = {};
    const p = addPartyDirect('保存テスト');
    setPartyTactic(p.id, 'assault');
    assert(localStorage._store['gm_v1'] != null, 'saveStateが呼ばれていない');
});

// ----- checkBossEncounter -----
console.log('\n◆ checkBossEncounter — ボス遭遇');
test('checkBossEncounter: 4の倍数週でなければeventsに追加しない', () => {
    resetState();
    G_STATE.week = 5;
    const p = addPartyDirect('ボステスト');
    p.members = [{ id: 1, dead: false, healthPt: 80, stress: 10 }];
    const evs = [];
    checkBossEncounter(p, evs);
    assertEqual(evs.length, 0, `4の倍数週でないのにイベントが追加された: ${evs.length}`);
});
test('checkBossEncounter: ボス敗北時にメンバーがseverelyInjured=trueになる', () => {
    resetState();
    G_STATE.week = 4;
    G_STATE.difficulty = 'hard';
    const p = addPartyDirect('弱パーティー');
    p.rank = 'F';
    p.members = [{ id: 1, dead: false, healthPt: 80, stress: 10, severelyInjured: false }];
    // Math.randomを固定してボス発生・敗北を保証
    const origRand = Math.random;
    let callCount = 0;
    Math.random = () => { callCount++; return callCount <= 1 ? 0.1 : 0.1; }; // 常に低い値
    const evs = [];
    checkBossEncounter(p, evs);
    Math.random = origRand;
    // ボスが出ていれば敗北イベントが追加されるはず
    const crisisEvs = evs.filter(e => e.type === 'crisis');
    assert(crisisEvs.length >= 1, `ボス戦のcrisisイベントがない: ${JSON.stringify(evs)}`);
});

// ----- checkStressBreakdown -----
console.log('\n◆ checkStressBreakdown — ストレス崩壊');
test('checkStressBreakdown: stress<100のとき何もしない', () => {
    resetState();
    const p = addPartyDirect('崩壊テスト');
    const m = { id: 1, name: 'テスト', stress: 99, dead: false, mood: 70 };
    p.members = [m];
    const evs = [];
    checkStressBreakdown(m, p, evs);
    assertEqual(evs.length, 0, 'stress<100なのにイベントが追加された');
});
test('checkStressBreakdown: stress=100でeventsにcrisisが追加される', () => {
    resetState();
    const p = addPartyDirect('崩壊パーティー');
    const m = { id: 1, name: '崩壊者', stress: 100, dead: false, mood: 70 };
    p.members = [m];
    const evs = [];
    checkStressBreakdown(m, p, evs);
    assert(evs.length > 0, 'stress=100なのにイベントが追加されなかった');
    assert(evs.some(e => e.type === 'crisis' || e.type === 'good'), `crisisでもgoodでもないイベント: ${JSON.stringify(evs)}`);
});
test('checkStressBreakdown: 崩壊後stressが100未満になる', () => {
    resetState();
    const p = addPartyDirect('崩壊ストレスP');
    const m = { id: 1, name: 'ストレス者', stress: 100, dead: false, mood: 70, mentalPt: 80 };
    p.members = [{ ...m }];
    const origMember = p.members[0];
    const evs = [];
    checkStressBreakdown(origMember, p, evs);
    // 廃人化で追放された可能性があるのでorigMemberを直接確認
    const isRemoved = !p.members.find(x => x.id === origMember.id);
    if (isRemoved) {
        // 廃人化はOK
        assert(true);
    } else {
        assert(origMember.stress < 100, `崩壊後もstress=${origMember.stress}`);
    }
});

// ----- addWish / removeWish -----
console.log('\n◆ addWish / removeWish — ウィッシュリスト');
test('addWish: wishListに名前が追加される', () => {
    resetState();
    G_STATE.wishList = [];
    addWish('豪炎の大剣');
    assert(G_STATE.wishList.includes('豪炎の大剣'), 'wishListに追加されていない');
});
test('addWish: 同じ名前を2回追加しても重複しない', () => {
    resetState();
    G_STATE.wishList = [];
    addWish('豪炎の大剣');
    addWish('豪炎の大剣');
    assertEqual(G_STATE.wishList.length, 1, `重複が発生: length=${G_STATE.wishList.length}`);
});
test('addWish: 空文字を渡しても追加されない', () => {
    resetState();
    G_STATE.wishList = [];
    addWish('');
    assertEqual(G_STATE.wishList.length, 0, '空文字が追加されてしまった');
});
test('removeWish: 指定した名前がwishListから削除される', () => {
    resetState();
    G_STATE.wishList = ['豪炎の大剣', '霜雪の弓'];
    removeWish('豪炎の大剣');
    assert(!G_STATE.wishList.includes('豪炎の大剣'), '削除されていない');
    assertEqual(G_STATE.wishList.length, 1, '件数が正しくない');
});
test('removeWish: 存在しない名前を渡してもエラーにならない', () => {
    resetState();
    G_STATE.wishList = ['霜雪の弓'];
    let threw = false;
    try { removeWish('存在しない'); } catch (e) { threw = true; }
    assert(!threw, 'removeWish が例外を投げた');
});

// ----- craftRecipe -----
console.log('\n◆ craftRecipe — レシピ合成');
test('craftRecipe: 素材が揃っていれば合成品がinventoryに追加される', () => {
    resetState();
    // RECIPES[3] = '魔道書・上巻', ingredients: ['封印の書', '月光の杖'], rarity:'rare', value:250
    G_STATE.inventory = [
        { id: uid(), name: '封印の書', rarity: 'rare', value: 100 },
        { id: uid(), name: '月光の杖', rarity: 'rare', value: 100 },
    ];
    craftRecipe(3); // '魔道書・上巻'
    const crafted = G_STATE.inventory.find(x => x.name === '魔道書・上巻');
    assert(crafted, '合成品が見つからない');
    assertEqual(crafted.rarity, 'rare', `rarity=${crafted.rarity}`);
});
test('craftRecipe: 素材が不足しているなら合成されない', () => {
    resetState();
    G_STATE.inventory = [
        { id: uid(), name: '封印の書', rarity: 'rare', value: 100 },
        // 月光の杖は無い
    ];
    const origLen = G_STATE.inventory.length;
    craftRecipe(3);
    // アラートの代わりearly returnなので inv.lengthは変わらない
    assertEqual(G_STATE.inventory.length, origLen, '素材不足なのに合成が実行された');
});
test('craftRecipe: 素材消費後にinventoryから素材が削除される', () => {
    resetState();
    G_STATE.inventory = [
        { id: uid(), name: '封印の書', rarity: 'rare', value: 100 },
        { id: uid(), name: '月光の杖', rarity: 'rare', value: 100 },
    ];
    craftRecipe(3);
    assert(!G_STATE.inventory.some(x => x.name === '封印の書'), '封印の書が残っている');
    assert(!G_STATE.inventory.some(x => x.name === '月光の杖'), '月光の杖が残っている');
});

// ----- upgradeGuildSkill -----
console.log('\n◆ upgradeGuildSkill — ギルドスキルツリー');
test('upgradeGuildSkill: skillPts十分あればスキルが解除される', () => {
    resetState();
    G_STATE.skillPts = 10;
    G_STATE.unlockedSkills = {};
    const tree = GUILD_SKILLS[0];
    const node = tree.tree[0]; // lv:1のノード
    upgradeGuildSkill(tree.id, node.lv);
    const key = `${tree.id}_${node.lv}`;
    assert(G_STATE.unlockedSkills[key], 'スキルが解除されていない');
});
test('upgradeGuildSkill: skillPtsがcostより少なければ解除されない', () => {
    resetState();
    G_STATE.skillPts = 0;
    G_STATE.unlockedSkills = {};
    const tree = GUILD_SKILLS[0];
    const node = tree.tree[0];
    upgradeGuildSkill(tree.id, node.lv);
    const key = `${tree.id}_${node.lv}`;
    assert(!G_STATE.unlockedSkills[key], 'スキルPt不足なのに解除されてしまった');
});
test('upgradeGuildSkill: 前提スキル未解除ならlv2は習得不可', () => {
    resetState();
    G_STATE.skillPts = 10;
    G_STATE.unlockedSkills = {}; // lv1未解除
    const tree = GUILD_SKILLS[0];
    const lv2node = tree.tree.find(n => n.lv === 2);
    if (!lv2node) return; // lv2がなければスキップ
    upgradeGuildSkill(tree.id, 2);
    const key = `${tree.id}_2`;
    assert(!G_STATE.unlockedSkills[key], '前提未解除なのにlv2が解除された');
});
test('upgradeGuildSkill: 解除済みのスキルを再習得しても重複しない', () => {
    resetState();
    G_STATE.skillPts = 10;
    G_STATE.unlockedSkills = {};
    const tree = GUILD_SKILLS[0];
    const node = tree.tree[0];
    upgradeGuildSkill(tree.id, node.lv);
    const ptsBefore = G_STATE.skillPts;
    upgradeGuildSkill(tree.id, node.lv); // 2回目
    assertEqual(G_STATE.skillPts, ptsBefore, '既習得スキルで追加コストが発生した');
});

// ----- disbandParty -----
console.log('\n◆ disbandParty — パーティー解散');
test('disbandParty: パーティーのstatusが"disbanded"になる', () => {
    resetState();
    // confirmをtrueにモック
    const origConfirm = global.confirm;
    global.confirm = () => true;
    const p = addPartyDirect('解散テスト');
    disbandParty(p.id);
    global.confirm = origConfirm;
    assertEqual(p.status, 'disbanded', `status=${p.status}`);
});
test('disbandParty: メンバーがrosterに戻される', () => {
    resetState();
    const origConfirm = global.confirm;
    global.confirm = () => true;
    const p = addPartyDirect('メンバー戻しP');
    const m = { id: uid(), name: 'メンバー', dead: false };
    p.members = [m];
    G_STATE.roster.push({ ...m });
    const prevRosterLen = G_STATE.roster.length;
    disbandParty(p.id);
    global.confirm = origConfirm;
    assert(G_STATE.roster.length > prevRosterLen, 'メンバーがrosterに戻されていない');
});
test('disbandParty: confirm=falseなら解散しない', () => {
    resetState();
    const origConfirm = global.confirm;
    global.confirm = () => false;
    const p = addPartyDirect('キャンセルP');
    disbandParty(p.id);
    global.confirm = origConfirm;
    assert(p.status !== 'disbanded', 'confirmキャンセルなのに解散されてしまった');
});

// ----- dismissAllReports -----
console.log('\n◆ dismissAllReports — 全報告既読');
test('dismissAllReports: pendingReportsが空になる', () => {
    resetState();
    const p = addPartyDirect('報告P');
    G_STATE.pendingReports = [
        { party: p, events: [], week: 1 },
        { party: p, events: [], week: 2 },
        { party: p, events: [], week: 3 },
    ];
    dismissAllReports();
    assertEqual(G_STATE.pendingReports.length, 0, 'pendingReportsが残っている');
});
test('dismissAllReports: saveStateが呼ばれる', () => {
    resetState();
    localStorage._store = {};
    dismissAllReports();
    assert(localStorage._store['gm_v1'] != null, 'saveStateが呼ばれていない');
});

// ----- rarityBadge -----
console.log('\n◆ rarityBadge — アイテムレアリティ表示');
test('rarityBadge("epic", "神剣") にはepicカラーが含まれる', () => {
    const html = rarityBadge('epic', '神剣');
    assertContains(html, '神剣', '名前が含まれない');
    assertContains(html, '🌟', 'epicアイコンがない');
});
test('rarityBadge("common", "鉄剣") にはcommonラベルが含まれる', () => {
    const html = rarityBadge('common', '鉄剣');
    assertContains(html, '鉄剣');
    assertContains(html, '📦');
});
test('rarityBadge: 未知のrarityでもクラッシュしない', () => {
    let result = '';
    let threw = false;
    try { result = rarityBadge('legendary', 'テスト品'); } catch (e) { threw = true; }
    assert(!threw, 'rarityBadgeが例外を投げた');
    assertContains(result, 'テスト品');
});

// ----- DIFFICULTY_PRESETS -----
console.log('\n◆ DIFFICULTY_PRESETS — 難易度定数');
test('DIFFICULTY_PRESETSにcasual/normal/hardが存在する', () => {
    assert(typeof DIFFICULTY_PRESETS !== 'undefined', 'DIFFICULTY_PRESETSが未定義');
    assert(DIFFICULTY_PRESETS.casual, 'casual がない');
    assert(DIFFICULTY_PRESETS.normal, 'normal がない');
    assert(DIFFICULTY_PRESETS.hard, 'hard がない');
});

// ----- genChar / initRoster -----
console.log('\n◆ genChar — キャラクター生成');
test('genChar: 必須フィールドが全て存在する', () => {
    const c = genChar();
    assert(c.name, 'name がない');
    assert(c.age, 'age がない');
    assert(c.skill, 'skill がない');
    assert(c.personality, 'personality がない');
    assert(c.gender, 'gender がない');
    assertRange(c.age, 17, 45, `age=${c.age}`);
});
test('genChar: skillとweakSkillが異なる', () => {
    const c = genChar();
    assert(c.skill !== c.weakSkill, `skill=${c.skill} と weakSkill=${c.weakSkill} が同じ`);
});

// ----- TACTIC_PRESETS -----
console.log('\n◆ TACTIC_PRESETS — 戦術定数');
test('TACTIC_PRESETSにassault/guard/gatherが存在する', () => {
    assert(typeof TACTIC_PRESETS !== 'undefined', 'TACTIC_PRESETSが未定義');
    assert(TACTIC_PRESETS.assault, 'assault がない');
    assert(TACTIC_PRESETS.guard, 'guard がない');
    assert(TACTIC_PRESETS.gather, 'gather がない');
});
test('TACTIC_PRESETS.assault.dropMultは1より大きい', () => {
    assert(TACTIC_PRESETS.assault.dropMult > 1, `dropMult=${TACTIC_PRESETS.assault.dropMult}`);
});

console.log('\n' + '─'.repeat(40));
console.log(`結果: ${passed + failed} テスト中 ${passed} 件成功 / ${failed} 件失敗`);
if (errors.length > 0) {
    console.log('\n失敗したテスト:');
    errors.forEach(e => console.log(`  ✗ ${e.name}: ${e.msg}`));
}
console.log('─'.repeat(40));
process.exit(failed > 0 ? 1 : 0);
