/**
 * CoinFello for Hermes — desktop half (pane + statusbar chip).
 *
 * Sign-in is browser-first: one approval on app.coinfello.com, no email code
 * to relay (servers that predate it fall back to the email-code flow). Once
 * signed in, the pane is the minimal portfolio: the automations wallet with
 * copy + QR for funding, the total with its 24h move, and balances grouped
 * per network — the same rules as the CoinFello Portfolio view, applied in
 * the plugin backend (coinfello_portfolio.py). Deeper views open in
 * CoinFello itself.
 *
 * Swap and Earn host CoinFello's own UI (coinfello-web /embed/swap and
 * /embed/earn) in a sandboxed frame; see "embedded views" below. The agent's
 * coinfello_show_card(card="earn_deposit") opens the Earn view.
 *
 * Cards the agent shows (coinfello_show_card) appear at the top of the pane:
 * CoinFello's MCP App cards, each in a sandboxed frame, with the MCP Apps
 * bridge answered here (see "MCP App cards" below).
 *
 * All data flows through the plugin's Python backend at
 * /api/plugins/coinfello — this file never sees the session token.
 */

import {
  Button,
  Codicon,
  CopyButton,
  Input,
  SandboxedFrame,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  StatusDot,
  cn,
  useQuery,
  useQueryClient,
} from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import { Fragment, jsx, jsxs } from 'react/jsx-runtime'

const ID = 'coinfello'

const muted = 'text-(--ui-text-tertiary)'
const row = 'flex items-center justify-between gap-2'
const up = 'text-emerald-500'
const down = 'text-destructive'

const shortAddr = (address) =>
  address && address.length > 14 ? `${address.slice(0, 6)}…${address.slice(-4)}` : address || ''

const shortDate = (iso) => {
  const date = iso ? new Date(iso) : null
  return date && !Number.isNaN(date.getTime())
    ? date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : ''
}

function errorOf(result, fallback) {
  return (result && result.error) || fallback
}

// -- small pieces --------------------------------------------------------------

function TokenLogo({ token }) {
  // TokenIcon.tsx's chain: provider logo -> MetaMask icon API -> generic.
  const sources = [token.logo_url, token.fallback_logo_url].filter(Boolean)
  const [index, setIndex] = useState(0)
  if (index >= sources.length) {
    return jsx('div', {
      className: 'flex size-5 shrink-0 items-center justify-center rounded-full bg-(--ui-stroke-secondary) text-[0.5rem] font-medium',
      children: (token.symbol || '?').slice(0, 3),
    })
  }
  return jsx('img', {
    src: sources[index],
    alt: '',
    className: 'size-5 shrink-0 rounded-full',
    onError: () => setIndex(index + 1),
  })
}

function ExternalButton({ ctx, url, label, icon }) {
  return jsx(Button, {
    variant: 'outline',
    size: 'sm',
    className: 'flex-1',
    onClick: () => ctx.os.openExternal(url),
    children: jsxs(Fragment, {
      children: [jsx(Codicon, { name: icon || 'link-external', size: 12 }), label],
    }),
  })
}

// -- signed-in: wallet + portfolio --------------------------------------------

function WalletCard({ ctx }) {
  const [showQr, setShowQr] = useState(false)
  const wallet = useQuery({
    queryKey: ['coinfello', 'wallet'],
    queryFn: () => ctx.rest('/wallet'),
    staleTime: 5 * 60 * 1000,
  })
  const data = wallet.data
  if (!data || data.ok === false) {
    return jsx('div', { className: cn('text-xs', muted), children: wallet.isLoading ? 'Loading wallet…' : errorOf(data, 'Wallet unavailable') })
  }
  return jsxs('div', {
    className: 'flex flex-col gap-2 rounded-md border border-(--ui-stroke-secondary) p-2',
    children: [
      jsxs('div', {
        className: row,
        children: [
          jsxs('div', {
            className: 'min-w-0',
            children: [
              jsx('div', { className: cn('text-[0.6875rem]', muted), children: 'Automations wallet' }),
              jsx('div', { className: 'font-mono text-xs', title: data.address, children: shortAddr(data.address) }),
            ],
          }),
          jsxs('div', {
            className: 'flex items-center gap-1',
            children: [
              jsx(CopyButton, { text: data.address, appearance: 'icon', label: 'Copy address' }),
              jsx(Button, {
                variant: showQr ? 'secondary' : 'ghost',
                size: 'sm',
                onClick: () => setShowQr(!showQr),
                children: 'QR',
              }),
            ],
          }),
        ],
      }),
      showQr
        ? jsxs('div', {
            className: 'flex flex-col items-center gap-2 pt-1',
            children: [
              data.qr_svg
                ? jsx('div', {
                    // Dark-on-light regardless of theme: scanners need the contrast.
                    className: 'rounded-md bg-white p-2',
                    children: jsx('img', { src: data.qr_svg, alt: 'Wallet address QR code', className: 'size-40' }),
                  })
                : jsx('div', { className: cn('text-xs', muted), children: 'QR unavailable (run hermes pm repair to install segno).' }),
              jsx('div', { className: 'w-full break-all text-center font-mono text-[0.6875rem]', children: data.address }),
              jsx('div', {
                className: cn('text-center text-[0.6875rem]', muted),
                children: 'Send tokens on a network CoinFello supports. This address is the same on every EVM network.',
              }),
            ],
          })
        : null,
    ],
  })
}

function Portfolio({ ctx, onSend, onSwap, onEarn }) {
  const portfolio = useQuery({
    queryKey: ['coinfello', 'portfolio'],
    queryFn: () => ctx.rest('/portfolio'),
    refetchInterval: 60 * 1000,
  })
  const data = portfolio.data
  if (portfolio.isLoading) return jsx('div', { className: cn('text-xs', muted), children: 'Loading balances…' })
  if (!data || data.ok === false) {
    return jsx('div', { className: cn('text-xs', muted), children: errorOf(data, 'Could not load balances.') })
  }
  return jsxs(Fragment, {
    children: [
      jsxs('div', {
        className: 'flex flex-col',
        children: [
          jsx('div', { className: 'text-lg font-semibold', children: data.total_text }),
          jsxs('div', {
            className: cn('text-xs', data.change_positive ? up : down),
            children: [data.change_24h_text, jsx('span', { className: muted, children: ' 24h' })],
          }),
        ],
      }),
      jsxs('div', {
        className: 'flex gap-2',
        children: [
          jsx(Button, {
            size: 'sm',
            className: 'flex-1',
            disabled: !data.can_send,
            title: data.can_send ? undefined : data.can_trade === false ? 'Read-only session: enable trading first' : 'Sending from Hermes needs a CoinFello update',
            onClick: () => onSend(data),
            children: jsxs(Fragment, { children: [jsx(Codicon, { name: 'arrow-up', size: 12 }), 'Send'] }),
          }),
          jsx(Button, {
            size: 'sm',
            variant: 'secondary',
            className: 'flex-1',
            disabled: !data.can_swap,
            title: data.can_swap ? undefined : data.can_trade === false ? 'Read-only session: enable trading first' : 'Swapping from Hermes needs a CoinFello update',
            onClick: onSwap,
            children: jsxs(Fragment, { children: [jsx(Codicon, { name: 'arrow-swap', size: 12 }), 'Swap'] }),
          }),
          // Read-only sessions may browse: the server decides on deposits.
          data.earn_supported
            ? jsx(Button, {
                size: 'sm',
                variant: 'secondary',
                className: 'flex-1',
                onClick: onEarn,
                children: jsxs(Fragment, { children: [jsx(Codicon, { name: 'graph-line', size: 12 }), 'Earn'] }),
              })
            : null,
        ],
      }),
      data.earn_supported === false
        ? jsx('div', {
            className: cn('text-[0.6875rem]', muted),
            children: 'Earn opens here once CoinFello updates. Until then, ask the agent for yields to see them as a card.',
          })
        : null,
      data.networks.length === 0
        ? jsx('div', { className: cn('text-xs', muted), children: 'No tokens yet — fund the wallet above to get started.' })
        : jsx('div', {
            className: 'flex flex-col gap-3',
            children: data.networks.map((network) =>
              jsxs(
                'div',
                {
                  className: 'flex flex-col gap-1',
                  children: [
                    jsxs('div', {
                      className: cn(row, 'border-b border-(--ui-stroke-secondary) pb-1 text-[0.6875rem] font-medium', muted),
                      children: [jsx('span', { children: network.chain_name }), jsx('span', { children: network.subtotal_text })],
                    }),
                    ...network.tokens.map((token, index) =>
                      jsxs(
                        'div',
                        {
                          className: cn(row, 'text-xs'),
                          children: [
                            jsxs('div', {
                              className: 'flex min-w-0 items-center gap-2',
                              children: [
                                jsx(TokenLogo, { token }),
                                jsxs('div', {
                                  className: 'min-w-0',
                                  children: [
                                    jsx('div', { className: 'truncate font-medium', children: token.symbol }),
                                    jsx('div', { className: cn('truncate text-[0.6875rem]', muted), children: token.balance_text }),
                                  ],
                                }),
                              ],
                            }),
                            jsxs('div', {
                              className: 'shrink-0 text-right',
                              children: [
                                jsx('div', { children: token.value_text }),
                                token.change_text
                                  ? jsx('div', {
                                      className: cn('text-[0.6875rem]', token.change_positive ? up : down),
                                      children: token.change_text,
                                    })
                                  : null,
                              ],
                            }),
                          ],
                        },
                        `${network.chain_id}-${token.symbol}-${index}`,
                      ),
                    ),
                  ],
                },
                String(network.chain_id),
              ),
            ),
          }),
      data.hidden_count > 0 || data.truncated
        ? jsx('div', {
            className: cn('text-[0.6875rem]', muted),
            children: [
              data.hidden_count > 0 ? `${data.hidden_count} unpriced token${data.hidden_count === 1 ? '' : 's'} hidden.` : '',
              data.truncated ? ' Smallest balances not shown.' : '',
            ].join(' ').trim(),
          })
        : null,
      jsxs('div', {
        className: 'flex gap-2',
        children: [
          jsx(ExternalButton, { ctx, url: data.portfolio_url, label: 'Portfolio' }),
          jsx(ExternalButton, { ctx, url: data.strategies_url, label: 'Strategies' }),
        ],
      }),
    ],
  })
}

