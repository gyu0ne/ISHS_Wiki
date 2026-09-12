"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const renderSource = readFileSync(
    join(__dirname, "../views/main_css/js/func/render.js"),
    "utf8"
);
const funcSource = readFileSync(
    join(__dirname, "../views/main_css/js/func/func.js"),
    "utf8"
);

function mathElement(tex) {
    return {
        dataset: tex === undefined ? {} : { tex },
        style: {},
        textContent: ""
    };
}

function makeContext({ elements = [], readyState = "complete", katex } = {}) {
    const listeners = new Map();
    const document = {
        readyState,
        addEventListener(type, listener, options) {
            listeners.set(type, { listener, options });
        },
        getElementById() {
            return null;
        },
        querySelectorAll(selector) {
            assert.equal(selector, ".opennamu-math");
            return elements;
        }
    };
    const window = {
        addEventListener(type, listener, options) {
            listeners.set(type, { listener, options });
        }
    };
    if (katex !== undefined) {
        window.katex = katex;
    }

    const context = vm.createContext({
        console,
        document,
        URLSearchParams,
        window
    });
    vm.runInContext(renderSource, context, { filename: "render.js" });

    return { context, document, listeners, window };
}

test("passes the exact TeX source to KaTeX", () => {
    const element = mathElement(String.raw`\frac{a_1}{\sqrt{b}}`);
    const calls = [];
    const { context } = makeContext({
        elements: [element],
        katex: { render: (...args) => calls.push(args) }
    });

    context.opennamu_render_math();

    assert.deepEqual(calls, [[String.raw`\frac{a_1}{\sqrt{b}}`, element]]);
});

test("uses literal text when KaTeX is missing or rejects the expression", async (t) => {
    await t.test("missing KaTeX", () => {
        const tex = '</script><script>alert(1)</script>';
        const element = mathElement(tex);
        const { context } = makeContext({ elements: [element] });

        context.opennamu_render_math();

        assert.equal(element.textContent, tex);
    });

    await t.test("invalid TeX", () => {
        const tex = String.raw`\broken{<img src=x onerror=alert(1)>`;
        const element = mathElement(tex);
        const { context } = makeContext({
            elements: [element],
            katex: { render: () => { throw new Error("invalid TeX"); } }
        });

        context.opennamu_render_math();

        assert.equal(element.textContent, tex);
        assert.equal(element.style.color, "red");
    });
});

test("waits for window load when KaTeX has not loaded yet", () => {
    const element = mathElement("x+y");
    const calls = [];
    const { context, listeners, window } = makeContext({
        elements: [element],
        readyState: "loading"
    });

    context.opennamu_render_math();
    assert.equal(element.dataset.mathRendered, undefined);
    assert.equal(listeners.get("load").options.once, true);

    window.katex = { render: (...args) => calls.push(args) };
    listeners.get("load").listener();

    assert.deepEqual(calls, [["x+y", element]]);
});

test("does not render the same element twice", () => {
    const element = mathElement("z");
    let renderCount = 0;
    const { context } = makeContext({
        elements: [element],
        katex: { render: () => { renderCount += 1; } }
    });

    context.opennamu_render_math();
    context.opennamu_render_math();

    assert.equal(renderCount, 1);
    assert.equal(element.dataset.mathRendered, "1");
});

test("dynamic rendering processes math before invoking its callback", async () => {
    const element = mathElement(String.raw`\alpha+1`);
    const target = {
        innerHTML: "",
        querySelectorAll(selector) {
            assert.equal(selector, ".opennamu-math");
            return [element];
        }
    };
    const { context, document } = makeContext({
        katex: {
            render(tex) {
                element.renderedTex = tex;
            }
        }
    });
    document.getElementById = id => id === "preview" ? target : null;
    context.fetch = async () => ({
        ok: true,
        json: async () => ({ data: "<span>math</span>", js_data: "" })
    });
    vm.runInContext(funcSource, context, { filename: "func.js" });

    await new Promise((resolve, reject) => {
        context.opennamu_do_render("preview", "source", "", "", "", () => {
            try {
                assert.equal(element.renderedTex, String.raw`\alpha+1`);
                resolve();
            } catch (error) {
                reject(error);
            }
        });
    });

    assert.equal(target.innerHTML, "<span>math</span>");
});
