// The desktop half's MCP Apps bridge (desktop/plugin.js, between the
// card-bridge markers), run under node with fakes for the frame and ctx.rest.
//   node --test tests/card_bridge.test.mjs
// (tests/test_card_bridge_js.py runs this from pytest when node is installed.)

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const start = source.indexOf('/* card-bridge:start */')
const end = source.indexOf('/* card-bridge:end */')
assert.ok(start > 0 && end > start, 'card-bridge markers missing from desktop/plugin.js')

const EXPORTS = [
  'CARD_TOOLS', 'CARD_ALWAYS_RELAYED', 'CARD_RETRYABLE_TOOLS', 'CARD_NEVER_RELAYED',
  'CARD_HEIGHT_MIN', 'CARD_HEIGHT_MAX', 'CARD_CANCELLED_TEXT', 'CARD_PROTOCOL_VERSION',
  'cardToolDecision', 'stripSecrets', 'clampCardHeight', 'fitCard', 'isHttpsUrl',
  'createRateLimiter', 'createCardBridge', 'cardInitializeResult',
]
const bridge = new Function(`${source.slice(start, end)}\nreturn { ${EXPORTS.join(', ')} }`)()

const PORTFOLIO = 'ui://coinfello/portfolio-card.html'
const QUOTE = 'ui://coinfello/quote-card.html'
const INTENT = '66666666-6666-6666-6666-666666666666'

function harness({ uri = PORTFOLIO, structured = {}, rest, confirm, limiter } = {}) {
  const posted = []
  const restCalls = []
  const opened = []
  const sizes = []
  const card = {
    id: 'c'.repeat(32),
    uri,
    tool_input: { arguments: { token: 'USDC' } },
    tool_result: { content: [{ type: 'text', text: 'raw' }], structuredContent: structured },
  }
  const instance = bridge.createCardBridge({
    card,
    post: (message) => posted.push(message),
    rest: async (path, options) => {
      restCalls.push([path, options.body])
      return rest ? rest(path, options.body) : { ok: true, result: { content: [{ type: 'text', text: 'ok' }] } }
    },
    confirm: confirm || (async () => null),
    openExternal: (url) => opened.push(url),
    onSize: (params) => sizes.push(params),
    context: () => ({ theme: 'dark', locale: 'en-GB', width: 296 }),
    newId: () => 'teardown-1',
    limiter,
  })
  return { instance, posted, restCalls, opened, sizes, card }
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

test('answers ui/initialize with the host context', () => {
  const { instance, posted } = harness()
  instance.handle({ jsonrpc: '2.0', id: 1, method: 'ui/initialize', params: { protocolVersion: '2026-01-26' } })
  assert.equal(posted.length, 1)
  const { result } = posted[0]
  assert.equal(posted[0].id, 1)
  assert.equal(result.protocolVersion, '2026-01-26')
  assert.deepEqual(result.hostCapabilities, { openLinks: {}, serverTools: {} })
  assert.equal(result.hostContext.theme, 'dark')
  assert.equal(result.hostContext.displayMode, 'inline')
  assert.equal(result.hostContext.platform, 'desktop')
  assert.equal(result.hostContext.locale, 'en-GB')
  assert.deepEqual(result.hostContext.containerDimensions, { width: 296, maxHeight: 1400 })
})

test('sends tool input, then the raw tool result, once the card is initialized', () => {
  const { instance, posted, card } = harness()
  instance.handle({ jsonrpc: '2.0', method: 'ui/notifications/initialized' })
  assert.deepEqual(posted.map((m) => m.method), ['ui/notifications/tool-input', 'ui/notifications/tool-result'])
  assert.deepEqual(posted[0].params, { arguments: { token: 'USDC' } })
  assert.deepEqual(posted[1].params, card.tool_result)
})

test('ignores anything that is not JSON-RPC 2.0', () => {
  const { instance, posted } = harness()
  for (const message of [null, 'x', { id: 1, method: 'ui/initialize' }, { jsonrpc: '1.0', id: 1, method: 'ui/initialize' },
    { type: 'hermes-guest-loaded' }]) {
    instance.handle(message)
  }
  assert.deepEqual(posted, [])
})

test('size changes reach the pane; heights are clamped', () => {
  const { instance, sizes } = harness()
  instance.handle({ jsonrpc: '2.0', method: 'ui/notifications/size-changed', params: { width: 480, height: 900 } })
  assert.deepEqual(sizes, [{ width: 480, height: 900 }])
  assert.equal(bridge.clampCardHeight(10), 120)
  assert.equal(bridge.clampCardHeight(5000), 1400)
  assert.equal(bridge.clampCardHeight('nope'), 120)
  assert.equal(bridge.clampCardHeight(640.2), 641)
})

test('a card that overflows the pane is laid out wider and scaled, and stays that way', () => {
  assert.deepEqual(bridge.fitCard({ container: 296, reported: 296, latched: null }), { layoutWidth: 296, scale: 1, latched: null })
  const wide = bridge.fitCard({ container: 296, reported: 480, latched: null })
  assert.equal(wide.layoutWidth, 480)
  assert.equal(wide.latched, 480)
  assert.ok(Math.abs(wide.scale - 296 / 480) < 1e-9)
  // Laid out at 480 the card stops overflowing; the latch keeps the layout.
  assert.equal(bridge.fitCard({ container: 296, reported: 480, latched: 480 }).layoutWidth, 480)
  assert.equal(bridge.fitCard({ container: 296, reported: 2000, latched: null }).layoutWidth, 560)
  assert.equal(bridge.fitCard({ container: 600, reported: 480, latched: null }).scale, 1)
})

test('relays an allowed tool to /cards/{id}/call and returns its raw result', async () => {
  const { instance, posted, restCalls } = harness()
  instance.handle({ jsonrpc: '2.0', id: 7, method: 'tools/call',
    params: { name: 'show_portfolio_card', arguments: { session_token: 'tok', nested: { embedToken: 'e', keep: 1 } } } })
  await settle()
  assert.deepEqual(restCalls, [[`/cards/${'c'.repeat(32)}/call`, { tool: 'show_portfolio_card', arguments: { nested: { keep: 1 } } }]])
  assert.deepEqual(posted, [{ jsonrpc: '2.0', id: 7, result: { content: [{ type: 'text', text: 'ok' }] } }])
})

test('refuses everything else with -32601, without calling the backend', async () => {
  for (const name of ['sign_out', 'fello_chat', 'privy_complete_approval', 'start_browser_sign_in', 'renew_session',
    'create_embed_token', 'set_daily_limit', 'start_limit_change', 'get_balances', 'execute_intent', 'show_quote_card', '']) {
    const { instance, posted, restCalls } = harness()
    instance.handle({ jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name, arguments: {} } })
    await settle()
    assert.deepEqual(restCalls, [], name)
    assert.equal(posted[0].error.code, -32601, name)
  }
})