// -- send: form -> review (server-validated, single-use intent) -> result -------

const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/

/* amount:start */
// The server takes a plain decimal with a leading digit ("0.001", not
// ".001"). Same rules as coinfello_core.normalize_amount, which the backend
// applies again; tests/amount_cases.json holds the two to one table. String
// operations only: Number() would round away digits a token has.
const AMOUNT_RE = /^([0-9]*)(?:\.([0-9]*))?$/
const AMOUNT_HINT = 'Enter an amount like 0.001'
const AMOUNT_ZERO = 'Enter an amount greater than 0'

function normalizeAmount(value) {
  const match = AMOUNT_RE.exec(String(value == null ? '' : value).trim())
  if (!match || !(match[1] || match[2])) return { amount: '', error: AMOUNT_HINT }
  const whole = match[1].replace(/^0+/, '') || '0'
  const fraction = (match[2] || '').replace(/0+$/, '')
  if (whole === '0' && !fraction) return { amount: '', error: AMOUNT_ZERO }
  return { amount: fraction ? `${whole}.${fraction}` : whole, error: '' }
}
/* amount:end */

function heldTokens(portfolio) {
  const rows = []
  for (const network of portfolio.networks || []) {
    for (const token of network.tokens || []) {
      rows.push({ ...token, chain_name: network.chain_name, key: `${token.chain_id}:${token.address}` })
    }
  }
  return rows
}

function Row({ label, value, mono }) {
  return jsxs('div', {
    className: 'flex items-start justify-between gap-3 text-xs',
    children: [
      jsx('span', { className: cn('shrink-0', muted), children: label }),
      jsx('span', { className: cn('min-w-0 text-right', mono && 'break-all font-mono'), children: value }),
    ],
  })
}

function Countdown({ seconds, onExpired }) {
  const [left, setLeft] = useState(seconds)
  useEffect(() => {
    setLeft(seconds)
    const timer = setInterval(() => setLeft((value) => Math.max(0, value - 1)), 1000)
    return () => clearInterval(timer)
  }, [seconds])
  useEffect(() => {
    if (left === 0) onExpired()
  }, [left === 0])
  return jsx('span', { children: `${left}s` })
}

function SendFlow({ ctx, portfolio, onClose }) {
  const queryClient = useQueryClient()
  const tokens = heldTokens(portfolio)
  const [tokenKey, setTokenKey] = useState(tokens[0] ? tokens[0].key : '')
  const [amount, setAmount] = useState('')
  const [recipient, setRecipient] = useState('')
  const [stage, setStage] = useState('form') // form -> review -> result
  const [prepared, setPrepared] = useState(null)
  const [expired, setExpired] = useState(false)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const token = tokens.find((row) => row.key === tokenKey)

  const recipientValid = ADDRESS_RE.test(recipient.trim())
  const parsedAmount = normalizeAmount(amount)
  const canReview = !busy && token && !parsedAmount.error && recipientValid

  const review = async () => {
    if (!canReview) return
    setBusy(true)
    setError('')
    try {
      const response = await ctx.rest('/send/prepare', {
        method: 'POST',
        body: { chain_id: token.chain_id, token: token.address, amount: parsedAmount.amount, recipient: recipient.trim() },
      })
      if (!response || response.ok === false) setError(errorOf(response, 'Could not prepare the send'))
      else {
        setPrepared(response)
        setExpired(false)
        setStage('review')
      }
    } catch (exc) {
      setError(String(exc))
    } finally {
      setBusy(false)
    }
  }

  const confirm = async () => {
    setBusy(true)
    setError('')
    try {
      const response = await ctx.rest('/intent/execute', {
        method: 'POST',
        body: { intent_id: prepared.intent_id },
        timeoutMs: 180000,
      })
      setResult(response || { ok: false, error: 'No response' })
      setStage('result')
      queryClient.invalidateQueries({ queryKey: ['coinfello', 'portfolio'] })
    } catch (exc) {
      setResult({ ok: false, error: String(exc), unknown: true })
      setStage('result')
    } finally {
      setBusy(false)
    }
  }

  const header = jsxs('div', {
    className: row,
    children: [
      jsx('div', { className: 'font-medium', children: 'Send' }),
      jsx(Button, { variant: 'ghost', size: 'sm', onClick: onClose, children: 'Close' }),
    ],
  })

  if (stage === 'result') {
    const ok = result && result.ok
    const unknown = result && (result.unknown || result.outcome_unknown)
    return jsxs('div', {
      className: 'flex flex-col gap-2',
      children: [
        header,
        jsx('div', {
          className: cn('text-sm font-medium', ok ? up : unknown ? muted : down),
          children: ok ? 'Sent' : unknown ? 'Outcome unknown' : 'Not sent',
        }),
        ok
          ? jsx(Row, { label: 'Transaction', value: shortAddr(result.transaction_hash || ''), mono: true })
          : jsx('div', { className: 'text-xs', children: result && result.error }),
        unknown
          ? jsx('div', { className: cn('text-xs', muted), children: 'It may have gone through. Check the transaction or your CoinFello activity before trying again.' })
          : null,
        jsxs('div', {
          className: 'flex gap-2',
          children: [
            result && result.explorer_url
              ? jsx(Button, { size: 'sm', variant: 'outline', onClick: () => ctx.os.openExternal(result.explorer_url), children: 'View transaction' })
              : null,
            jsx(Button, { size: 'sm', onClick: onClose, children: 'Done' }),
          ],
        }),
      ],
    })
  }

  if (stage === 'review' && prepared) {
    const summary = prepared.summary || {}
    const symbol = (summary.token && summary.token.symbol) || ''
    const usd = summary.valueUsd != null ? ` (~$${Number(summary.valueUsd).toFixed(2)})` : ''
    return jsxs('div', {
      className: 'flex flex-col gap-2',
      children: [
        header,
        jsxs('div', {
          className: 'flex flex-col gap-1.5 rounded-md border border-(--ui-stroke-secondary) p-2',
          children: [
            jsx(Row, { label: 'Send', value: `${summary.amount} ${symbol}${usd}` }),
            jsx(Row, { label: 'Network', value: summary.chainName }),
            jsx(Row, { label: 'To', value: summary.recipient, mono: true }),
            jsx(Row, { label: 'From', value: 'Automations wallet' }),
          ],
        }),
        jsx('div', {
          className: cn('text-[0.6875rem]', muted),
          children: 'This sends immediately from your automations wallet. Check the address: transactions cannot be reversed.',
        }),
        expired
          ? jsx('div', { className: cn('text-xs', down), children: 'This confirmation expired. Review again to refresh it.' })
          : jsxs('div', {
              className: cn('text-[0.6875rem]', muted),
              children: ['Confirmation valid for ', jsx(Countdown, { seconds: prepared.expires_in_seconds || 120, onExpired: () => setExpired(true) })],
            }),
        jsxs('div', {
          className: 'flex gap-2',
          children: [
            expired
              ? jsx(Button, { size: 'sm', loading: busy, onClick: review, children: 'Review again' })
              : jsx(Button, { size: 'sm', loading: busy, onClick: confirm, children: 'Confirm send' }),
            jsx(Button, { size: 'sm', variant: 'ghost', disabled: busy, onClick: () => setStage('form'), children: 'Back' }),
          ],
        }),
        error ? jsx('div', { className: cn('text-xs', down), children: error }) : null,
      ],
    })
  }

  return jsxs('form', {
    className: 'flex flex-col gap-2',
    onSubmit: (event) => {
      event.preventDefault()
      review()
    },
    children: [
      header,
      tokens.length === 0
        ? jsx('div', { className: cn('text-xs', muted), children: 'Nothing to send yet: fund the wallet first.' })
        : jsxs(Select, {
            value: tokenKey,
            onValueChange: setTokenKey,
            children: [
              jsx(SelectTrigger, { className: 'w-full', children: jsx(SelectValue, { placeholder: 'Token' }) }),
              jsx(SelectContent, {
                children: tokens.map((row) =>
                  jsx(SelectItem, { value: row.key, children: `${row.symbol} · ${row.chain_name} · ${row.balance_text}` }, row.key),
                ),
              }),
            ],
          }),
      jsxs('div', {
        className: 'flex gap-2',
        children: [
          jsx(Input, { value: amount, inputMode: 'decimal', placeholder: '0.00', onChange: (e) => setAmount(e.target.value) }),
          jsx(Button, { type: 'button', size: 'sm', variant: 'outline', disabled: !token, onClick: () => token && setAmount(token.balance), children: 'Max' }),
        ],
      }),
      amount.trim() && parsedAmount.error
        ? jsx('div', { className: cn('text-[0.6875rem]', down), children: parsedAmount.error })
        : null,
      jsx(Input, { value: recipient, placeholder: 'Recipient address (0x…)', spellCheck: false, onChange: (e) => setRecipient(e.target.value) }),
      recipient && !recipientValid
        ? jsx('div', { className: cn('text-[0.6875rem]', down), children: 'Enter a full 0x address (42 characters).' })
        : null,
      jsx(Button, { type: 'submit', size: 'sm', loading: busy, disabled: !canReview, children: 'Review' }),
      error ? jsx('div', { className: cn('text-xs', down), children: error }) : null,
    ],
  })
}

