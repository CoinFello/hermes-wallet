# CoinFello for Hermes Agent

A Hermes Agent plugin that connects the agent to [CoinFello](https://coinfello.com)
through the CoinFello MCP server: sign in once, and the agent gets fast reads
over your automation wallet (balances, positions, LP ranges, open orders,
activity, prices, yields, swap/bridge quotes) plus **Fello**, CoinFello's DeFi
agent, which can execute on-chain actions for you.

Includes a desktop pane: one-click browser sign-in, the automations wallet
(copy + QR to fund it), balances per network shaped like the CoinFello
Portfolio view, and CoinFello's MCP App cards (portfolio, quotes,
automations, yields, ...) when the agent shows one.

## What you get

**22 agent tools** (toolset `coinfello`):

| Tool | What it does |
|---|---|
| `coinfello_status` | Connection state, wallet (funding) address, expiry |
| `coinfello_connect` | Start sign-in: browser approval link + code (email code on older servers) |
| `coinfello_poll_approval` | Finish sign-in once the human approved in the browser |
| `coinfello_verify` | Email-code sign-in, only for servers without browser sign-in |
| `coinfello_disconnect` | Revoke the session now |
| `coinfello_chat` | Ask Fello to do something (can EXECUTE; each message needs your approval) |
| `coinfello_job_status` | Poll a running Fello turn |
| `coinfello_balances` / `_positions` / `_lp_positions` / `_open_orders` / `_activity` | Wallet reads |
| `coinfello_quote` | Swap/bridge quote, for comparing (executes nothing, not executable by reference) |
| `coinfello_prepare_swap` / `coinfello_prepare_send` | Validate, price and hold a trade as a 2-minute single-use intent (executes nothing) |
| `coinfello_execute` | Run a prepared intent ON-CHAIN, only after you approve its summary in Hermes |
| `coinfello_transfer_status` | What a swap/bridge actually delivered: completed, wrong_token, refunded, failed |
| `coinfello_yields` / `_prices` | Market reads |
| `coinfello_show_card` | Show a CoinFello card: drawn in the desktop pane; other surfaces get its text |
| `coinfello_set_daily_limit` / `_limit_status` | Lower the daily limit, or ask the human to approve a raise |

**Desktop pane** (desktop half of the same package):

- **Sign in with CoinFello**: opens one approval page in your browser and
  shows the code to match. Already signed in to CoinFello there? One click.
- **Automations wallet**: address with copy button and a scannable QR to
  fund it (same address on every EVM network).
- **Portfolio**: total value with its 24h move, balances grouped per network
  with token logos, using the same rules as the web Portfolio view
  (`coinfello_portfolio.py` names the web function each rule is ported from).
- **Portfolio / Strategies** buttons open the full views in CoinFello.
- **Cards** the agent shows appear at the top of the pane (see below).
- Statusbar connection chip.

## Install

```bash
git clone git@github.com:CoinFello/coinfello-hermes-plugin.git
cd coinfello-hermes-plugin
./install.sh                       # copies the plugin into ~/.hermes/plugins/coinfello
hermes plugins enable coinfello    # admits it AND installs its Python deps (segno)
```

Restart Hermes. The MCP tools appear as `coinfello_*`; the desktop pane
appears after **Reload desktop plugins** (⌘K) — the desktop half is opt-in
and inventories under Capabilities → Plugins.

### Configuration

| Env var | Default | Meaning |
|---|---|---|
| `COINFELLO_MCP_URL` | `https://app.coinfello.com/api/mcp` | MCP endpoint (streamable HTTP). Point it at a preview deployment to test there. |

Set it in `~/.hermes/.env` or the process environment. The plugin's session
token is stored under `providers.coinfello` in the profile's `auth.json` —
never in `config.yaml`.

> Note: token storage uses the same (currently private) `hermes_cli.auth`
> helpers the official Spotify plugin uses — there is no public writer for
> provider state yet. `hermes plugins validate` passes, with a warning; if a
> Hermes release moves those helpers, the plugin falls back to a 0600 state
> file inside the plugin directory.

## Sign-in flow

**Browser-first** (CoinFello servers with `start_browser_sign_in`):

1. **Sign in with CoinFello** opens `/authorize` in your browser and the pane
   shows a code.
2. Sign in to CoinFello there (skipped if you already are), check the code
   matches, approve.
3. The pane picks the session up on its own. New and existing accounts take
   the same path.

**Sessions renew themselves**: within two weeks of expiry the plugin swaps
the token for a fresh 30-day one (`renew_session`), so a plugin in regular
use never signs in again.

