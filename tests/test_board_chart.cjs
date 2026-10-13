// Exercise the real board script without loading external fonts or Chart.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync('src/sentra/board/board.html', 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

function board(days) {
  const nodes = new Map();
  const element = () => ({ children: [], style: { setProperty() {} },
    appendChild(child) { this.children.push(child); }, setAttribute() {}, addEventListener() {} });
  const get = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
  let chart;
  const context = {
    document: { documentElement: element(), getElementById: get, createElement: element, querySelector: element },
    getComputedStyle: () => ({ getPropertyValue: () => '#999' }),
    matchMedia: () => ({ addEventListener() {} }), MutationObserver: class { observe() {} },
    Chart: class { constructor(_, config) { chart = config; } destroy() {} },
  };
  context.window = context;
  const data = [{ id: 'p01', name: 'p01', device: 'Fitbit', days }];
  vm.runInNewContext(source.replace('/*__SENTRA_DATA__*/[]', JSON.stringify(data)), context);
  return { get, points: () => Array.from(chart.data.datasets[0].data) };
}

test('missing baselines stay missing instead of using current or future values', () => {
  const page = board([{ d: '2026-10-01', rhr: 60 }, { d: '2026-10-02', rhr: 100 }]);
  page.get('metric').children.find(button => button.id === 'mt-rhr').onclick();
  assert.deepEqual(page.points(), [60, 100]);
  page.get('m-rel').onclick();
  assert.deepEqual(page.points(), [null, null]);
});

test('each metric uses its supplied per-day baseline in relative trends', () => {
  for (const [metric, baseline] of [['sleep_hr', 'sleep_hr_b'], ['steps', 'steps_b'], ['br', 'br_b'], ['temp', 'temp_b']]) {
    const page = board([{ d: '2026-10-01', [metric]: 60, [baseline]: 50 },
                        { d: '2026-10-02', [metric]: 100 }]);
    page.get('metric').children.find(button => button.id === 'mt-' + metric).onclick();
    page.get('m-rel').onclick();
    assert.deepEqual(page.points(), [10, null], metric);
  }
});

test('sleeping HR card compares against its supplied baseline', () => {
  const page = board([{ d: '2026-10-01', sleep_hr: 60, sleep_hr_b: 50 }]);
  assert.ok(page.get('cards').children[0].innerHTML.includes('▲ 10 vs normal'));
});
