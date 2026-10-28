/**
 * verify_math_renderer.js
 * Verification of CodeMind AI's Markdown-to-HTML and KaTeX rendering pipeline
 * loaded directly from frontend/static/js/api.js.
 */

const fs = require('fs');
const path = require('path');

// 1. Setup DOM and environment mocks before evaluating api.js
global.window = global;
global.window.addEventListener = () => {};
global.window.fetch = async () => ({
  ok: true,
  status: 200,
  json: async () => ({}),
  text: async () => "{}"
});
global.document = {
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => null,
  addEventListener: () => {},
  removeEventListener: () => {},
  createElement: (tag) => {
    return {
      tagName: tag.toUpperCase(),
      set textContent(v) { this._text = v; },
      get innerHTML() {
        return (this._text || '')
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#039;');
      }
    };
  }
};
global.localStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {}
};
global.sessionStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
  clear: () => {}
};
global.location = {
  pathname: '/assistant',
  search: '',
  href: ''
};
global.navigator = {
  userAgent: 'NodeVerification'
};

// Load bundled KaTeX
const katexVendorPath = path.resolve(__dirname, '../../frontend/static/vendor/katex/katex.min.js');
global.katex = require(katexVendorPath);

// Read and evaluate api.js
const apiJsPath = path.resolve(__dirname, '../../frontend/static/js/api.js');
const apiJsCode = fs.readFileSync(apiJsPath, 'utf8');
eval(apiJsCode);

let testsRun = 0;
let testsPassed = 0;

function assert(condition, message) {
  testsRun++;
  if (!condition) {
    console.error(`FAIL: ${message}`);
    throw new Error(`Assertion failed: ${message}`);
  }
  testsPassed++;
  console.log(`PASS: ${message}`);
}

console.log('--- 1. DELIMITER & NOTATION TESTS ---');

// Inline \( ... \)
const inline1 = renderMarkdown('The theorem is \\( c^2 = a^2 + b^2 \\) in geometry.');
assert(inline1.includes('class="math-inline"'), 'Inline \\( ... \\) wrapped in math-inline');
assert(inline1.includes('class="katex"'), 'Inline \\( ... \\) rendered by KaTeX');
assert(!inline1.includes('\\(') && !inline1.includes('\\)'), 'Inline delimiters stripped');

// Display \[ ... \]
const disp1 = renderMarkdown('Here is mass-energy equivalence:\n\n\\[ E = mc^2 \\]\n\nEnd.');
assert(disp1.includes('class="math-display"'), 'Display \\[ ... \\] wrapped in math-display');
assert(disp1.includes('class="katex-display"'), 'Display \\[ ... \\] has katex-display class');
assert(!disp1.includes('\\[') && !disp1.includes('\\]'), 'Display delimiters stripped');

// Display $$ ... $$
const disp2 = renderMarkdown('Here is the quadratic equation:\n\n$$ x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a} $$\n\nDone.');
assert(disp2.includes('class="math-display"'), 'Display $$ ... $$ wrapped in math-display');
assert(disp2.includes('class="katex-display"'), 'Display $$ ... $$ rendered by KaTeX');
assert(!disp2.includes('$$'), '$$ delimiters stripped');

// Inline $ ... $ (non-currency)
const inline2 = renderMarkdown('Energy $E = mc^2$ is fundamental.');
assert(inline2.includes('class="math-inline"'), 'Inline $ ... $ wrapped in math-inline');
assert(inline2.includes('class="katex"'), 'Inline $ ... $ rendered by KaTeX');

console.log('--- 2. ADVANCED MATHEMATICAL STRUCTURES ---');

// Fractions and roots
const fracRoot = renderMarkdown('\\[ \\sqrt{\\frac{a^2 + b^2}{2}} \\]');
assert(fracRoot.includes('class="math-display"'), 'Fractions and square roots rendered');
assert(fracRoot.includes('sqrt') || fracRoot.includes('mord'), 'Square root DOM generated');

// Superscripts, subscripts, Greek letters
const greekSub = renderMarkdown('Relation: \\( \\alpha_i^2 + \\beta_j^2 = \\theta \\)');
assert(greekSub.includes('class="math-inline"'), 'Greek symbols and sub/superscripts rendered');
assert(greekSub.includes('&alpha;') || greekSub.includes('\u03b1') || greekSub.includes('alpha'), 'Greek letter in rendered DOM');

// Multiple equations in one response
const multiEq = renderMarkdown(`
### Mathematical Foundations
1. First equation: \\( a^2 + b^2 = c^2 \\)
2. Second equation:
\\[ E = mc^2 \\]
3. Third equation: \\( (x+y)^2 = x^2 + 2xy + y^2 \\)
`);
assert(multiEq.match(/class="math-inline"/g)?.length === 2, 'Multiple inline equations rendered');
assert(multiEq.match(/class="math-display"/g)?.length === 1, 'Display equation rendered in multi-equation body');

console.log('--- 3. STREAMING & BUFFERING TESTS ---');

