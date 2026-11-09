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

function Portfolio({ ctx, onSend, onSwap }) {
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
        ],
      }),
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
  const canReview = !busy && token && Number(amount) > 0 && recipientValid

  const review = async () => {
    if (!canReview) return
    setBusy(true)
    setError('')
    try {
      const response = await ctx.rest('/send/prepare', {
        method: 'POST',
        body: { chain_id: token.chain_id, token: token.address, amount: amount.trim(), recipient: recipient.trim() },
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
      jsx(Input, { value: recipient, placeholder: 'Recipient address (0x…)', spellCheck: false, onChange: (e) => setRecipient(e.target.value) }),
      recipient && !recipientValid
        ? jsx('div', { className: cn('text-[0.6875rem]', down), children: 'Enter a full 0x address (42 characters).' })
        : null,
      jsx(Button, { type: 'submit', size: 'sm', loading: busy, disabled: !canReview, children: 'Review' }),
      error ? jsx('div', { className: cn('text-xs', down), children: error }) : null,
    ],
  })
}

// -- swap: CoinFello's real swap UI, embedded (coinfello-web /embed/swap) --------

// Hosts the embed may ask us to open (its links can't open themselves: the
// sandbox has no allow-popups). Block explorers from coinfello-web's
// BLOCK_EXPLORERS, plus Blockscan and LI.FI's bridge explorer. https only.
const EMBED_LINK_HOSTS = [
  'etherscan.io', 'optimistic.etherscan.io', 'sepolia.etherscan.io', 'arbiscan.io',
  'basescan.org', 'sepolia.basescan.org', 'bscscan.com', 'polygonscan.com',
  'lineascan.build', 'scrollscan.com', 'mantlescan.xyz', 'snowscan.xyz', 'uniscan.xyz',
  'katanascan.com', 'monadvision.com', 'explorer.inkonchain.com',
  'robinhoodchain.blockscout.com', 'blockscan.com', 'scan.li.fi',
]

function allowedEmbedLink(raw) {
  try {
    const url = new URL(String(raw))
    return url.protocol === 'https:' && EMBED_LINK_HOSTS.includes(url.hostname) ? url.toString() : null
  } catch {
    return null
  }
}

const txUrl = (hash) => (/^0x[0-9a-fA-F]{64}$/.test(String(hash || '')) ? `https://blockscan.com/tx/${hash}` : null)

function SwapEmbed({ ctx, appUrl, onClose }) {
  const queryClient = useQueryClient()
  const frameRef = useRef(null)
  const tokenSentRef = useRef(false)
  const [mount, setMount] = useState(0)
  const [height, setHeight] = useState(560)
  const [notice, setNotice] = useState('')
  const [resultUrl, setResultUrl] = useState(null)
  const [error, setError] = useState('')

  const dark = document.documentElement.classList.contains('dark')
  const src = `${String(appUrl || '').replace(/\/$/, '')}/embed/swap?theme=${dark ? 'dark' : 'light'}`

  useEffect(() => {
    tokenSentRef.current = false
    // Per-mount secret, handed to the embed with its first token. Later token
    // requests (the embed asks again when a token expires) must echo it: a
    // document the frame navigated to never saw it, so it gets nothing.
    const nonce = crypto.randomUUID()
    let lastSentAt = 0
    let lastOpenAt = 0
    const sendToken = async (frame) => {
      lastSentAt = Date.now()
      const minted = await ctx.rest('/embed-token', { method: 'POST', body: {} })
      if (!minted || minted.ok === false) {
        setError(errorOf(minted, 'Could not open swap'))
        return
      }
      // A sandboxed (opaque-origin) frame can only be addressed with '*';
      // the token is short-lived and swap-scoped.
      frame.contentWindow.postMessage({ type: 'coinfello:embed-token', token: minted.token, nonce }, '*')
    }
    const onMessage = async (event) => {
      const frame = frameRef.current
      // Only our own frame speaks this protocol; everything else is ignored.
      if (!frame || event.source !== frame.contentWindow) return
      const message = event.data || {}
      if (message.type === 'coinfello:embed-ready') {
        if (!tokenSentRef.current) {
          tokenSentRef.current = true
          await sendToken(frame)
        } else if (message.nonce === nonce) {
          // Tokens live 15 minutes. A re-request within a minute of the last
          // token means the session itself is gone (signed out, revoked):
          // minting more would loop, so stop and say so.
          if (Date.now() - lastSentAt < 60000) {
            setError('Your CoinFello session ended. Sign in again, then reopen Swap.')
            return
          }
          await sendToken(frame) // an expired token, from the same document
        } else {
          setError('The swap view reloaded. Reopen it to continue.')
        }
      } else if (message.type === 'coinfello:embed-resize' && Number(message.height) > 0) {
        setHeight(Math.min(1200, Math.max(240, Number(message.height))))
      } else if (message.type === 'coinfello:open-url') {
        // The embed's own "View" links (the sandbox blocks popups): open only
        // allowlisted https explorers, at most once a second.
        const url = allowedEmbedLink(message.url)
        const now = Date.now()
        if (url && now - lastOpenAt >= 1000) {
          lastOpenAt = now
          ctx.os.openExternal(url)
        }
      } else if (message.type === 'coinfello:swap-result') {
        queryClient.invalidateQueries({ queryKey: ['coinfello', 'portfolio'] })
        if (message.status === 'success') {
          setNotice('Swap submitted.')
          setResultUrl(txUrl(message.transactionHash))
        }
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [mount, ctx, queryClient])

  return jsxs('div', {
    className: 'flex flex-col gap-2',
    children: [
      jsxs('div', {
        className: row,
        children: [
          jsx('div', { className: 'font-medium', children: 'Swap' }),
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
      notice
        ? jsxs('div', {
            className: cn(row, 'text-xs'),
            children: [
              jsx('span', { className: up, children: notice }),
              resultUrl
                ? jsx(Button, { size: 'sm', variant: 'outline', onClick: () => ctx.os.openExternal(resultUrl), children: 'View transaction' })
                : null,
            ],
          })
        : null,
      jsx(SandboxedFrame, {
        key: mount,
        ref: frameRef,
        src,
        title: 'CoinFello swap',
        sandbox: 'allow-scripts allow-forms',
        className: 'w-full rounded-md',
        style: { height },
      }),
    ],
  })
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
    body = jsx(SwapEmbed, { ctx, appUrl: data.app_url, onClose: () => setView({ kind: 'home' }) })
  } else if (connected) {
    body = jsxs(Fragment, {
      children: [
        data.pending_approval_id
          ? jsx(PendingSignIn, { ctx, status: data, refresh, upgrade: !!data.pending_upgrade })
          : jsx(AccessBadge, { ctx, status: data, refresh }),
        jsx(WalletCard, { ctx }),
        jsx(Portfolio, {
          ctx,
          onSend: (portfolio) => setView({ kind: 'send', portfolio }),
          onSwap: () => setView({ kind: 'swap' }),
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
