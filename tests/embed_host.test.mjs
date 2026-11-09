// The pane's host for CoinFello's embedded views (desktop/plugin.js, between
// the embed-host markers): swap and Earn share it, so both are run here with
// fakes for the frame window, the clock and ctx.rest.
//   node --test tests/embed_host.test.mjs
// (tests/test_earn.py runs this from pytest when node is installed.)

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const start = source.indexOf('/* embed-host:start */')
const end = source.indexOf('/* embed-host:end */')
assert.ok(start > 0 && end > start, 'embed-host markers missing from desktop/plugin.js')

const EXPORTS = [
  'EMBEDS', 'EMBED_HEIGHT_MIN', 'EMBED_HEIGHT_MAX', 'EMBED_REFRESH_GAP_MS', 'EMBED_CHECK_TEXT',
  'embedFrameSrc', 'clampEmbedHeight', 'createEmbedHost', 'swapOutcome', 'earnOutcome',
]
const host = new Function(`${source.slice(start, end)}\nreturn { ${EXPORTS.join(', ')} }`)()

const HASH = `0x${'ab'.repeat(32)}`

function harness({ kind = 'swap', mint } = {}) {
  const frame = { name: 'own frame' }
  const posted = []
  const errors = []
  const sizes = []
  const results = []
  const mints = []
  let clock = 1_000_000
  const instance = host.createEmbedHost({
    embed: host.EMBEDS[kind],
    nonce: 'nonce-1',
    frameWindow: () => frame,
    post: (target, message) => posted.push([target, message]),
    mint: async () => {
      mints.push(clock)
      return mint ? mint() : { ok: true, token: `cfemb_${mints.length}` }
    },
    now: () => clock,
    onError: (text, minted) => errors.push([text, minted]),
    onResize: (height) => sizes.push(height),
    onResult: (message) => results.push(message),
  })
  const send = (data, source = frame) => instance.handle({ source, data })
  return { instance, frame, posted, errors, sizes, results, mints, send, tick: (ms) => { clock += ms } }
}

// -- the frame URL -------------------------------------------------------------------

test('builds the frame URL with the theme first and the preselect after it', () => {
  const app = 'https://app.coinfello.test/'
  assert.equal(host.embedFrameSrc({ appUrl: app, path: '/embed/swap', theme: 'dark' }),
    'https://app.coinfello.test/embed/swap?theme=dark')
  assert.equal(host.embedFrameSrc({ appUrl: 'https://app.coinfello.test//', path: '/embed/earn', theme: 'light', query: 'token=USDC&chain_id=8453' }),
    'https://app.coinfello.test/embed/earn?theme=light&token=USDC&chain_id=8453')
  // Anything but 'dark' is light; an empty query adds nothing.
  assert.equal(host.embedFrameSrc({ appUrl: app, path: '/embed/earn', theme: 'sepia', query: '' }),
    'https://app.coinfello.test/embed/earn?theme=light')
})

test('swap keeps its path, result message and wording', () => {
  const swap = host.EMBEDS.swap
  assert.equal(swap.path, '/embed/swap')
  assert.equal(swap.resultType, 'coinfello:swap-result')
  assert.equal(swap.sessionEnded, 'Your CoinFello session ended. Sign in again, then reopen Swap.')
  assert.equal(swap.reloaded, 'The swap view reloaded. Reopen it to continue.')
  assert.equal(host.EMBEDS.earn.path, '/embed/earn')
  assert.equal(host.EMBEDS.earn.resultType, 'coinfello:earn-result')
  assert.equal(host.EMBEDS.earn.scope, 'earn')
})

// -- the handshake -----------------------------------------------------------------------

for (const kind of ['swap', 'earn']) {
  test(`${kind}: the first ready gets a token with the nonce, sent to the frame that asked`, async () => {
    const h = harness({ kind })
    assert.equal(await h.send({ type: 'coinfello:embed-ready', version: 1 }), true)
    assert.equal(h.posted.length, 1)
    const [target, message] = h.posted[0]
    assert.equal(target, h.frame)
    assert.deepEqual(message, { type: 'coinfello:embed-token', token: 'cfemb_1', nonce: 'nonce-1' })
  })
}

test('messages from any other window are ignored', async () => {
  const h = harness()
  assert.equal(await h.send({ type: 'coinfello:embed-ready' }, { name: 'stranger' }), false)
  assert.equal(await h.send({ type: 'coinfello:embed-ready' }, null), false)
  assert.equal(await h.send({ type: 'coinfello:swap-result', status: 'success' }, { name: 'stranger' }), false)
  assert.deepEqual([h.mints, h.posted, h.results], [[], [], []])
})

test('nothing is accepted before the frame exists', async () => {
  const posted = []
  const instance = host.createEmbedHost({
    embed: host.EMBEDS.earn, nonce: 'n', frameWindow: () => null,
    post: (...args) => posted.push(args), mint: async () => ({ ok: true, token: 't' }),
    onError: () => {}, onResize: () => {}, onResult: () => {},
  })
  assert.equal(await instance.handle({ source: null, data: { type: 'coinfello:embed-ready' } }), false)
  assert.deepEqual(posted, [])
})

test('a refused mint says why and sends nothing', async () => {
  const refusal = { ok: false, needs_trading_access: true, error: 'This session is read-only.' }
  const h = harness({ kind: 'earn', mint: () => refusal })
  await h.send({ type: 'coinfello:embed-ready', version: 1 })
  assert.deepEqual(h.errors, [['This session is read-only.', refusal]])
  assert.deepEqual(h.posted, [])
})

