"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const sidebar = fs.readFileSync("views/ringo/js/sidebar.js", "utf8");
const autocomplete = fs.readFileSync("views/main_css/js/func/autocomplete.js", "utf8");
const template = fs.readFileSync("views/ringo/index.html", "utf8");

assert.match(sidebar, /window\.ringoRanking/, "ranking state must be shared with mobile search");
assert.match(sidebar, /RINGO_TRENDING_REFRESH_MS\s*=\s*30000/, "visible tabs refresh trending every 30 seconds");
assert.match(sidebar, /document\.hidden/, "hidden tabs must not refresh trending");
assert.match(sidebar, /textContent\s*=\s*item\.title/, "trending titles must use safe DOM text");
assert.match(sidebar, /fetch\('\/api\/ranking\/view'/, "eligible document views must send the signed ticket");
assert.match(sidebar, /JSON\.stringify\(\{ ticket: ticket \}\)/, "view event sends only the opaque ticket");
assert.match(autocomplete, /window\.ringoRanking/, "mobile empty search must use the shared trending snapshot");
assert.doesNotMatch(autocomplete, /processTrendingHTML|cleanTitle|replace\(\/\^\[0-9\]/, "mobile search must not parse legacy HTML or alter titles");
assert.match(autocomplete, /classList\.add\('ringo_trending_results'\)/, "mobile trending results opt into the viewport popup layout");
assert.match(autocomplete, /getBoundingClientRect\(\)/, "viewport popup is positioned below its search input");
assert.match(sidebar, /title\.className\s*=\s*'ringo_trending_title'/, "rank and title have scoped layout hooks");
assert.match(template, /body\.namu #autocomplete_results_not_mobile\.ringo_trending_results,[\s\S]*body\.namu #autocomplete_results_mobile\.ringo_trending_results\s*\{[\s\S]*position:\s*fixed[\s\S]*left:\s*10px[\s\S]*right:\s*10px/, "mobile popular results override the later ID-based popup width with viewport bounds");

function makeElement(tagName) {
    return {
        tagName,
        children: [],
        className: "",
        href: "",
        style: {},
        _text: "",
        appendChild(child) {
            this.children.push(child);
            return child;
        },
        replaceChildren(...children) {
            this.children = children;
            this._text = "";
        },
        set textContent(value) {
            this.children = [];
            this._text = String(value);
        },
        get textContent() {
            return this._text + this.children.map((child) => child.textContent).join("");
        }
    };
}

async function verifyTrendingStates() {
    const sidebarTarget = makeElement("div");
    const documentListeners = {};
    const responses = [
        { ok: true, json: () => Promise.resolve({ response: "ok", items: [{ title: "2024 <script>", url: "/w/2024" }] }) },
        { ok: true, json: () => Promise.resolve({ response: "ok", items: [{ title: "새 문서", url: "/w/new" }] }) },
        { ok: true, json: () => Promise.resolve({ response: "ok", items: [] }) },
        { ok: false, json: () => Promise.resolve({}) }
    ];
    let fetchCalls = 0;
    const document = {
        hidden: false,
        createElement: makeElement,
        querySelector: () => sidebarTarget,
        getElementById: () => null,
        addEventListener(name, callback) {
            documentListeners[name] = callback;
        }
    };
    const window = {
        location: { origin: "https://ishswiki.xyz" },
        addEventListener() {},
        setInterval() {},
        setTimeout() {},
        clearTimeout() {}
    };
    const context = {
        URL,
        console: { warn() {} },
        document,
        fetch() {
            fetchCalls += 1;
            return Promise.resolve(responses.shift());
        },
        performance: { now: () => 0 },
        window
    };

    vm.runInNewContext(sidebar, context);
    await window.ringoRanking.refresh();
    assert.strictEqual(sidebarTarget.textContent, "1.2024 <script>", "safe DOM preserves a leading-digit title literally");
    assert.strictEqual(sidebarTarget.children[0].children[0].children[0].href, "/w/2024", "structured URL renders as an internal link");

    const mobileTarget = makeElement("div");
    window.ringoRanking.bindMobile(mobileTarget, () => true);
    await window.ringoRanking.refresh();
    assert.strictEqual(sidebarTarget.textContent, "1.새 문서", "sidebar receives the latest shared snapshot");
    assert.strictEqual(mobileTarget.textContent, "1.새 문서", "mobile empty search receives the same latest snapshot");

    await window.ringoRanking.refresh();
    assert.match(sidebarTarget.textContent, /표시할 실시간 인기 문서가 없습니다/, "empty trending response has an ordinary empty state");

    await window.ringoRanking.refresh();
    assert.match(sidebarTarget.textContent, /불러올 수 없습니다/, "non-200 trending response has an ordinary failure state");

    document.hidden = true;
    await window.ringoRanking.refresh();
    assert.strictEqual(fetchCalls, 4, "hidden tabs do not refresh trending");
}

async function verifyTicketDelay() {
    const documentListeners = {};
    const windowListeners = {};
    const timers = [];
    const calls = [];
    let now = 0;
    const document = {
        hidden: true,
        createElement: makeElement,
        querySelector: () => makeElement("div"),
        getElementById(id) {
            return id === "ranking_ticket" ? { dataset: { rankingTicket: "signed-ticket" } } : null;
        },
        addEventListener(name, callback) {
            documentListeners[name] = documentListeners[name] || [];
            documentListeners[name].push(callback);
        }
    };
    const window = {
        location: { origin: "https://ishswiki.xyz" },
        addEventListener(name, callback) {
            windowListeners[name] = callback;
        },
        setInterval() {},
        setTimeout(callback, delay) {
            const timer = { callback, delay, cleared: false };
            timers.push(timer);
            return timer;
        },
        clearTimeout(timer) {
            timer.cleared = true;
        }
    };
    const context = {
        URL,
        console: { warn() {} },
        document,
        fetch(url, options) {
            calls.push({ url, options });
            if(url === "/api/trending") {
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ response: "ok", items: [] }) });
            }
            return Promise.resolve({ ok: true });
        },
        performance: { now: () => now },
        window
    };
    const emitVisibility = () => documentListeners.visibilitychange.forEach((callback) => callback());

    vm.runInNewContext(sidebar, context);
    windowListeners.DOMContentLoaded();
    assert.strictEqual(calls.filter((call) => call.url === "/api/ranking/view").length, 0, "hidden time does not count toward a view");

    document.hidden = false;
    emitVisibility();
    now = 2000;
    document.hidden = true;
    emitVisibility();
    now = 3000;
    document.hidden = false;
    emitVisibility();
    const activeTimer = timers.find((timer) => !timer.cleared && timer.delay === 3000);
    assert.ok(activeTimer, "resume schedules only the remaining foreground time");
    activeTimer.callback();
    activeTimer.callback();

    const viewCalls = calls.filter((call) => call.url === "/api/ranking/view");
    assert.strictEqual(viewCalls.length, 1, "five foreground seconds send one view event");
    assert.strictEqual(viewCalls[0].options.credentials, "same-origin", "view event uses same-origin credentials");
    assert.strictEqual(viewCalls[0].options.body, JSON.stringify({ ticket: "signed-ticket" }), "view event sends only the opaque ticket");
}

