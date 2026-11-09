# CoinFello for Hermes Agent

A Hermes Agent plugin that connects the agent to [CoinFello](https://coinfello.com)
through the CoinFello MCP server: sign in once, and the agent gets fast reads
over your automation wallet (balances, positions, LP ranges, open orders,
activity, prices, yields, swap/bridge quotes) plus **Fello**, CoinFello's DeFi
agent, which can execute on-chain actions for you.

Includes a desktop pane: one-click browser sign-in, the automations wallet
(copy + QR to fund it), and balances per network, shaped like the CoinFello
Portfolio view.

## What you get

**19 agent tools** (toolset `coinfello`):

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

**Desktop pane** (desktop half of the same package):

- **Sign in with CoinFello**: opens one approval page in your browser and
  shows the code to match. Already signed in to CoinFello there? One click.
- **Automations wallet**: address with copy button and a scannable QR to
  fund it (same address on every EVM network).
- **Portfolio**: total value with its 24h move, balances grouped per network
  with token logos, using the same rules as the web Portfolio view
  (`coinfello_portfolio.py` names the web function each rule is ported from).
- **Portfolio / Strategies** buttons open the full views in CoinFello.
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

## The pane

- **Header:** the CoinFello logo (wordmark follows your theme's text colour),
  connection state, and a **Settings** gear.
- **Home:** the automations wallet (address + copy), portfolio total and 24h
  change, and Send / Swap / Receive (Receive shows the funding QR). Below that,
  assets grouped by network and links to the full portfolio and strategies.
  **Full portfolio** opens CoinFello's portfolio in a Hermes tab (main area)
  when the server offers the read-only `/embed/portfolio` view
  (`create_embed_token` with scope `portfolio`): it always shows this
  plugin's account, with no browser, cookies or wallet extension involved.
  Older servers, and Strategies for now, open in the browser with a note to
  dismiss any wallet-extension prompt (the web app reconnects extension
  wallets, which can sign in as a different account).
  A read-only session or a pending allowance change shows one notice that
  opens Settings.
- **Settings:** the trading allowance (daily limit, what's left in the last
  24 hours, change it without signing in again), the account and sign-out,
  **Appearance** (CoinFello colors), and the server in use.

The styling is one stylesheet scoped to `.cf`, injected at register and
removed on dispose. Surfaces, text, borders, fonts and gain/loss colours come
from the active Hermes theme (`--ui-*`, `--font-*`, `--ui-green`/`--ui-red`).
Buttons and highlights use the theme's accent (`--dt-primary`, the colour of
Hermes' own primary buttons) by default; **Settings > Appearance > CoinFello
colors** switches them to CoinFello's yellow (saved per app with
`ctx.storage`). CoinFello also contributes the logo, serif portfolio figures,
round token icons and rounded cards.

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
├── dashboard/             web/desktop backend: FastAPI router at /api/plugins/coinfello/
├── desktop/plugin.js      desktop pane + statusbar chip
└── tests/                 mock-MCP test suite
```

### Roadmap

- **Embedded portfolio + strategies**: `/embed/*` routes in coinfello-web
  (same components as the real pages, short-lived scoped token) hosted in a
  Hermes full-page view, so web releases reach Hermes with no plugin change.
  Until then the pane's buttons open CoinFello in the browser.
- **Tier 2**: MetaMask mobile via WalletConnect (QR pairing; transactions
  approved on-device).
- **Tier 3**: MetaMask browser extension embedded in the Hermes desktop app
  (extension-host pane; feasibility spike required).