// -- embedded views: CoinFello's real swap and Earn UIs (coinfello-web /embed/*) --
//
// One host for every embed: a sandboxed frame on <app><path>?theme=..., a
// short-lived token minted for its scope and handed over by postMessage, and
// its resize and result messages. The embeds speak the same protocol:
//   child  -> parent  {type: 'coinfello:embed-ready', version: 1}
//                     (again, with the nonce, when its token is rejected)
//   parent -> child   {type: 'coinfello:embed-token', token, nonce}
//   child  -> parent  {type: 'coinfello:embed-resize', height}
//   child  -> parent  {type: <the embed's resultType>, status, ...}
//
// Everything between the embed-host markers is plain JavaScript with no
// React or SDK import, so tests/embed_host.test.mjs can run it under node.

/* embed-host:start */
const EMBED_HEIGHT_MIN = 240
const EMBED_HEIGHT_MAX = 1200
const EMBED_HEIGHT_DEFAULT = 560
// Tokens live 15 minutes. A re-request within a minute of the last token
// means the session itself is gone (signed out, revoked).
const EMBED_REFRESH_GAP_MS = 60000
const EMBED_CHECK_TEXT = 'It may have gone through. Check the transaction or your CoinFello activity before trying again.'

const EMBEDS = {
  swap: {
    scope: 'swap',
    path: '/embed/swap',
    resultType: 'coinfello:swap-result',
    title: 'Swap',
    frameTitle: 'CoinFello swap',
    mintError: 'Could not open swap',
    sessionEnded: 'Your CoinFello session ended. Sign in again, then reopen Swap.',
    reloaded: 'The swap view reloaded. Reopen it to continue.',
  },
  earn: {
    scope: 'earn',
    path: '/embed/earn',
    resultType: 'coinfello:earn-result',
    title: 'Earn',
    frameTitle: 'CoinFello Earn',
    mintError: 'Could not open Earn',
    sessionEnded: 'Your CoinFello session ended. Sign in again, then reopen Earn.',
    reloaded: 'The Earn view reloaded. Reopen it to continue.',
  },
}

/** The frame's URL. `query` is the backend's already-escaped preselect
 * (coinfello_earn.frame_query); it always follows the theme. */
function embedFrameSrc({ appUrl, path, theme, query }) {
  const base = String(appUrl || '').replace(/\/+$/, '')
  const shade = theme === 'dark' ? 'dark' : 'light'
  return `${base}${path}?theme=${shade}${query ? `&${query}` : ''}`
}

function clampEmbedHeight(height) {
  return Math.min(EMBED_HEIGHT_MAX, Math.max(EMBED_HEIGHT_MIN, Number(height)))
}

const embedErrorOf = (result, fallback) => (result && result.error) || fallback

/**
 * The parent half of the embed protocol, for one mount.
 *   frameWindow()         the frame's contentWindow (or null)
 *   post(target, message) posts to `target`, the window that asked
 *   mint()         resolves to /embed-token's answer for this scope
 *   nonce          a per-mount secret, handed over with the first token
 */
function createEmbedHost({ embed, frameWindow, post, mint, nonce, now = () => Date.now(), onError, onResize, onResult }) {
  let tokenSent = false
  let lastSentAt = 0
  const sendToken = async (target) => {
    lastSentAt = now()
    const minted = await mint()
    if (!minted || minted.ok === false) {
      onError(embedErrorOf(minted, embed.mintError), minted || null)
      return
    }
    // A sandboxed (opaque-origin) frame can only be addressed with '*'; the
    // token is short-lived and good only for this embed's scope.
    post(target, { type: 'coinfello:embed-token', token: minted.token, nonce })
  }
  /** Handles one window message event; false when it was not ours. */
  const handle = async (event) => {
    const own = frameWindow()
    // Only our own frame speaks this protocol; everything else is ignored.
    if (!own || !event || event.source !== own) return false
    const message = (event.data && typeof event.data === 'object') ? event.data : {}
    if (message.type === 'coinfello:embed-ready') {
      if (!tokenSent) {
        tokenSent = true
        await sendToken(own)
      } else if (message.nonce === nonce) {
        // Minting again so soon would loop on a dead session: stop and say so.
        if (now() - lastSentAt < EMBED_REFRESH_GAP_MS) {
          onError(embed.sessionEnded, null)
          return true
        }
        await sendToken(own) // an expired token, from the same document
      } else {
        // A document the frame navigated to never saw the nonce: no token.
        onError(embed.reloaded, null)
      }
    } else if (message.type === 'coinfello:embed-resize' && Number(message.height) > 0) {
      onResize(clampEmbedHeight(message.height))
    } else if (message.type === embed.resultType) {
      onResult(message)
    }
    return true
  }
  return { handle }
}

const TX_HASH_RE = /^0x[0-9a-fA-F]{64}$/

/** Swap's result line, as it has always been: only a success is shown. */
function swapOutcome(message) {
  return message && message.status === 'success' ? { tone: 'good', title: 'Swap submitted.', detail: '', explorerUrl: '' } : null
}

/**
 * Earn's result. "Nothing was sent" only when the embed says it was
 * cancelled or failed AND names no transaction; anything else that is not a
 * clean success (unknown, outcomeUnknown, a failure with a hash, a status we
 * do not know) asks the person to check, never to retry.
 */
function earnOutcome(message) {
  if (!message || typeof message !== 'object') return null
  const hash = typeof message.transactionHash === 'string' && TX_HASH_RE.test(message.transactionHash) ? message.transactionHash : ''
  const explorerUrl = hash ? `https://blockscan.com/tx/${hash}` : ''
  const error = typeof message.error === 'string' ? message.error.trim().slice(0, 300) : ''
  const unknown = message.outcomeUnknown === true
  if (message.status === 'success' && !unknown) {
    return { tone: 'good', title: 'Deposit submitted.', detail: '', explorerUrl }
  }
  if (!hash && !unknown && message.status === 'cancelled') {
    return { tone: 'muted', title: 'Deposit cancelled.', detail: 'Nothing was sent.', explorerUrl: '' }
  }
  if (!hash && !unknown && message.status === 'failed') {
    return { tone: 'bad', title: 'Deposit failed.', detail: error ? `${error} Nothing was sent.` : 'Nothing was sent.', explorerUrl: '' }
  }
  return { tone: 'muted', title: 'Deposit status unknown. Check status.', detail: error ? `${error} ${EMBED_CHECK_TEXT}` : EMBED_CHECK_TEXT, explorerUrl }
}
/* embed-host:end */

const EMBED_OUTCOMES = { swap: swapOutcome, earn: earnOutcome }
const EARN_OPEN_EVENT = 'plugin.coinfello.earn.open'