// Trailing unclosed display delimiter \[
const stream1 = renderMarkdown('The equation is \\[');
assert(!stream1.includes('@@CM_') && !stream1.includes('\\['), 'Trailing unclosed \\[ stripped cleanly without leaking placeholder');

// Trailing unclosed display $$
const stream2 = renderMarkdown('The equation is $$');
assert(!stream2.includes('@@CM_') && !stream2.includes('$$'), 'Trailing unclosed $$ stripped cleanly');

// Incomplete display delimiter with body
const stream3 = renderMarkdown('The equation is \\[ E = mc^2');
assert(stream3.includes('class="math-display"'), 'Incomplete \\[ with body rendered safely');
assert(!stream3.includes('@@CM_'), 'No placeholder leaks in incomplete display');

// Trailing unclosed inline \(
const stream4 = renderMarkdown('We compute \\(');
assert(!stream4.includes('@@CM_') && !stream4.includes('\\('), 'Trailing unclosed \\( stripped cleanly');

// Incomplete inline delimiter with body
const stream5 = renderMarkdown('We compute \\( a^2 + b^2');
assert(stream5.includes('class="math-inline"'), 'Incomplete \\( with body rendered safely');

// Incomplete inline $ with body
const stream6 = renderMarkdown('The value $x + y');
assert(stream6.includes('class="math-inline"'), 'Incomplete $ with body rendered safely');

console.log('--- 4. EDGE CASES & COEXISTENCE ---');

// Currency values should NOT be parsed as math
const currency = renderMarkdown('The service costs $100 or $50.99 for annual plan.');
assert(!currency.includes('class="math-inline"'), 'Currency values $100 and $50.99 not parsed as math');
assert(currency.includes('$100') && currency.includes('$50.99'), 'Currency values preserved in text');

// Code block with LaTeX-like characters
const codeBlock = renderMarkdown('Here is code:\n```python\n# This is not LaTeX: \\[ x = 1 \\]\ndef test():\n    return "$100"\n```\nAnd math: \\( x = 1 \\)');
assert(codeBlock.includes('<pre><code class="language-python">'), 'Code block rendered');
assert(codeBlock.includes('# This is not LaTeX: \\[ x = 1 \\]'), 'Code block contents verbatim');
assert(codeBlock.includes('class="math-inline"'), 'Math outside code block rendered');

// Inline code with math delimiters
const inlineCode = renderMarkdown('Use `\\[ x = 1 \\]` in your docs, but write \\( x = 1 \\) for equations.');
assert(inlineCode.includes('<code class="inline-code">'), 'Inline code rendered');
assert(inlineCode.includes('class="math-inline"'), 'Inline math rendered outside code');

// Adjacent citations and math
const mathWithCitation = renderMarkdown('The score is given by \\( s = 0.5 v + 0.3 k \\) [Source 1: file.py (Lines 10-20)].');
assert(mathWithCitation.includes('class="math-inline"'), 'Math rendered alongside citation');
assert(mathWithCitation.includes('class="citation-pill"'), 'Citation pill rendered correctly');

// Malformed math handling (graceful fallback, no uncaught exception)
const malformedMath = renderMarkdown('Bad math: \\[ \\frac{1}{ \\]');
assert(malformedMath.includes('class="math-display"'), 'Malformed math handled without exception');

// Idempotent repeated rendering (streaming re-render simulation)
let textAcc = '';
const chunks = ['Here is ', 'the formula: ', '\\[ ', 'E = ', 'mc^2 ', '\\] ', 'and done.'];
for (const chunk of chunks) {
  textAcc += chunk;
  const rendered = renderMarkdown(textAcc);
  assert(!rendered.includes('undefined') && !rendered.includes('@@CM_'), `Streaming step rendered cleanly without corruption: "${chunk}"`);
}
const finalRendered = renderMarkdown(textAcc);
assert(finalRendered.includes('class="math-display"'), 'Final stream chunk renders complete display math');

console.log('--- 5. KATEX FALLBACK TEST (WHEN KATEX GLOBAL IS ABSENT) ---');

// Temporarily remove global.katex
const savedKatex = global.katex;
global.katex = undefined;

const fallbackDisplay = renderMarkdown('\\[ c^2 = a^2 + b^2 \\]');
assert(fallbackDisplay.includes('class="katex-fallback"'), 'Fallback display container rendered when KaTeX absent');
assert(fallbackDisplay.includes('c^2 = a^2 + b^2'), 'Formula preserved in fallback');

const fallbackInline = renderMarkdown('\\( x = 10 \\)');
assert(fallbackInline.includes('class="katex-fallback"'), 'Fallback inline container rendered when KaTeX absent');
assert(fallbackInline.includes('x = 10'), 'Inline formula preserved in fallback');

// Restore global.katex
global.katex = savedKatex;

console.log(`\n========================================`);
console.log(`MATH RENDERER AUDIT: ${testsPassed}/${testsRun} PASSED`);
console.log(`========================================`);

process.exit(0);
