#!/usr/bin/env node
/**
 * guild_master.html のゲームロジックテストスイート
 * 実行方法: node tests/guild_master_logic.test.js
 */
'use strict';

// ========= Node.js 用モック =========
global.localStorage = {
    _store: {},
    getItem(k) { return this._store[k] ?? null; },
    setItem(k, v) { this._store[k] = v; },
    removeItem(k) { delete this._store[k]; },
};
const mockElem = () => ({
    textContent: '', innerHTML: '', classList: { add() { }, remove() { } },
    style: {}, prepend() { }, lastChild: null,
    children: { length: 60 },
    appendChild() { }, remove() { },
});
global.document = {
    getElementById() { return mockElem(); },
    createElement() { return mockElem(); },
};
global.alert = () => { };
global.confirm = () => true;
global.prompt = () => '1';

// ========= ロジック読み込み =========
const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(
    path.join(__dirname, '..', 'guild_master.html'), 'utf8'
);
// <script>タグの内容を抽出
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) { console.error('script tag not found'); process.exit(1); }

// ロジックを実行（グローバルに展開）
const vm = require('vm');
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

function assert(condition, msg) {
    if (!condition) throw new Error(msg || 'assertion failed');
}

function assertEqual(a, b, msg) {
    if (a !== b) throw new Error(msg || `expected ${b}, got ${a}`);
}

function assertRange(v, min, max, msg) {
    if (v < min || v > max) throw new Error(msg || `${v} は [${min}, ${max}] の範囲外`);
}

function assertArray(v, msg) {
    if (!Array.isArray(v)) throw new Error(msg || `${typeof v} は配列ではない`);
}

function assertType(v, t, msg) {
    if (typeof v !== t) throw new Error(msg || `${typeof v} は ${t} ではない`);
}

// ========= テストケース =========

console.log('\n◆ genChar() — キャラクター生成');
test('必要フィールドが全て存在する', () => {
    const c = genChar();
    const required = ['id', 'name', 'gender', 'age', 'personality', 'quirk', 'health', 'morale', 'skill', 'weakSkill', 'ailment', 'illness', 'illnessDaysLeft', 'romanceStyle', 'romanceGender', 'romanceStatus', 'dead'];
    for (const k of required) {
        assert(k in c, `フィールド "${k}" が存在しない`);
    }
});
test('年齢が 17〜45 の範囲内', () => {
    for (let i = 0; i < 50; i++) {
        const c = genChar();
        assertRange(c.age, 17, 45, `年齢 ${c.age} が範囲外`);
    }
});
test('士気が 0〜100 の範囲内', () => {
    for (let i = 0; i < 20; i++) {
        const c = genChar();
        assertRange(c.morale, 0, 100, `士気 ${c.morale} が範囲外`);
    }
});
test('gender は ♀ か ♂ のどちらか', () => {
    for (let i = 0; i < 20; i++) {
        const c = genChar();
        assert(c.gender === '♀' || c.gender === '♂', `不正な gender: ${c.gender}`);
    }
});
test('初期health は healthy', () => {
    const c = genChar();
    assertEqual(c.health, 'healthy');
});
test('skill と weakSkill は異なる', () => {
    for (let i = 0; i < 50; i++) {
        const c = genChar();
        assert(c.skill !== c.weakSkill, `skill と weakSkill が同じ: ${c.skill}`);
    }
});
test('id は毎回異なる', () => {
    const ids = new Set();
    for (let i = 0; i < 30; i++) ids.add(genChar().id);
    assertEqual(ids.size, 30, 'IDが重複している');
});

console.log('\n◆ calcConflictChance() — 揉め事確率計算');
test('単独メンバーの基本確率は 0.1', () => {
    const c = genChar();
    const chance = calcConflictChance([c]);
    assertEqual(chance, 0.1);
});
test('上限 0.7 を超えない', () => {
    const members = [];
    for (let i = 0; i < 4; i++) {
        const c = genChar();
        // 全員が互いに嫌いな性格になるよう設定
        c.personality = 'A'; c.dislikedType = 'A';
        members.push(c);
    }
    const chance = calcConflictChance(members);
    assertRange(chance, 0, 0.7, `確率 ${chance} が 0.7 を超えた`);
});
test('相性の悪いメンバーがいると確率が上昇する', () => {
    const a = genChar(); a.personality = 'UNIQUE_TYPE';
    const b = genChar(); b.dislikedType = 'UNIQUE_TYPE';
    const base = calcConflictChance([a]);
    const high = calcConflictChance([a, b]);
    assert(high > base, `相性悪メンバー追加で確率が上がらなかった: ${base} → ${high}`);
});

console.log('\n◆ resolveConflict() — 揉め事解決');
const RULES = ['rest', 'leader', 'vote', 'ignore'];
for (const rule of RULES) {
    test(`rule="${rule}" で文字列を返す`, () => {
        const a = genChar(), b = genChar();
        const result = resolveConflict(rule, a, b);
        assertType(result, 'string', '返り値が文字列でない');
        assert(result.length > 0, '空文字列が返った');
    });
}