**Older servers** (no browser sign-in yet) fall back automatically to the
email-code flow: code by email, then a one-time browser approval for wallets
that already exist. The plugin detects which flow the server offers through
`tools/list`.

## Trading from the agent

1. `coinfello_prepare_swap` (or `_send`) asks the server to quote and validate
   the trade (balance, recipient, gas on the source chain) and to hold it as a
   single-use intent for two minutes. Nothing moves.
2. `coinfello_execute` runs it. Before it does, the plugin's `pre_tool_call`
   hook puts it through Hermes' approval prompt, showing the **server's**
   summary of that intent (cached at prepare time, never text the model
   wrote), e.g. *Bridge 0.004186 ETH on Ethereum Mainnet to at least 113.25
   POL on Polygon via layerswap*. Deny, and nothing is sent. The rule key is
   per intent, so an "always" answer never covers another trade.
3. The server executes exactly the prepared arguments: a price below the
   approved minimum (`price_moved`) or a different bridge than the approved
   one (`route_changed`) is refused before anything is broadcast.
4. A bridge's success only confirms the source chain. `coinfello_transfer_status`
   reads LI.FI's status and says what arrived: `wrong_token` (e.g. Across
   delivering WETH instead of native POL) and `refunded` are failures to
   report, not to repair with another trade.

`coinfello_chat` gets the same prompt for every message, since Fello can act
on any of them without asking again.

Approvals follow your Hermes settings: `--yolo` or **Approvals: off** skip
the prompt for these tools too, and non-interactive runs (cron, `-q`) are
refused unless you configured them to auto-approve.

Servers without `prepare_swap` (older CoinFello servers) cannot
prepare trades; `coinfello_transfer_status` then reads LI.FI directly.

## Cards (MCP Apps)

CoinFello's MCP server ships its views as MCP App cards: `show_<card>_card`
tools whose `_meta.ui.resourceUri` names a `ui://coinfello/...` HTML
document. The agent shows one with `coinfello_show_card` (`portfolio`,
`status`, `quote`, `automations`, `needs_you`, `error`, `fund`, `yield`,
`lp_ranges`, `perp`, `send`, `dca`, `earn_deposit`, `spend_limit`; the
sign-in card is left out, the pane has its own sign-in).

1. The plugin calls the server's card tool with the stored session, sending
   only the arguments the tool's schema declares, never a session token.
2. On **Hermes desktop** (`ctx.session_surface() == "desktop"`) the raw
   result becomes a card record (memory and `<hermes home>/coinfello/cards/`,
   0600, 24 hours), the pane is told (`plugin.coinfello.card.shown`), and the
   agent is told the card is in the pane. On every other surface (Telegram,
   CLI, ...) the agent gets the card's full text and no card is stored.
3. The pane fetches `/cards/{id}`: the card's HTML with a CSP meta tag and
   the theme injected, as a `data:` URL, plus the tool input and result. It
   mounts it in a `SandboxedFrame` (`allow-scripts` only: opaque origin, no
   storage, no popups) and answers the card's MCP Apps bridge.

What a card may call, checked in the pane and again in Python:

| Card | Relayed | Needs the human's Confirm in the pane |
|---|---|---|
| every card | its own `show_*_card` (refresh), `whoami` | |
| quote | `prepare_swap`, `prepare_send` | `execute_intent` |
| send / dca / earn_deposit / spend_limit | its `prepare_*` | `execute_intent` |
| automations | `pause_automation` | `cancel_automation` |
| error | its Retry tool, if on the server's retryable list (reads and quotes) | |

`execute_intent` runs only for an intent this card produced and Hermes
prepared (the server's summary, kept with the card record, is what the
confirmation shows), once and before it expires.
`cancel_automation` runs only for an automation the card listed. Sign-out,
Fello, sign-in, session renewal, embed tokens and daily-limit changes are
never relayed, nor is anything not in the table. Credential-like keys are
stripped from arguments and results in both directions.

The card's CSP: `default-src 'none'; script-src 'unsafe-inline'; style-src
'unsafe-inline' <resourceDomains>; font-src <resourceDomains>; img-src data:;
connect-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'`.

Cards need Hermes 0.22.3 or newer (`ctx.session_surface`); on older Hermes
the tool returns the card's text everywhere. The plugin does not advertise
the MCP Apps extension to the server, so card tools always answer with
their full text plus `structuredContent`, on every surface.

### Swap and Earn: CoinFello's own UI in the pane

