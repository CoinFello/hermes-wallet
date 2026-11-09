// The pane's amount normalizer (desktop/plugin.js, between the amount
// markers), against the table coinfello_core.normalize_amount also passes.
//   node --test tests/amount.test.mjs
// (tests/test_amounts.py runs this from pytest when node is installed.)

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const start = source.indexOf('/* amount:start */')
const end = source.indexOf('/* amount:end */')
assert.ok(start > 0 && end > start, 'amount markers missing from desktop/plugin.js')

const { normalizeAmount } = new Function(`${source.slice(start, end)}\nreturn { normalizeAmount }`)()
const cases = JSON.parse(readFileSync(new URL('./amount_cases.json', import.meta.url), 'utf8'))

test('normalizes what the server would refuse but means a plain amount', () => {
  for (const [input, expected] of cases.valid) {
    assert.deepEqual(normalizeAmount(input), { amount: expected, error: '' }, JSON.stringify(input))
  }
})

test('refuses anything else with a plain message', () => {
  for (const [input, message] of cases.invalid) {
    assert.deepEqual(normalizeAmount(input), { amount: '', error: message }, JSON.stringify(input))
  }
})

test('treats a missing value as empty', () => {
  assert.equal(normalizeAmount(undefined).error, 'Enter an amount like 0.001')
  assert.equal(normalizeAmount(null).error, 'Enter an amount like 0.001')
})

test('keeps every digit (no float rounding)', () => {
  assert.equal(normalizeAmount('0.1000000000000000055511151231257827').amount, '0.1000000000000000055511151231257827')
  assert.equal(normalizeAmount('9007199254740993').amount, '9007199254740993')
})