console.log('\n◆ generateWeekEvents() — 週次イベント生成');
test('配列を返す', () => {
    const p = { region: '北の森', directive: { focus: 'steady', conflict: 'leader' } };
    const mem = genChar();
    p.members = [mem];
    assertArray(generateWeekEvents(p));
});
test('イベントはtype と text プロパティを持つ', () => {
    const p = { region: '北の森', directive: { focus: 'drops', conflict: 'leader' } };
    p.members = [genChar(), genChar()];
    // 100回試行してイベントが生成された場合検証
    for (let t = 0; t < 20; t++) {
        const events = generateWeekEvents(p);
        for (const e of events) {
            assert('type' in e, `typeフィールドがない: ${JSON.stringify(e)}`);
            assert('text' in e, `textフィールドがない: ${JSON.stringify(e)}`);
            assertType(e.text, 'string', `text が文字列でない`);
            assert(e.text.length > 0, 'text が空');
        }
    }
});
test('メンバー0人のパーティーはイベント配列が空', () => {
    const p = { region: '北の森', directive: { focus: 'steady', conflict: 'leader' }, members: [] };
    const events = generateWeekEvents(p);
    assertArray(events);
    assertEqual(events.length, 0, `空パーティーでもイベントが生成された: ${events.length}件`);
});

console.log('\n◆ tickParty() — 週次処理');
function makeParty(cpPerWeek = 20) {
    return {
        id: 1,
        name: 'テストパーティー',
        region: '北の森',
        targetItem: '剣',
        members: [genChar()],
        leaderId: null,
        directive: { focus: 'steady', conflict: 'leader', cpPerWeek },
        status: 'active',
        cpDebt: 0,
    };
}

test('十分なCPがある場合、cpPerWeek を控除する', () => {
    G_STATE.cp = 100; G_STATE.week = 1;
    const p = makeParty(20);
    const result = tickParty(p);
    assert(result !== null, 'result が null');
    assertEqual(G_STATE.cp, 80, `CP控除が不正: ${G_STATE.cp}`);
});
test('CP不足の場合、cpDebt が加算される', () => {
    G_STATE.cp = 5;
    const p = makeParty(20);
    p.cpDebt = 0;
    const result = tickParty(p);
    assert(result !== null, 'result が null');
    assertEqual(p.cpDebt, 20, `cpDebt が不正: ${p.cpDebt}`);
});
test('3週連続CP不足でパーティーが解散する', () => {
    G_STATE.cp = 0;
    const p = makeParty(20);
    p.cpDebt = 40; // すでに2週分の未払い
    tickParty(p);
    assertEqual(p.status, 'disbanded', `3週CP未払いで解散しなかった: ${p.status}`);
});
test('メンバー0人のパーティーは idle になる', () => {
    G_STATE.cp = 100;
    const p = makeParty(20);
    p.members = [];
    const result = tickParty(p);
    assert(result === null || p.status === 'idle', 'メンバー0人でもidleにならない');
});

console.log('\n◆ clamp() — 値の範囲制限');
test('上限を超えた場合に上限値を返す', () => {
    assertEqual(clamp(150, 0, 100), 100);
});
test('下限を下回った場合に下限値を返す', () => {
    assertEqual(clamp(-10, 0, 100), 0);
});
test('範囲内の値はそのまま返す', () => {
    assertEqual(clamp(50, 0, 100), 50);
});

console.log('\n◆ 状態管理 — G_STATE の初期化');
test('initRoster が roster にキャラクターを追加する', () => {
    G_STATE.roster = [];
    initRoster();
    assert(G_STATE.roster.length >= 1, 'ロスターが空のまま');
});
test('全rosterキャラが valid なgenCharオブジェクト', () => {
    G_STATE.roster = [];
    initRoster();
    for (const c of G_STATE.roster) {
        assertRange(c.age, 17, 45);
        assertRange(c.morale, 0, 100);
        assert(!c.dead, 'ロスターに死亡キャラがいる');
    }
});

console.log('\n◆ データ永続化 — saveState / loadState');
test('saveState → loadState でデータが復元される', () => {
    G_STATE.cp = 999; G_STATE.week = 42; G_STATE.year = 3;
    saveState();
    // 一旦状態をリセット
    G_STATE.cp = 0; G_STATE.week = 1; G_STATE.year = 1;
    const loaded = loadState();
    assert(loaded, 'loadState が false を返した');
    assertEqual(G_STATE.cp, 999, `CP が復元されない: ${G_STATE.cp}`);
    assertEqual(G_STATE.week, 42, `週が復元されない: ${G_STATE.week}`);
    assertEqual(G_STATE.year, 3, `年が復元されない: ${G_STATE.year}`);
});

// ========= 結果サマリー =========
console.log('\n' + '─'.repeat(40));
console.log(`結果: ${passed + failed} テスト中 ${passed} 件成功 / ${failed} 件失敗`);
if (errors.length > 0) {
    console.log('\n失敗したテスト:');
    errors.forEach(e => console.log(`  ✗ ${e.name}: ${e.msg}`));
}
console.log('─'.repeat(40));
process.exit(failed > 0 ? 1 : 0);