test('a mint with no answer falls back to the embed\'s own words', async () => {
  const h = harness({ kind: 'earn', mint: () => null })
  await h.send({ type: 'coinfello:embed-ready' })
  assert.deepEqual(h.errors, [['Could not open Earn', null]])
})

test('an expired token is replaced for the same document', async () => {
  const h = harness()
  await h.send({ type: 'coinfello:embed-ready' })
  h.tick(15 * 60 * 1000)
  await h.send({ type: 'coinfello:embed-ready', nonce: 'nonce-1' })
  assert.equal(h.mints.length, 2)
  assert.equal(h.posted[1][1].token, 'cfemb_2')
})

test('a dead session cannot loop: a second request within a minute stops', async () => {
  const h = harness({ kind: 'earn' })
  await h.send({ type: 'coinfello:embed-ready' })
  h.tick(host.EMBED_REFRESH_GAP_MS - 1)
  await h.send({ type: 'coinfello:embed-ready', nonce: 'nonce-1' })
  assert.equal(h.mints.length, 1)
  assert.deepEqual(h.errors, [[host.EMBEDS.earn.sessionEnded, null]])
})

test('a document that never saw the nonce gets no token', async () => {
  const h = harness()
  await h.send({ type: 'coinfello:embed-ready' })
  h.tick(10 * 60 * 1000)
  await h.send({ type: 'coinfello:embed-ready', nonce: 'guessed' })
  await h.send({ type: 'coinfello:embed-ready' })
  assert.equal(h.mints.length, 1)
  assert.deepEqual(h.errors.map(([text]) => text), [host.EMBEDS.swap.reloaded, host.EMBEDS.swap.reloaded])
})

test('resizes are clamped and nonsense is ignored', async () => {
  const h = harness()
  for (const height of [10, 700, 99999, 0, -5, 'abc']) await h.send({ type: 'coinfello:embed-resize', height })
  assert.deepEqual(h.sizes, [host.EMBED_HEIGHT_MIN, 700, host.EMBED_HEIGHT_MAX])
})

test('each embed takes only its own result message', async () => {
  const swap = harness({ kind: 'swap' })
  await swap.send({ type: 'coinfello:earn-result', status: 'success' })
  await swap.send({ type: 'coinfello:swap-result', status: 'success' })
  assert.deepEqual(swap.results, [{ type: 'coinfello:swap-result', status: 'success' }])
  const earn = harness({ kind: 'earn' })
  await earn.send({ type: 'coinfello:swap-result', status: 'success' })
  await earn.send({ type: 'coinfello:earn-result', status: 'failed' })
  assert.deepEqual(earn.results, [{ type: 'coinfello:earn-result', status: 'failed' }])
})

test('a message that is not an object is ignored', async () => {
  const h = harness()
  await h.send('coinfello:embed-ready')
  await h.send(null)
  assert.deepEqual([h.mints, h.errors], [[], []])
})

// -- outcomes ---------------------------------------------------------------------------

test('swap still shows only a success', () => {
  assert.equal(host.swapOutcome({ status: 'success' }).title, 'Swap submitted.')
  for (const status of ['failed', 'unknown', 'cancelled']) assert.equal(host.swapOutcome({ status }), null)
})

test('an earn success links its transaction', () => {
  assert.deepEqual(host.earnOutcome({ status: 'success', transactionHash: HASH }),
    { tone: 'good', title: 'Deposit submitted.', detail: '', explorerUrl: `https://blockscan.com/tx/${HASH}` })
  assert.equal(host.earnOutcome({ status: 'success' }).explorerUrl, '')
})

test('"nothing was sent" only for a cancel or failure with no transaction', () => {
  const cancelled = host.earnOutcome({ status: 'cancelled' })
  assert.equal(cancelled.detail, 'Nothing was sent.')
  const failed = host.earnOutcome({ status: 'failed', error: 'Not enough USDC.' })
  assert.deepEqual([failed.tone, failed.detail], ['bad', 'Not enough USDC. Nothing was sent.'])
})

test('anything uncertain asks to check, never to retry', () => {
  const uncertain = [
    { status: 'unknown', transactionHash: HASH },
    { status: 'unknown' },
    { status: 'success', outcomeUnknown: true, transactionHash: HASH },
    { status: 'failed', transactionHash: HASH, error: 'Receipt timed out.' },
    { status: 'failed', outcomeUnknown: true },
    { status: 'cancelled', transactionHash: HASH },
    { status: 'something-new' },
    {},
  ]
  for (const message of uncertain) {
    const outcome = host.earnOutcome(message)
    assert.match(outcome.title, /Check status/, JSON.stringify(message))
    assert.ok(outcome.detail.endsWith(host.EMBED_CHECK_TEXT), JSON.stringify(message))
    assert.ok(!/Nothing was sent/.test(outcome.detail), JSON.stringify(message))
  }
  assert.equal(host.earnOutcome(uncertain[0]).explorerUrl, `https://blockscan.com/tx/${HASH}`)
  assert.equal(host.earnOutcome(uncertain[3]).detail, `Receipt timed out. ${host.EMBED_CHECK_TEXT}`)
})

test('only a real transaction hash becomes a link, and errors are bounded', () => {
  for (const transactionHash of ['javascript:alert(1)', '0x123', `${HASH}/../x`, 42]) {
    assert.equal(host.earnOutcome({ status: 'success', transactionHash }).explorerUrl, '')
  }
  assert.equal(host.earnOutcome({ status: 'failed', error: 'x'.repeat(1000) }).detail.length, 300 + ' Nothing was sent.'.length)
  assert.equal(host.earnOutcome(null), null)
})