The pane's **Swap** and **Earn** buttons host coinfello-web's `/embed/swap`
and `/embed/earn` (the app's real components) in a `SandboxedFrame`. One host
serves both (`desktop/plugin.js`, the `embed-host` section): the frame loads
`<app><path>?theme=dark|light`, says `coinfello:embed-ready`, and gets a
15-minute token minted for its scope (`create_embed_token {scope}`, never the
session token) with a per-mount nonce. A later token request must echo the
nonce, and one within a minute of the last token stops instead of looping
on a dead session. Results arrive as `coinfello:swap-result` /
`coinfello:earn-result`; an Earn result says "nothing was sent" only for a
cancel or failure with no transaction, and anything uncertain links the
transaction and asks to check it.

- **Earn preselects**: `&opportunity=<yield id>`, or `&token=<SYMBOL>&chain_id=<n>`,
  validated and percent-encoded by `coinfello_earn.frame_query`.
- **From the agent**: `coinfello_show_card` with `card="earn_deposit"` on
  Hermes desktop opens the Earn view (with any preselect from its
  arguments) instead of the typed-yield-id card, and calls no CoinFello tool.
  Other surfaces keep the card's text. This reuses `coinfello_show_card`
  rather than adding a tool: it is where the agent already goes to deposit,
  and it keeps the desktop-or-text rule in one place. The `yield` card is
  unchanged.
- **Read-only sessions** may open Earn: the server decides whether to mint a
  token for browsing, and a refusal is shown in plain words.
- **Older servers** (no `scope` on `create_embed_token`, or one without
  `earn`): no Earn button, a one-line note, and `earn_deposit` on desktop
  shows the read-only `yield` card when it has a token to show (otherwise
  the deposit card, as before).

## Security notes

- The MCP session token can move funds from the automation wallet. Treat it
  like a password; revoke it in the CoinFello app (Automation Wallet) at any
  time — revocation ends the session immediately.
- `coinfello_chat` executes on-chain actions **without further
  confirmation** on the CoinFello side, so Hermes asks you to approve each
  message. The CoinFello MCP server currently has no server-side spend cap.
- `coinfello_execute` runs only intents this Hermes process prepared, once,
  after you approve the server's summary in Hermes.
- Fast reads (`get_*`) are read-only.

## Development

```bash
uv run --no-project --with pytest --with fastapi --with httpx --with 'segno>=1.6,<2' pytest tests/
node --test tests/card_bridge.test.mjs   # the pane's card bridge (pytest runs it too when node is installed)
node --test tests/amount.test.mjs        # the pane's amount normalizer (likewise)
node --test tests/embed_host.test.mjs    # the pane's swap/Earn embed host (likewise)
```

The test suite runs a local mock of the MCP streamable-HTTP transport — no
network or real credentials involved.

### Layout

```
├── plugin.yaml            agent-plugin manifest (provides_tools)
├── pyproject.toml         Python deps (segno), installed by Hermes plugin admission
├── __init__.py            register(ctx) — registers the agent tools
├── coinfello_mcp.py       stdlib MCP streamable-HTTP client
├── coinfello_state.py     endpoint config + session token storage
├── coinfello_core.py      service layer (sign-in, renewal, reads, status)
├── coinfello_portfolio.py pane portfolio model, ported from the web Portfolio view
├── coinfello_tools.py     tool schemas + handlers
├── coinfello_trades.py    prepare/execute, the approval hook, transfer status
├── coinfello_cards.py     MCP App cards: show, card records, CSP, bridge allowlist
├── coinfello_earn.py      the Earn view: preselects, frame query, the agent's open request
├── dashboard/             web/desktop backend: FastAPI router at /api/plugins/coinfello/
├── desktop/plugin.js      desktop pane + statusbar chip + card frames
└── tests/                 mock-MCP test suite
```

### Roadmap

- **Wide cards**: cards target ~480px and the pane is ~320px, so a card that
  overflows is scaled down. Opening a card in the main workspace
  (`host.openWorkspace`) would give it full width.

- **Embedded portfolio + strategies**: `/embed/*` routes in coinfello-web
  (same components as the real pages, short-lived scoped token) hosted in a
  Hermes full-page view, so web releases reach Hermes with no plugin change.
  Until then the pane's buttons open CoinFello in the browser.
- **Tier 2**: MetaMask mobile via WalletConnect (QR pairing; transactions
  approved on-device).
- **Tier 3**: MetaMask browser extension embedded in the Hermes desktop app
  (extension-host pane; feasibility spike required).