test("the error card's Retry is checked against the retryable list and the card's own retryTool", () => {
  const error = 'ui://coinfello/error-card.html'
  assert.equal(bridge.cardToolDecision(error, 'get_balances', { retryTool: 'get_balances' }), 'relay')
  assert.equal(bridge.cardToolDecision(error, 'get_positions', { retryTool: 'get_balances' }), 'deny')
  assert.equal(bridge.cardToolDecision(error, 'fello_chat', { retryTool: 'fello_chat' }), 'deny')
  assert.equal(bridge.cardToolDecision(error, 'execute_intent', { retryTool: 'execute_intent' }), 'deny')
  assert.equal(bridge.cardToolDecision('ui://elsewhere/x.html', 'whoami', {}), 'deny')
  assert.equal(bridge.cardToolDecision('__proto__', 'whoami', {}), 'deny')
})

const YIELD = 'ui://coinfello/yield-card.html'
const EARN = 'ui://coinfello/earn-deposit-card.html'

test('the yield and earn deposit cards reach each other, and money still needs the confirm sheet', () => {
  for (const [uri, other] of [[YIELD, 'show_earn_deposit_card'], [EARN, 'show_yield_card']]) {
    assert.equal(bridge.cardToolDecision(uri, other, {}), 'relay', uri)
    assert.equal(bridge.cardToolDecision(uri, 'prepare_earn_deposit', {}), 'relay', uri)
    assert.equal(bridge.cardToolDecision(uri, 'execute_intent', {}), 'confirm', uri)
    for (const name of ['prepare_swap', 'prepare_send', 'cancel_automation', 'show_quote_card', 'fello_chat', 'create_embed_token']) {
      assert.equal(bridge.cardToolDecision(uri, name, {}), 'deny', `${uri} ${name}`)
    }
  }
  // Only these two are joined: no other card gains the deposit tools.
  assert.equal(bridge.cardToolDecision(PORTFOLIO, 'show_earn_deposit_card', {}), 'deny')
  assert.equal(bridge.cardToolDecision(QUOTE, 'prepare_earn_deposit', {}), 'deny')
})