function EmbedView({ ctx, appUrl, kind, query, onClose }) {
  const embed = EMBEDS[kind]
  const queryClient = useQueryClient()
  const frameRef = useRef(null)
  const [mount, setMount] = useState(0)
  const [height, setHeight] = useState(EMBED_HEIGHT_DEFAULT)
  const [outcome, setOutcome] = useState(null)
  const [error, setError] = useState('')

  const dark = document.documentElement.classList.contains('dark')
  const src = embedFrameSrc({ appUrl, path: embed.path, theme: dark ? 'dark' : 'light', query })

  useEffect(() => {
    const host = createEmbedHost({
      embed,
      // Per-mount secret: later token requests must echo it.
      nonce: crypto.randomUUID(),
      frameWindow: () => (frameRef.current ? frameRef.current.contentWindow : null),
      post: (target, message) => target.postMessage(message, '*'),
      // Swap's request is unchanged ({}: the backend defaults to swap).
      mint: () => ctx.rest('/embed-token', { method: 'POST', body: embed.scope === 'swap' ? {} : { scope: embed.scope } }),
      onError: setError,
      onResize: setHeight,
      onResult: (message) => {
        queryClient.invalidateQueries({ queryKey: ['coinfello', 'portfolio'] })
        const next = EMBED_OUTCOMES[kind](message)
        if (next) setOutcome(next)
      },
    })
    const onMessage = (event) => {
      host.handle(event)
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [mount, ctx, queryClient, kind])

  const toneClass = outcome ? (outcome.tone === 'good' ? up : outcome.tone === 'bad' ? down : muted) : ''

  return jsxs('div', {
    className: 'flex flex-col gap-2',
    children: [
      jsxs('div', {
        className: row,
        children: [
          jsx('div', { className: 'font-medium', children: embed.title }),
          jsx(Button, { variant: 'ghost', size: 'sm', onClick: onClose, children: 'Close' }),
        ],
      }),
      error
        ? jsxs('div', {
            className: 'flex items-center justify-between gap-2 text-xs',
            children: [
              jsx('span', { className: down, children: error }),
              jsx(Button, { size: 'sm', variant: 'outline', onClick: () => { setError(''); setMount(mount + 1) }, children: 'Reopen' }),
            ],
          })
        : null,
      outcome
        ? jsxs('div', {
            className: 'flex flex-col gap-1',
            children: [
              jsx('div', { className: cn('text-xs', toneClass), children: outcome.title }),
              outcome.detail ? jsx('div', { className: cn('text-[0.6875rem]', muted), children: outcome.detail }) : null,
              outcome.explorerUrl
                ? jsx('div', {
                    children: jsx(Button, { size: 'sm', variant: 'outline', onClick: () => ctx.os.openExternal(outcome.explorerUrl), children: 'View transaction' }),
                  })
                : null,
            ],
          })
        : null,
      jsx(SandboxedFrame, {
        key: mount,
        ref: frameRef,
        src,
        title: embed.frameTitle,
        sandbox: 'allow-scripts allow-forms',
        className: 'w-full rounded-md',
        style: { height },
      }),
    ],
  })
}

/**
 * The model's coinfello_show_card(card="earn_deposit") on desktop leaves an
 * "open Earn" request in the backend (coinfello_earn). Open it here once:
 * at the event, or at the next poll on Hermes builds without events.
 */
function useEarnRequests(ctx, enabled, open) {
  const queryClient = useQueryClient()
  const request = useQuery({
    queryKey: ['coinfello', 'earn-request'],
    queryFn: () => ctx.rest('/earn/request'),
    enabled,
    refetchInterval: 20 * 1000,
  })
  useEffect(() => {
    if (!enabled || typeof ctx.onEvent !== 'function') return undefined
    return ctx.onEvent(EARN_OPEN_EVENT, () => queryClient.invalidateQueries({ queryKey: ['coinfello', 'earn-request'] }))
  }, [ctx, queryClient, enabled])
  const pending = enabled && request.data && request.data.ok !== false ? request.data.request : null
  const pendingId = pending ? pending.id : ''
  useEffect(() => {
    if (!pending) return
    open(pending)
    ctx.rest(`/earn/request/${pending.id}/consume`, { method: 'POST', body: {} })
      .catch(() => {})
      .finally(() => queryClient.invalidateQueries({ queryKey: ['coinfello', 'earn-request'] }))
  }, [pendingId])
}

// -- signed-out: browser-first sign-in ------------------------------------------

// The approval page's steps, from the backend (coinfello_core.sign_in_steps),
// so the pane and the agent always describe the same order: open the page,
// sign in to CoinFello, type the code, choose access, approve.
function PendingSignIn({ ctx, status, refresh, upgrade }) {
  const [error, setError] = useState('')
  const code = status.pending_user_code
  const url = status.pending_approval_url
  const steps = status.sign_in_steps || []

  // While a browser approval is outstanding, poll for the finished sign-in.
  useEffect(() => {
    if (!status.pending_approval_id) return undefined
    const timer = setInterval(async () => {
      try {
        const result = await ctx.rest('/approval', { method: 'POST', body: {} })
        if (result && result.status === 'signed_in') refresh()
        else if (result && result.ok === false) {
          setError(errorOf(result, 'Sign-in failed'))
          await ctx.rest('/cancel-sign-in', { method: 'POST', body: {} })
          refresh()
        }
      } catch {
        // transient: keep polling
      }
    }, 5000)
    return () => clearInterval(timer)
  }, [status.pending_approval_id, ctx, refresh])

  const cancel = async () => {
    await ctx.rest('/cancel-sign-in', { method: 'POST', body: {} })
    refresh()
  }

  return jsxs('div', {
    className: 'flex flex-col gap-2 rounded-md border border-(--ui-stroke-secondary) p-2',
    children: [
      jsx('div', { className: 'text-xs font-medium', children: upgrade ? 'Enable trading' : 'Finish signing in' }),
      jsxs('ol', {
        className: cn('flex list-decimal flex-col gap-1 pl-4 text-xs', muted),
        children: [
          // Step 1 is "open the page": a button here instead of the URL.
          jsx('li', {
            children: jsx(Button, { size: 'sm', variant: 'outline', onClick: () => ctx.os.openExternal(url), children: 'Open the sign-in page' }),
          }),
          ...steps.slice(1).map((step, index) =>
            jsx('li', { children: step.startsWith('When the page asks for your agent') ? 'Then type this code when the page asks for it:' : step }, index),
          ),
        ],
      }),
      jsx('div', { className: 'rounded-md border border-(--ui-stroke-secondary) py-2 text-center font-mono text-lg tracking-widest select-all', children: code }),
      jsx('div', { className: cn('text-[0.6875rem]', muted), children: 'Only approve if the page says the request came from you, just now.' }),
      jsxs('div', {
        className: row,
        children: [
          jsx('span', { className: cn('animate-pulse text-xs', muted), children: 'Waiting for approval…' }),
          jsx(Button, { size: 'sm', variant: 'ghost', onClick: cancel, children: 'Cancel' }),
        ],
      }),
      error ? jsx('div', { className: cn('text-xs', down), children: error }) : null,
    ],
  })
}

// The session's access and its daily limit, adjustable in
// place: lowering applies at once; a raise (or read-only -> trading) opens a
// one-click approval on CoinFello in the browser. Same session either way.
const LIMIT_PRESETS = [50, 250, 1000]

const money = (value) => `$${Number(value).toLocaleString('en-US', { maximumFractionDigits: 2 })}`

function LimitEditor({ current, busy, onSave, onCancel }) {
  const preset = current != null && LIMIT_PRESETS.includes(current)
  const [choice, setChoice] = useState(current == null ? 'read' : preset ? String(current) : 'custom')
  const [custom, setCustom] = useState(current != null && !preset ? String(current) : '')
  const isCustom = choice === 'custom'
  const value = choice === 'read' ? null : isCustom ? Number(custom) : Number(choice)
  const valid = choice === 'read' || (Number.isFinite(value) && value > 0)
  const raising = value != null && (current == null || value > current)

  const option = (key, label) =>
    jsx(Button, {
      key,
      type: 'button',
      size: 'sm',
      variant: choice === key ? 'secondary' : 'outline',
      onClick: () => setChoice(key),
      children: label,
    })

  return jsxs('form', {
    className: 'flex flex-col gap-2',
    onSubmit: (event) => {
      event.preventDefault()
      if (valid && !busy) onSave(value)
    },
    children: [
      jsxs('div', {
        className: 'flex flex-wrap gap-1',
        children: [
          option('read', 'Read only'),
          ...LIMIT_PRESETS.map((amount) => option(String(amount), `${money(amount)}/day`)),
          option('custom', 'Custom'),
        ],
      }),
      isCustom
        ? jsx(Input, { value: custom, inputMode: 'decimal', autoFocus: true, placeholder: 'Daily limit in USD, e.g. 500', onChange: (e) => setCustom(e.target.value.replace(/[^0-9.]/g, '')) })
        : null,
      jsx('div', {
        className: cn('text-[0.6875rem]', muted),
        children: raising
          ? 'Raising opens a one-click approval on CoinFello in your browser. Same session, no new sign-in.'
          : 'Applies right away. Same session, no new sign-in.',
      }),
      jsxs('div', {
        className: 'flex gap-2',
        children: [
          jsx(Button, { type: 'submit', size: 'sm', loading: busy, disabled: !valid, children: raising ? 'Continue in browser' : 'Save' }),
          jsx(Button, { type: 'button', size: 'sm', variant: 'ghost', onClick: onCancel, children: 'Cancel' }),
        ],
      }),
    ],
  })
}

function AccessBadge({ ctx, status, refresh }) {
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const pendingUrl = status.pending_limit_change_url

  // A raise waiting on the human's browser approval: poll until it settles.
  useEffect(() => {
    if (!pendingUrl) return undefined
    const timer = setInterval(async () => {
      try {
        const result = await ctx.rest('/limit/poll', { method: 'POST', body: {} })
        if (!result || result.status === 'pending') return
        if (result.status === 'approved') setNotice(result.user_message || 'Limit updated.')
        else if (result.status === 'denied') setNotice('The change was denied. Your limit is unchanged.')
        else if (result.status === 'expired') setNotice('The approval link expired. Your limit is unchanged.')
        refresh()
      } catch {
        // transient: keep polling
      }
    }, 5000)
    return () => clearInterval(timer)
  }, [pendingUrl, ctx, refresh])

  if (!status.access || status.access === 'unknown') return null
  const current = status.access === 'trade' ? Number(status.daily_limit_usd) : null

  const save = async (limit) => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      // Servers without adjustable limits: the only way to trade is a new sign-in.
      if (!status.can_adjust_limit) {
        const result = await ctx.rest('/connect', { method: 'POST', body: {} })
        if (!result || result.ok === false) setError(errorOf(result, 'Could not start sign-in'))
        else ctx.os.openExternal(result.approval_url)
      } else {
        const result = await ctx.rest('/limit', { method: 'POST', body: { limit_usd: limit } })
        if (!result || result.ok === false) setError(errorOf(result, 'Could not change the limit'))
        else if (result.status === 'approval_required') ctx.os.openExternal(result.approval_url)
        else setNotice(result.user_message || 'Limit updated.')
      }
      setEditing(false)
      refresh()
    } catch (exc) {
      setError(String(exc))
    } finally {
      setBusy(false)
    }
  }

  const cancelPending = async () => {
    await ctx.rest('/limit/cancel', { method: 'POST', body: {} })
    refresh()
  }

  const summary =
    current == null
      ? jsxs('span', { className: 'flex items-center gap-1.5 text-xs font-medium', children: [jsx(StatusDot, { tone: 'warn' }), 'Read-only'] })
      : jsxs('span', { className: 'flex items-center gap-1.5 text-xs font-medium', children: [jsx(StatusDot, { tone: 'good' }), `Trading · up to ${money(current)}/day`] })

  return jsxs('div', {
    className: 'flex flex-col gap-1.5 rounded-md border border-(--ui-stroke-secondary) p-2',
    children: [
      jsxs('div', {
        className: row,
        children: [
          summary,
          !editing && !pendingUrl
            ? jsx(Button, {
                size: 'sm',
                variant: current == null ? 'default' : 'ghost',
                onClick: () => (status.can_adjust_limit ? setEditing(true) : save(null)),
                children: current == null ? 'Enable trading' : 'Change limit',
              })
            : null,
        ],
      }),
      current != null && status.remaining_today_usd != null && !editing
        ? jsx('div', { className: cn('text-[0.6875rem]', muted), children: `${money(status.remaining_today_usd)} left in the last 24 hours` })
        : null,
      current == null && !editing && !pendingUrl
        ? jsx('div', { className: cn('text-[0.6875rem]', muted), children: 'Balances and quotes work. To send or swap, set a daily limit.' })
        : null,
      editing ? jsx(LimitEditor, { current, busy, onSave: save, onCancel: () => setEditing(false) }) : null,
      pendingUrl
        ? jsxs('div', {
            className: 'flex flex-col gap-1.5',
            children: [
              jsx('div', {
                className: cn('text-xs', muted),
                children: `Approve ${status.pending_limit_requested == null ? 'read-only' : `${money(status.pending_limit_requested)}/day`} on CoinFello in your browser (sign in there first if it asks).`,
              }),
              jsxs('div', {
                className: row,
                children: [
                  jsx('span', { className: cn('animate-pulse text-xs', muted), children: 'Waiting for approval…' }),
                  jsxs('div', {
                    className: 'flex gap-1',
                    children: [
                      jsx(Button, { size: 'sm', variant: 'outline', onClick: () => ctx.os.openExternal(pendingUrl), children: 'Reopen' }),
                      jsx(Button, { size: 'sm', variant: 'ghost', onClick: cancelPending, children: 'Cancel' }),
                    ],
                  }),
                ],
              }),
            ],
          })
        : null,
      notice ? jsx('div', { className: cn('text-xs', up), children: notice }) : null,
      error ? jsx('div', { className: cn('text-xs', down), children: error }) : null,
    ],
  })
}