function createTicketViewHarness(viewFetch, hidden) {
    const documentListeners = {};
    const windowListeners = {};
    const timers = [];
    const calls = [];
    let now = 0;
    const document = {
        hidden,
        createElement: makeElement,
        querySelector: () => makeElement("div"),
        getElementById(id) {
            return id === "ranking_ticket" ? { dataset: { rankingTicket: "signed-ticket" } } : null;
        },
        addEventListener(name, callback) {
            documentListeners[name] = documentListeners[name] || [];
            documentListeners[name].push(callback);
        }
    };
    const window = {
        location: { origin: "https://ishswiki.xyz" },
        addEventListener(name, callback) {
            windowListeners[name] = callback;
        },
        setInterval() {},
        setTimeout(callback, delay) {
            const timer = { delay, cleared: false, fired: false };
            timer.callback = () => {
                timer.fired = true;
                callback();
            };
            timers.push(timer);
            return timer;
        },
        clearTimeout(timer) {
            if(timer) {
                timer.cleared = true;
            }
        }
    };
    const context = {
        URL,
        console: { warn() {} },
        document,
        fetch(url, options) {
            if(url === "/api/trending") {
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ response: "ok", items: [] }) });
            }
            calls.push({ url, options });
            return viewFetch(calls.length);
        },
        performance: { now: () => now },
        window
    };
    const emitVisibility = () => documentListeners.visibilitychange.forEach((callback) => callback());

    vm.runInNewContext(sidebar, context);
    windowListeners.DOMContentLoaded();
    return {
        calls,
        document,
        emitVisibility,
        setNow(value) {
            now = value;
        },
        runTimer(delay) {
            const timer = timers.filter((item) => !item.cleared && !item.fired && item.delay === delay).pop();
            assert.ok(timer, "expected an active " + delay + "ms timer");
            timer.callback();
            return timer;
        },
        hasTimer(delay) {
            return timers.some((item) => !item.cleared && !item.fired && item.delay === delay);
        },
        lastTimer(delay) {
            return timers.filter((item) => item.delay === delay).pop();
        }
    };
}

function flushPromises() {
    return new Promise((resolve) => setImmediate(resolve));
}