test('Check status is relayed only from cards that can end in an unknown outcome', () => {
  const status = ['quote', 'send', 'dca', 'earn-deposit', 'yield'].map((name) => `ui://coinfello/${name}-card.html`)
  for (const [uri, card] of Object.entries(bridge.CARD_TOOLS)) {
    const expected = status.includes(uri) || card.tool === 'show_status_card' ? 'relay' : 'deny'
    assert.equal(bridge.cardToolDecision(uri, 'show_status_card', {}), expected, uri)
  }
  for (const uri of status) assert.equal(bridge.cardToolDecision(uri, 'execute_intent', {}), 'confirm', uri)
})

test("a yield row's Deposit gets the earn card's result back raw, to draw in the same frame", async () => {
  const earnCard = {
    content: [{ type: 'text', text: 'Earn deposit.' }],
    structuredContent: { kind: 'earn_deposit', phase: 'form', opportunity: { yieldId: 'base-usdc-aave-v3-lending' } },
  }
  const { instance, posted, restCalls } = harness({ uri: YIELD, rest: () => ({ ok: true, result: earnCard }) })
  instance.handle({ jsonrpc: '2.0', id: 11, method: 'tools/call',
    params: { name: 'show_earn_deposit_card', arguments: { yield_id: 'base-usdc-aave-v3-lending' } } })
  await settle()
  // Through the yield card's own record: no new card, no Earn view.
  assert.deepEqual(restCalls, [[`/cards/${'c'.repeat(32)}/call`,
    { tool: 'show_earn_deposit_card', arguments: { yield_id: 'base-usdc-aave-v3-lending' } }]])
  assert.deepEqual(posted, [{ jsonrpc: '2.0', id: 11, result: earnCard }])
})

test('execute_intent from the yield card opens the confirmation; only its Confirm result goes back', async () => {
  const preview = { confirm_id: 'cf-3', tool: 'execute_intent', title: 'Confirm on-chain', description: 'Run this earn deposit…', rows: [], expires_in_seconds: 100 }
  const executed = { ok: true, tool: 'execute_intent', result: { content: [{ type: 'text', text: '{"success":true}' }] } }
  const seen = []
  const { instance, posted, restCalls } = harness({
    uri: YIELD,
    rest: () => ({ ok: true, confirm: preview }),
    confirm: async (shown) => {
      seen.push(shown)
      return executed
    },
  })
  instance.handle({ jsonrpc: '2.0', id: 12, method: 'tools/call', params: { name: 'execute_intent', arguments: { intent_id: INTENT } } })
  await settle()
  assert.deepEqual(restCalls.map(([path]) => path), [`/cards/${'c'.repeat(32)}/call`])
  assert.deepEqual(seen, [preview])
  assert.deepEqual(posted, [{ jsonrpc: '2.0', id: 12, result: executed.result }])
})

test('execute_intent opens the confirmation; only its Confirm result goes back', async () => {
  const preview = { confirm_id: 'cf-1', tool: 'execute_intent', title: 'Confirm on-chain', description: 'Bridge…', rows: [], expires_in_seconds: 100 }
  const executed = { ok: true, tool: 'execute_intent', result: { content: [{ type: 'text', text: '{"success":true}' }] } }
  const seen = []
  const { instance, posted, restCalls } = harness({
    uri: QUOTE,
    rest: () => ({ ok: true, confirm: preview }),
    confirm: async (shown) => {
      seen.push(shown)
      return executed // what the sheet's Confirm button got from /execute
    },
  })
  instance.handle({ jsonrpc: '2.0', id: 9, method: 'tools/call', params: { name: 'execute_intent', arguments: { intent_id: INTENT } } })
  await settle()
  // The bridge asked for the confirmation; it never called /execute itself.
  assert.deepEqual(restCalls.map(([path]) => path), [`/cards/${'c'.repeat(32)}/call`])
  assert.deepEqual(seen, [preview])
  assert.deepEqual(posted, [{ jsonrpc: '2.0', id: 9, result: executed.result }])
})