function BrowserSignIn({ ctx, status, refresh }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const pendingCode = status.pending_user_code

  const start = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await ctx.rest('/connect', { method: 'POST', body: {} })
      if (!result || result.ok === false) setError(errorOf(result, 'Could not start sign-in'))
      else {
        ctx.os.openExternal(result.approval_url)
        refresh()
      }
    } catch (exc) {
      setError(String(exc))
    } finally {
      setBusy(false)
    }
  }

  if (pendingCode) return jsx(PendingSignIn, { ctx, status, refresh, upgrade: false })

  const forgetAccount = async () => {
    await ctx.rest('/forget-account', { method: 'POST', body: {} })
    refresh()
  }

  return jsxs('div', {
    className: 'flex flex-col gap-2',
    children: [
      jsx('div', {
        className: cn('text-xs', muted),
        children:
          'Sign in once in your browser with your CoinFello email or phone. ' +
          'Approving lets Fello act on your automations wallet, the same permission as the Automation Wallet in the app (revocable there).',
      }),
      status.account_hint
        ? jsxs('div', {
            className: cn(row, 'text-[0.6875rem]', muted),
            children: [
              jsx('span', { children: `Signing in as ${status.account_hint}` }),
              jsx(Button, { size: 'sm', variant: 'ghost', onClick: forgetAccount, children: 'Use a different account' }),
            ],
          })
        : null,
      jsx('div', {
        className: cn('text-[0.6875rem]', muted),
        children: 'If your browser asks to connect or sign with a wallet like MetaMask, cancel it: that is a different account.',
      }),
      jsx(Button, { size: 'sm', loading: busy, onClick: start, children: 'Sign in with CoinFello' }),
      error ? jsx('div', { className: cn('text-xs', down), children: error }) : null,
    ],
  })
}

// Fallback for CoinFello servers deployed before browser sign-in.
function EmailSignIn({ ctx, status, refresh }) {
  const [stage, setStage] = useState('email')
  const [email, setEmail] = useState(status.email || '')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!status.pending_approval_id) return undefined
    const timer = setInterval(async () => {
      try {
        const result = await ctx.rest('/approval', { method: 'POST', body: {} })
        if (result && result.status === 'signed_in') refresh()
      } catch {
        // keep polling
      }
    }, 5000)
    return () => clearInterval(timer)
  }, [status.pending_approval_id, ctx, refresh])

  const run = async (path, body, onOk) => {
    setBusy(true)
    setError('')
    try {
      const result = await ctx.rest(path, { method: 'POST', body })
      if (!result || result.ok === false) setError(errorOf(result, 'Sign-in failed'))
      else onOk(result)
    } catch (exc) {
      setError(String(exc))
    } finally {
      setBusy(false)
    }
  }

  if (status.pending_approval_id) {
    return jsxs('div', {
      className: 'flex flex-col gap-2',
      children: [
        jsx('div', { className: cn('text-xs', muted), children: 'This wallet needs a one-time approval in your browser.' }),
        jsx(Button, { size: 'sm', onClick: () => ctx.os.openExternal(status.pending_approval_url), children: 'Open approval page' }),
        jsx('div', { className: cn('animate-pulse text-xs', muted), children: 'Waiting for approval…' }),
      ],
    })
  }

  const field =
    stage === 'email'
      ? jsx(Input, { value: email, type: 'email', autoFocus: true, placeholder: 'you@example.com', onChange: (e) => setEmail(e.target.value) })
      : jsx(Input, { value: code, inputMode: 'numeric', autoFocus: true, maxLength: 6, placeholder: '000000', onChange: (e) => setCode(e.target.value) })
  const canSubmit = !busy && (stage === 'email' ? !!email : code.length === 6)
  const submit = () => {
    if (!canSubmit) return
    if (stage === 'email') run('/connect', { email }, () => setStage('code'))
    else
      run('/verify', { email, code }, (result) => {
        if (result.status === 'approval_required') ctx.os.openExternal(result.approval_url)
        refresh()
      })
  }
  // A real <form>: Enter submits from either field, like any sign-in form.
  return jsxs('form', {
    className: 'flex flex-col gap-2',
    onSubmit: (event) => {
      event.preventDefault()
      submit()
    },
    children: [
      jsx('div', { className: cn('text-xs', muted), children: stage === 'email' ? 'Sign in with your CoinFello email.' : `Enter the 6-digit code sent to ${email}.` }),
      field,
      jsx(Button, {
        type: 'submit',
        size: 'sm',
        loading: busy,
        disabled: !canSubmit,
        children: stage === 'email' ? 'Send login code' : 'Verify',
      }),
      error ? jsx('div', { className: cn('text-xs', down), children: error }) : null,
    ],
  })
}