async function verifyTicketDeliveryRetries() {
    let rejectFirst;
    const network = createTicketViewHarness((attempt) => {
        if(attempt === 1) {
            return new Promise((resolve, reject) => {
                rejectFirst = reject;
            });
        }
        return Promise.resolve({ ok: true, status: 200 });
    }, false);
    const initialTimer = network.runTimer(5000);
    initialTimer.callback();
    assert.strictEqual(network.calls.length, 1, "repeated timer callbacks while a request is pending do not send parallel views");
    rejectFirst(new Error("offline"));
    await flushPromises();
    network.runTimer(1000);
    await flushPromises();
    assert.strictEqual(network.calls.length, 2, "a network rejection retries after a bounded delay");
    assert.strictEqual(network.hasTimer(1000), false, "acknowledged retry success stops further sends");
    initialTimer.callback();
    assert.strictEqual(network.calls.length, 2, "acknowledged success cannot send a duplicate view");

    const serverError = createTicketViewHarness((attempt) => Promise.resolve(
        attempt === 1 ? { ok: false, status: 503 } : { ok: true, status: 200 }
    ), false);
    serverError.runTimer(5000);
    await flushPromises();
    serverError.runTimer(1000);
    await flushPromises();
    assert.strictEqual(serverError.calls.length, 2, "a 5xx response retries and records only the acknowledged success");

    const bounded = createTicketViewHarness(() => Promise.resolve({ ok: false, status: 503 }), false);
    bounded.runTimer(5000);
    await flushPromises();
    bounded.runTimer(1000);
    await flushPromises();
    bounded.runTimer(1000);
    await flushPromises();
    assert.strictEqual(bounded.calls.length, 3, "recoverable failures stop after two delayed retries");
    assert.strictEqual(bounded.hasTimer(1000), false, "retry exhaustion cannot create an immediate loop");

    const interrupted = createTicketViewHarness((attempt) => Promise.resolve(
        attempt === 1 ? { ok: false, status: 503 } : { ok: true, status: 200 }
    ), false);
    interrupted.runTimer(5000);
    await flushPromises();
    for(let cycle = 0; cycle < 2; cycle++) {
        assert.strictEqual(interrupted.hasTimer(1000), true, "a recoverable retry is pending before visibility changes");
        interrupted.document.hidden = true;
        interrupted.emitVisibility();
        interrupted.document.hidden = false;
        interrupted.emitVisibility();
    }
    interrupted.runTimer(1000);
    await flushPromises();
    assert.strictEqual(interrupted.calls.length, 2, "canceled retry timers do not exhaust the retry budget before dispatch");

    const stalled = createTicketViewHarness(() => Promise.resolve({ ok: true, status: 200 }), true);
    stalled.document.hidden = false;
    stalled.emitVisibility();
    const staleTimer = stalled.lastTimer(5000);
    stalled.document.hidden = true;
    stalled.emitVisibility();
    staleTimer.callback();
    stalled.document.hidden = false;
    stalled.emitVisibility();
    assert.strictEqual(stalled.calls.length, 1, "a visible resume sends a qualified view after a hidden timer callback was guarded");

    for(const status of [403, 400]) {
        const permanentError = createTicketViewHarness(() => Promise.resolve({ ok: false, status }), false);
        permanentError.runTimer(5000);
        await flushPromises();
        permanentError.document.hidden = true;
        permanentError.emitVisibility();
        permanentError.document.hidden = false;
        permanentError.emitVisibility();
        assert.strictEqual(permanentError.calls.length, 1, "permanent " + status + " responses do not retry after visibility changes");
        assert.strictEqual(permanentError.hasTimer(1000), false, "permanent " + status + " responses do not schedule retries");
    }

    const hidden = createTicketViewHarness(() => Promise.resolve({ ok: true, status: 200 }), true);
    assert.strictEqual(hidden.calls.length, 0, "hidden documents do not schedule a qualified view");
    hidden.document.hidden = false;
    hidden.emitVisibility();
    hidden.document.hidden = true;
    hidden.emitVisibility();
    assert.strictEqual(hidden.calls.length, 0, "hidden documents do not send a qualified view");
    assert.strictEqual(hidden.hasTimer(5000), false, "hiding clears the pending qualification timer");
}

async function verifyRefreshDeduplication() {
    const target = makeElement("div");
    let resolveResponse;
    const document = {
        hidden: false,
        createElement: makeElement,
        querySelector: () => target,
        getElementById: () => null,
        addEventListener() {}
    };
    const window = {
        location: { origin: "https://ishswiki.xyz" },
        addEventListener() {},
        setInterval() {},
        setTimeout() {},
        clearTimeout() {}
    };
    const context = {
        URL,
        console: { warn() {} },
        document,
        fetch() {
            return new Promise((resolve) => {
                resolveResponse = resolve;
            });
        },
        performance: { now: () => 0 },
        window
    };

    vm.runInNewContext(sidebar, context);
    const first = window.ringoRanking.refresh();
    const second = window.ringoRanking.refresh();
    assert.strictEqual(first, second, "concurrent visible refreshes share one request");
    resolveResponse({ ok: true, json: () => Promise.resolve({ response: "ok", items: [] }) });
    await first;
}

Promise.all([verifyTrendingStates(), verifyTicketDelay(), verifyTicketDeliveryRetries(), verifyRefreshDeduplication()]).then(() => {
    console.log("rankings UI contract checks passed");
}).catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
