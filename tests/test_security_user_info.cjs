"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "..", "views", "main_css", "js", "func", "insert_user_info.js"), "utf8");

function profile() {
    return {
        data: {
            auth: "member", auth_date: "0", ban: "0", render: "target", gender: "female",
            student_id: "S-TEST-01", real_name: "Synthetic Name", birth: "2000-01-02", generation: "test",
        },
        language: {user_name: "user", authority: "authority", state: "state", normal: "normal"},
    };
}

async function run(response) {
    const target = {
        value: "target",
        get innerHTML() { return this.value; },
        set innerHTML(value) { this.value = value; },
        get textContent() { return this.value; },
        set textContent(value) { this.value = value; },
    };
    const context = {
        document: {getElementById: (id) => id === "opennamu_get_user_info" ? target : null},
        fetch: () => response,
        opennamu_do_url_encode: encodeURIComponent,
        opennamu_xss_filter: (value) => value,
        Error,
        Promise,
        setTimeout,
    };
    vm.runInNewContext(script, context);
    await new Promise((resolve) => setTimeout(resolve, 0));
    return target.value;
}

test("member response retains the user-info table", async () => {
    const rendered = await run(Promise.resolve({ok: true, status: 200, json: async () => profile()}));
    assert.match(rendered, /user_info_table/);
    assert.match(rendered, /Synthetic Name/);
});

test("401 clears stale profile data and shows a login prompt", async () => {
    const rendered = await run(Promise.resolve({ok: false, status: 401, json: async () => ({error: "login_required"})}));
    assert.equal(rendered, "로그인이 필요합니다.");
    assert.doesNotMatch(rendered, /S-TEST-01|Synthetic Name/);
});

test("other HTTP and network failures clear stale profile data", async () => {
    const failedHttp = await run(Promise.resolve({ok: false, status: 500, json: async () => ({})}));
    const failedNetwork = await run(Promise.reject(new Error("offline")));
    assert.equal(failedHttp, "");
    assert.equal(failedNetwork, "");
});