// -- MCP App cards: the host half of the MCP Apps bridge -------------------------
//
// The agent's coinfello_show_card stores a card record in the backend and
// emits plugin.coinfello.card.shown. The pane fetches /cards/{id} (a ready
// data: document with its CSP, the tool input and the raw tool result),
// mounts it in a SandboxedFrame (allow-scripts only: opaque origin, no
// storage, no popups) and answers the card's JSON-RPC.
//
// Everything between the card-bridge markers is plain JavaScript with no
// React or SDK import, so tests/card_bridge.test.mjs can run it under node.

/* card-bridge:start */
const CARD_PROTOCOL_VERSION = '2026-01-26'
const CARD_HEIGHT_MIN = 120
const CARD_HEIGHT_MAX = 1400
// Cards target ~480px; a card that overflows the ~300px pane is laid out
// wider (up to this) and scaled down to fit, never cut off.
const CARD_LAYOUT_MAX = 560
const CARD_CALLS_PER_MINUTE = 30
const CARD_CANCELLED_TEXT = 'Cancelled in Hermes. Nothing was sent.'

// The same tables as coinfello_cards.py (a test keeps them in sync): what a
// card may relay is checked here AND in the backend.
const CARD_ALWAYS_RELAYED = ['whoami']
const CARD_RETRYABLE_TOOLS = [
  'get_activity', 'get_balances', 'get_deposit_options', 'get_gas_price',
  'get_lp_positions', 'get_needs_attention', 'get_open_orders', 'get_positions',
  'get_prices', 'get_quote', 'get_transfer_status', 'get_yields',
  'prepare_send', 'prepare_swap', 'whoami',
]
const CARD_NEVER_RELAYED = [
  'sign_out', 'fello_chat', 'fello_job_status', 'start_browser_sign_in',
  'renew_session', 'create_embed_token', 'set_daily_limit', 'start_limit_change',
  'get_limit_change', 'sign_in_card_status', 'show_sign_in_card',
]
const CARD_TOOLS = {
  'ui://coinfello/portfolio-card.html': { tool: 'show_portfolio_card', relay: [], confirm: [] },
  'ui://coinfello/status-card.html': { tool: 'show_status_card', relay: [], confirm: [] },
  'ui://coinfello/quote-card.html': { tool: 'show_quote_card', relay: ['prepare_swap', 'prepare_send'], confirm: ['execute_intent'] },
  'ui://coinfello/automations-card.html': { tool: 'show_automations_card', relay: ['pause_automation'], confirm: ['cancel_automation'] },
  'ui://coinfello/needs-you-card.html': { tool: 'show_needs_you_card', relay: [], confirm: [] },
  'ui://coinfello/error-card.html': { tool: 'show_error_card', relay: [], confirm: [] },
  'ui://coinfello/fund-card.html': { tool: 'show_fund_card', relay: [], confirm: [] },
  'ui://coinfello/yield-card.html': { tool: 'show_yield_card', relay: [], confirm: [] },
  'ui://coinfello/lp-ranges-card.html': { tool: 'show_lp_ranges_card', relay: [], confirm: [] },
  'ui://coinfello/perp-card.html': { tool: 'show_perp_card', relay: [], confirm: [] },
  'ui://coinfello/send-card.html': { tool: 'show_send_card', relay: ['prepare_send'], confirm: ['execute_intent'] },
  'ui://coinfello/dca-card.html': { tool: 'show_dca_card', relay: ['prepare_dca'], confirm: ['execute_intent'] },
  'ui://coinfello/earn-deposit-card.html': { tool: 'show_earn_deposit_card', relay: ['prepare_earn_deposit'], confirm: ['execute_intent'] },
  'ui://coinfello/spend-limit-card.html': { tool: 'show_spend_limit_card', relay: ['prepare_spend_limit'], confirm: ['execute_intent'] },
}

/** 'relay', 'confirm' (the human decides first) or 'deny'. */
function cardToolDecision(uri, tool, structured) {
  const card = Object.prototype.hasOwnProperty.call(CARD_TOOLS, uri) ? CARD_TOOLS[uri] : null
  if (!card || typeof tool !== 'string' || !tool) return 'deny'
  if (CARD_NEVER_RELAYED.includes(tool) || tool.startsWith('privy_')) return 'deny'
  if (card.confirm.includes(tool)) return 'confirm'
  if (tool === card.tool || card.relay.includes(tool) || CARD_ALWAYS_RELAYED.includes(tool)) return 'relay'
  if (card.tool === 'show_error_card' && CARD_RETRYABLE_TOOLS.includes(tool) && structured && structured.retryTool === tool) {
    return 'relay'
  }
  return 'deny'
}

const CARD_SECRET_KEYS = new Set([
  'sessiontoken', 'embedtoken', 'accesstoken', 'refreshtoken', 'idtoken',
  'authtoken', 'authorization', 'bearer', 'apikey', 'secret', 'clientsecret',
  'credentials', 'mnemonic', 'seed', 'seedphrase', 'password', 'privatekey',
  'cookie',
])
const CARD_UNSAFE_KEYS = new Set(['__proto__', 'constructor', 'prototype'])

/** Drop credential-like keys at any depth (bare `token` is a coin symbol). */
function stripSecrets(value, depth = 0) {
  if (depth > 24) return null
  if (Array.isArray(value)) return value.map((item) => stripSecrets(item, depth + 1))
  if (!value || typeof value !== 'object') return value
  const out = {}
  for (const [key, item] of Object.entries(value)) {
    if (CARD_UNSAFE_KEYS.has(key) || CARD_SECRET_KEYS.has(key.toLowerCase().replace(/[_-]/g, ''))) continue
    out[key] = stripSecrets(item, depth + 1)
  }
  return out
}

function clampCardHeight(height) {
  const value = Number(height)
  if (!Number.isFinite(value)) return CARD_HEIGHT_MIN
  return Math.min(CARD_HEIGHT_MAX, Math.max(CARD_HEIGHT_MIN, Math.ceil(value)))
}

/**
 * Fit a card to the pane. It lays out at the pane's width; once it reports
 * content wider than that, it keeps that wider layout (latched, so the frame
 * does not flip between widths) and is scaled down to the pane.
 */
function fitCard({ container, reported, latched }) {
  const width = Math.max(1, Math.floor(Number(container) || 0))
  let layout = Number(latched) || 0
  if (!layout && Number(reported) > width + 1) layout = Math.min(Math.ceil(Number(reported)), CARD_LAYOUT_MAX)
  if (!layout || layout <= width) return { layoutWidth: width, scale: 1, latched: null }
  return { layoutWidth: layout, scale: width / layout, latched: layout }
}

function isHttpsUrl(url) {
  if (typeof url !== 'string') return false
  try {
    return new URL(url).protocol === 'https:'
  } catch {
    return false
  }
}

const rpcResult = (id, result) => ({ jsonrpc: '2.0', id, result })
const rpcError = (id, code, message) => ({ jsonrpc: '2.0', id, error: { code, message } })
const rpcNotification = (method, params) => ({ jsonrpc: '2.0', method, params })
const toolErrorResult = (text) => ({ isError: true, content: [{ type: 'text', text }] })

function cardHostContext({ theme, locale, width }) {
  return {
    theme: theme === 'dark' ? 'dark' : 'light',
    displayMode: 'inline',
    availableDisplayModes: ['inline'],
    platform: 'desktop',
    locale: locale || 'en-US',
    containerDimensions: { width: Math.floor(Number(width) || 0), maxHeight: CARD_HEIGHT_MAX },
  }
}

function cardInitializeResult(context) {
  return {
    protocolVersion: CARD_PROTOCOL_VERSION,
    hostInfo: { name: 'Hermes CoinFello plugin', version: '0.1.0' },
    hostCapabilities: { openLinks: {}, serverTools: {} },
    hostContext: cardHostContext(context),
  }
}