test('cancelling the confirmation tells the card nothing was sent', async () => {
  const { instance, posted } = harness({
    uri: QUOTE,
    rest: () => ({ ok: true, confirm: { confirm_id: 'cf-2', tool: 'execute_intent' } }),
    confirm: async () => null,
  })
  instance.handle({ jsonrpc: '2.0', id: 4, method: 'tools/call', params: { name: 'execute_intent', arguments: { intent_id: INTENT } } })
  await settle()
  assert.deepEqual(posted[0].result, { isError: true, content: [{ type: 'text', text: bridge.CARD_CANCELLED_TEXT }] })
  assert.equal(bridge.CARD_CANCELLED_TEXT, 'Cancelled in Hermes. Nothing was sent.')
})

test('a backend refusal reaches the card as a tool error', async () => {
  const { instance, posted } = harness({ uri: QUOTE, rest: () => ({ ok: false, error: 'This card did not prepare that trade. Nothing was sent.' }) })
  instance.handle({ jsonrpc: '2.0', id: 5, method: 'tools/call', params: { name: 'execute_intent', arguments: { intent_id: INTENT } } })
  await settle()
  assert.equal(posted[0].result.isError, true)
  assert.match(posted[0].result.content[0].text, /did not prepare/)
})

test('relayed calls are rate limited per frame', async () => {
  let now = 0
  const limiter = bridge.createRateLimiter(2, 60000, () => now)
  const { instance, posted, restCalls } = harness({ limiter })
  for (const id of [1, 2, 3]) instance.handle({ jsonrpc: '2.0', id, method: 'tools/call', params: { name: 'whoami' } })
  await settle()
  assert.equal(restCalls.length, 2)
  assert.equal(posted.find((m) => m.id === 3).error.code, -32000)
  now = 60000
  assert.equal(limiter(), true)
})

test('ui/open-link opens https only', () => {
  const { instance, posted, opened } = harness()
  instance.handle({ jsonrpc: '2.0', id: 1, method: 'ui/open-link', params: { url: 'https://app.coinfello.com/portfolio' } })
  instance.handle({ jsonrpc: '2.0', id: 2, method: 'ui/open-link', params: { url: 'http://app.coinfello.com/' } })
  instance.handle({ jsonrpc: '2.0', id: 3, method: 'ui/open-link', params: { url: 'javascript:alert(1)' } })
  assert.deepEqual(opened, ['https://app.coinfello.com/portfolio'])
  assert.deepEqual(posted[0], { jsonrpc: '2.0', id: 1, result: {} })
  assert.equal(posted[1].result.isError, true)
  assert.equal(posted[2].result.isError, true)
})

test('unknown requests get -32601; unknown notifications are ignored', () => {
  const { instance, posted } = harness()
  instance.handle({ jsonrpc: '2.0', id: 1, method: 'ui/message', params: { role: 'user', content: [] } })
  instance.handle({ jsonrpc: '2.0', id: 2, method: 'ui/update-model-context', params: {} })
  instance.handle({ jsonrpc: '2.0', method: 'ui/notifications/something' })
  assert.deepEqual(posted.map((m) => m.error && m.error.code), [-32601, -32601])
})

test('theme changes go to the card; dispose tears it down and goes quiet', () => {
  const { instance, posted } = harness()
  instance.notifyContext({ theme: 'light' })
  instance.dispose()
  instance.handle({ jsonrpc: '2.0', id: 1, method: 'ui/initialize' })
  instance.notifyContext({ theme: 'dark' })
  assert.deepEqual(posted, [
    { jsonrpc: '2.0', method: 'ui/notifications/host-context-changed', params: { theme: 'light' } },
    { jsonrpc: '2.0', id: 'teardown-1', method: 'ui/resource-teardown', params: {} },
  ])
})

test('stripSecrets keeps coin symbols and drops credentials and prototype keys', () => {
  const parsed = JSON.parse('{"token":"USDC","Session-Token":"a","list":[{"privateKey":"k","amount":"1"}],"__proto__":{"x":1}}')
  assert.deepEqual(bridge.stripSecrets(parsed), { token: 'USDC', list: [{ amount: '1' }] })
})

test('isHttpsUrl', () => {
  assert.equal(bridge.isHttpsUrl('https://x.test/a'), true)
  assert.equal(bridge.isHttpsUrl('http://x.test/a'), false)
  assert.equal(bridge.isHttpsUrl('data:text/html,hi'), false)
  assert.equal(bridge.isHttpsUrl(42), false)
})