/** true while under `limit` calls in the last `windowMs`. */
function createRateLimiter(limit, windowMs, now = () => Date.now()) {
  const stamps = []
  return () => {
    const at = now()
    while (stamps.length && at - stamps[0] >= windowMs) stamps.shift()
    if (stamps.length >= limit) return false
    stamps.push(at)
    return true
  }
}

/**
 * The host side of one mounted card. `post` sends to the frame; `rest` is
 * ctx.rest; `confirm(preview)` resolves with the /execute response after the
 * human pressed Confirm, or null when they cancelled (the bridge itself never
 * calls /execute); `onSize` gets size-changed params; `context()` returns
 * { theme, locale, width }.
 */
function createCardBridge({ card, post, rest, confirm, openExternal, onSize, context, newId, limiter }) {
  const structured = (card.tool_result && card.tool_result.structuredContent) || {}
  const allow = limiter || createRateLimiter(CARD_CALLS_PER_MINUTE, 60000)
  const makeId = newId || (() => crypto.randomUUID())
  let disposed = false
  const send = (message) => {
    if (!disposed) post(message)
  }

  const relay = async (id, params) => {
    const name = params && typeof params.name === 'string' ? params.name : ''
    const raw = params && params.arguments
    const args = raw && typeof raw === 'object' && !Array.isArray(raw) ? stripSecrets(raw) : {}
    const decision = cardToolDecision(card.uri, name, structured)
    if (decision === 'deny') {
      send(rpcError(id, -32601, `${name || 'That tool'} is not available from this card in Hermes.`))
      return
    }
    if (!allow()) {
      send(rpcError(id, -32000, 'Too many requests from this card. Wait a minute.'))
      return
    }
    let response
    try {
      response = await rest(`/cards/${card.id}/call`, { method: 'POST', body: { tool: name, arguments: args } })
    } catch (exc) {
      send(rpcResult(id, toolErrorResult(String(exc))))
      return
    }
    if (!response || response.ok === false) {
      send(rpcResult(id, toolErrorResult((response && response.error) || 'Hermes could not complete that.')))
      return
    }
    if (decision !== 'confirm') {
      send(rpcResult(id, response.result || {}))
      return
    }
    if (!response.confirm) {
      send(rpcResult(id, toolErrorResult('Hermes could not prepare the confirmation. Nothing was sent.')))
      return
    }
    let executed = null
    try {
      executed = await confirm(response.confirm)
    } catch {
      executed = null
    }
    if (!executed) send(rpcResult(id, toolErrorResult(CARD_CANCELLED_TEXT)))
    else if (executed.ok === false) send(rpcResult(id, toolErrorResult(executed.error || 'Nothing was sent.')))
    else send(rpcResult(id, executed.result || {}))
  }

  const handle = (message) => {
    if (disposed || !message || typeof message !== 'object' || message.jsonrpc !== '2.0') return
    const { id, method, params } = message
    if (typeof method !== 'string') return // a response to our teardown: nothing waits on it
    if (id === undefined || id === null) {
      if (method === 'ui/notifications/initialized') {
        send(rpcNotification('ui/notifications/tool-input', card.tool_input || { arguments: {} }))
        send(rpcNotification('ui/notifications/tool-result', card.tool_result || {}))
      } else if (method === 'ui/notifications/size-changed') {
        onSize(params || {})
      }
      return
    }
    if (method === 'ui/initialize') send(rpcResult(id, cardInitializeResult(context())))
    else if (method === 'tools/call') relay(id, params)
    else if (method === 'ui/open-link') {
      const url = params && params.url
      if (isHttpsUrl(url)) {
        openExternal(url)
        send(rpcResult(id, {}))
      } else {
        send(rpcResult(id, toolErrorResult('Only https links open from a card.')))
      }
    } else if (method === 'ping') send(rpcResult(id, {}))
    else send(rpcError(id, -32601, `Hermes does not support ${method}.`))
  }

  return {
    handle,
    notifyContext: (partial) => send(rpcNotification('ui/notifications/host-context-changed', partial)),
    dispose: () => {
      send({ jsonrpc: '2.0', id: makeId(), method: 'ui/resource-teardown', params: {} })
      disposed = true
    },
  }
}
/* card-bridge:end */

const CARD_SHOWN_EVENT = 'plugin.coinfello.card.shown'

const currentTheme = () => (document.documentElement.classList.contains('dark') ? 'dark' : 'light')

function ConfirmSheet({ ctx, cardId, preview, onDone }) {
  const [busy, setBusy] = useState(false)
  const [expired, setExpired] = useState(!(preview.expires_in_seconds > 0))
  const isTrade = preview.tool === 'execute_intent'

  const confirmNow = async () => {
    setBusy(true)
    let response
    try {
      response = await ctx.rest(`/cards/${cardId}/execute`, {
        method: 'POST',
        body: { confirm_id: preview.confirm_id },
        timeoutMs: 180000,
      })
    } catch (exc) {
      response = {
        ok: false,
        error: isTrade
          ? `Hermes lost the answer (${String(exc)}). It may have gone through: check your CoinFello activity before trying again.`
          : String(exc),
      }
    }
    onDone(response || { ok: false, error: 'No response' })
  }

  return jsxs('div', {
    className: 'flex flex-col gap-2 rounded-md border border-(--ui-stroke-secondary) p-2',
    children: [
      jsx('div', { className: 'text-xs font-medium', children: preview.title }),
      jsx('div', { className: 'text-xs', children: preview.description }),
      (preview.rows || []).length
        ? jsx('div', {
            className: 'flex flex-col gap-1',
            children: preview.rows.map(([label, value], index) => jsx(Row, { label, value }, index)),
          })
        : null,
      isTrade
        ? jsx('div', {
            className: cn('text-[0.6875rem]', muted),
            children: 'This runs from your automations wallet right away. Transactions cannot be reversed.',
          })
        : null,
      expired
        ? jsx('div', { className: cn('text-xs', down), children: 'This confirmation expired. Ask the card for a fresh one.' })
        : jsxs('div', {
            className: cn('text-[0.6875rem]', muted),
            children: ['Valid for ', jsx(Countdown, { seconds: preview.expires_in_seconds, onExpired: () => setExpired(true) })],
          }),
      jsxs('div', {
        className: 'flex gap-2',
        children: [
          jsx(Button, { size: 'sm', loading: busy, disabled: expired, onClick: confirmNow, children: isTrade ? 'Confirm' : 'Cancel automation' }),
          jsx(Button, { size: 'sm', variant: 'ghost', disabled: busy, onClick: () => onDone(null), children: isTrade ? 'Cancel' : 'Keep it' }),
        ],
      }),
    ],
  })
}

function CardFrame({ ctx, card }) {
  const queryClient = useQueryClient()
  const frameRef = useRef(null)
  const boxRef = useRef(null)
  const [height, setHeight] = useState(240)
  const [reported, setReported] = useState(0)
  const [latched, setLatched] = useState(null)
  const [container, setContainer] = useState(0)
  const [confirmation, setConfirmation] = useState(null)

  // The pane can be resized: re-fit from scratch when its width changes
  // (not when the card's own height does).
  useEffect(() => {
    const box = boxRef.current
    if (!box) return undefined
    let width = -1
    const update = () => {
      if (box.clientWidth === width) return
      width = box.clientWidth
      setContainer(width)
      setLatched(null)
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(box)
    return () => observer.disconnect()
  }, [])

  const fit = fitCard({ container, reported, latched })
  useEffect(() => {
    if (fit.latched !== latched) setLatched(fit.latched)
  }, [fit.latched, latched])

  useEffect(() => {
    const post = (message) => {
      const frame = frameRef.current
      // A sandboxed (opaque-origin) frame can only be addressed with '*'.
      if (frame && frame.contentWindow) frame.contentWindow.postMessage(message, '*')
    }
    const bridge = createCardBridge({
      card,
      post,
      rest: (path, options) => ctx.rest(path, options),
      confirm: (preview) => new Promise((resolve) => setConfirmation({ preview, resolve })),
      openExternal: (url) => ctx.os.openExternal(url),
      onSize: (params) => {
        if (Number(params.height) > 0) setHeight(clampCardHeight(params.height))
        if (Number(params.width) > 0) setReported(Number(params.width))
      },
      context: () => ({
        theme: currentTheme(),
        locale: navigator.language,
        width: boxRef.current ? boxRef.current.clientWidth : 0,
      }),
    })
    const onMessage = (event) => {
      const frame = frameRef.current
      // Only this card's own frame speaks to this bridge.
      if (!frame || event.source !== frame.contentWindow) return
      bridge.handle(event.data)
    }
    window.addEventListener('message', onMessage)
    let theme = currentTheme()
    const observer = new MutationObserver(() => {
      const next = currentTheme()
      if (next !== theme) {
        theme = next
        bridge.notifyContext({ theme: next })
      }
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => {
      window.removeEventListener('message', onMessage)
      observer.disconnect()
      bridge.dispose()
      setConfirmation((open) => {
        if (open) open.resolve(null)
        return null
      })
    }
  }, [card.id, ctx])

  const finish = (response) => {
    if (!confirmation) return
    confirmation.resolve(response)
    setConfirmation(null)
    if (response && response.ok !== false) queryClient.invalidateQueries({ queryKey: ['coinfello', 'portfolio'] })
  }

  return jsxs('div', {
    className: 'flex flex-col gap-2',
    children: [
      confirmation ? jsx(ConfirmSheet, { ctx, cardId: card.id, preview: confirmation.preview, onDone: finish }) : null,
      jsx('div', {
        ref: boxRef,
        className: 'relative w-full overflow-hidden',
        style: { height: Math.ceil(height * fit.scale) },
        children: container
          ? jsx(SandboxedFrame, {
              ref: frameRef,
              src: card.src,
              title: `CoinFello ${card.title || 'card'}`,
              sandbox: 'allow-scripts',
              className: 'block',
              style: {
                width: fit.layoutWidth,
                height,
                transform: fit.scale === 1 ? undefined : `scale(${fit.scale})`,
                transformOrigin: 'top left',
              },
            })
          : null,
      }),
    ],
  })
}

function CardSlot({ ctx, summary, onDismiss }) {
  // Outside the ['coinfello'] prefix: the pane's own refreshes must not
  // reload a mounted card.
  const cardDoc = useQuery({
    queryKey: ['coinfello-card', summary.id],
    queryFn: () => ctx.rest(`/cards/${summary.id}?theme=${currentTheme()}`),
    staleTime: Infinity,
  })
  const data = cardDoc.data
  return jsxs('div', {
    className: 'flex flex-col gap-1',
    children: [
      jsxs('div', {
        className: cn(row, 'text-[0.6875rem]', muted),
        children: [
          jsx('span', { className: 'min-w-0 truncate font-medium', children: summary.title || 'Card' }),
          jsx(Button, { variant: 'ghost', size: 'sm', title: 'Close card', onClick: () => onDismiss(summary.id), children: jsx(Codicon, { name: 'close', size: 12 }) }),
        ],
      }),
      !data
        ? jsx('div', { className: cn('text-xs', muted), children: 'Loading card…' })
        : data.ok === false
          ? jsx('div', { className: cn('text-xs', muted), children: errorOf(data, 'Could not load this card.') })
          : jsx(CardFrame, { ctx, card: data }),
    ],
  })
}

function Cards({ ctx }) {
  const queryClient = useQueryClient()
  const list = useQuery({
    queryKey: ['coinfello', 'cards'],
    queryFn: () => ctx.rest('/cards'),
    // The event is instant; this catches Hermes builds without it.
    refetchInterval: 20 * 1000,
  })
  useEffect(() => {
    if (typeof ctx.onEvent !== 'function') return undefined
    return ctx.onEvent(CARD_SHOWN_EVENT, () => queryClient.invalidateQueries({ queryKey: ['coinfello', 'cards'] }))
  }, [ctx, queryClient])

  const dismiss = async (id) => {
    await ctx.rest(`/cards/${id}/dismiss`, { method: 'POST', body: {} })
    queryClient.invalidateQueries({ queryKey: ['coinfello', 'cards'] })
  }

  const items = (list.data && list.data.ok !== false && list.data.cards) || []
  if (items.length === 0) return null
  return jsx('div', {
    className: 'flex flex-col gap-3 border-b border-(--ui-stroke-secondary) pb-3',
    children: items.slice(0, 3).map((card) => jsx(CardSlot, { ctx, summary: card, onDismiss: dismiss }, card.id)),
  })
}

// -- pane ----------------------------------------------------------------------

function Pane({ ctx }) {
  const queryClient = useQueryClient()
  const status = useQuery({
    queryKey: ['coinfello', 'status'],
    queryFn: () => ctx.rest('/status'),
    refetchInterval: 30 * 1000,
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['coinfello'] })
  const data = status.data
  const connected = !!(data && data.connected)
  const [view, setView] = useState({ kind: 'home' })
  useEarnRequests(ctx, connected && !!data.earn_supported, (request) =>
    setView({ kind: 'earn', query: request.query || '', requestId: request.id }),
  )

  const signOut = async () => {
    // Optimistic: show the signed-out pane now. The backend forgets the
    // session at once and revokes it server-side in the background.
    const previous = queryClient.getQueryData(['coinfello', 'status']) || {}
    await queryClient.cancelQueries({ queryKey: ['coinfello'] })
    queryClient.removeQueries({ queryKey: ['coinfello', 'portfolio'] })
    queryClient.removeQueries({ queryKey: ['coinfello', 'wallet'] })
    queryClient.setQueryData(['coinfello', 'status'], {
      endpoint: previous.endpoint,
      app_url: previous.app_url,
      email: previous.email,
      sign_in_mode: previous.sign_in_mode,
      connected: false,
    })
    try {
      await ctx.rest('/disconnect', { method: 'POST', body: {} })
    } finally {
      refresh()
    }
  }

  let body
  if (!data) body = jsx('div', { className: cn('text-xs', muted), children: 'Checking connection…' })
  else if (connected && view.kind === 'send') {
    body = jsx(SendFlow, { ctx, portfolio: view.portfolio, onClose: () => setView({ kind: 'home' }) })
  } else if (connected && view.kind === 'swap') {
    body = jsx(EmbedView, { ctx, appUrl: data.app_url, kind: 'swap', onClose: () => setView({ kind: 'home' }) })
  } else if (connected && view.kind === 'earn') {
    body = jsx(EmbedView, {
      key: view.requestId || 'earn',
      ctx,
      appUrl: data.app_url,
      kind: 'earn',
      query: view.query || '',
      onClose: () => setView({ kind: 'home' }),
    })
  } else if (connected) {
    body = jsxs(Fragment, {
      children: [
        jsx(Cards, { ctx }),
        data.pending_approval_id
          ? jsx(PendingSignIn, { ctx, status: data, refresh, upgrade: !!data.pending_upgrade })
          : jsx(AccessBadge, { ctx, status: data, refresh }),
        jsx(WalletCard, { ctx }),
        jsx(Portfolio, {
          ctx,
          onSend: (portfolio) => setView({ kind: 'send', portfolio }),
          onSwap: () => setView({ kind: 'swap' }),
          onEarn: () => setView({ kind: 'earn' }),
        }),
        jsxs('div', {
          className: cn(row, 'border-t border-(--ui-stroke-secondary) pt-2 text-[0.6875rem]', muted),
          children: [
            jsx('span', {
              className: 'min-w-0 truncate',
              title: data.signed_in_as || undefined,
              children: data.signed_in_as
                ? `Signed in as ${data.signed_in_as}`
                : data.expires_at ? `Session renews automatically · ${shortDate(data.expires_at)}` : '',
            }),
            jsx(Button, { variant: 'ghost', size: 'sm', onClick: signOut, children: data.signed_in_as ? 'Not you? Sign out' : 'Sign out' }),
          ],
        }),
      ],
    })
  } else if (data.sign_in_mode === 'email') body = jsx(EmailSignIn, { ctx, status: data, refresh })
  else body = jsx(BrowserSignIn, { ctx, status: data, refresh })

  return jsxs('div', {
    className: 'flex h-full flex-col gap-3 overflow-auto p-3 text-sm',
    children: [
      jsxs('div', {
        className: row,
        children: [
          jsx('div', { className: 'font-medium', children: 'CoinFello' }),
          jsxs('div', {
            className: cn('flex items-center gap-1.5 text-xs', muted),
            children: [jsx(StatusDot, { tone: connected ? 'good' : 'muted' }), connected ? 'connected' : 'not signed in'],
          }),
        ],
      }),
      body,
    ],
  })
}

function Chip({ ctx }) {
  const status = useQuery({
    queryKey: ['coinfello', 'status'],
    queryFn: () => ctx.rest('/status'),
    refetchInterval: 30 * 1000,
  })
  const connected = !!(status.data && status.data.connected)
  return jsxs('div', {
    className: cn('inline-flex h-full items-center gap-1.5 px-1.5 text-[0.6875rem]', muted),
    children: [jsx(StatusDot, { tone: connected ? 'good' : 'muted' }), 'coinfello'],
  })
}

export default {
  id: ID,
  name: 'CoinFello',
  register(ctx) {
    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'coinfello',
      data: { placement: 'right', width: '320px' },
      render: () => jsx(Pane, { ctx }),
    })
    ctx.register({
      id: 'chip',
      area: 'statusBar.right',
      order: 140,
      render: () => jsx(Chip, { ctx }),
    })
  },
}
