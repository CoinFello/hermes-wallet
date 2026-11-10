"""Which liquidity venue a transaction actually used, instead of the aggregator.

The activity feed labels a transaction with the application its wallet call
went to (Zerion's ``application_metadata.name``). For trades routed through an
aggregator that label is the aggregator (LI.FI), which the pane must not show.
This module names the venue underneath instead:

- **swaps**: read the receipt's logs and recognise the pools that emitted swap
  events. Pair/pool contracts are attributed through their ``factory()``
  against a table of factories verified on-chain; singletons (Uniswap v4's
  PoolManager, Balancer's vaults) by address; Curve by its own event. An
  unrecognised pool names nothing: the pane never guesses a venue.
- **bridges**: CoinFello's ``get_transfer_status`` reports the bridge LI.FI
  used (``tool``), e.g. Across or Layerswap. Only bridges in ``BRIDGES`` are
  named, so a nested aggregator is never shown either.

Results are cached on disk by chain + hash (a mined transaction's logs never
change); lookups that fail are not cached and are retried on the next read.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable

#: Labels that name a router/aggregator rather than where liquidity came
#: from. Compared case-insensitively after stripping spaces, dots and dashes.
AGGREGATORS = frozenset(
    {
        "lifi", "lifidiamond", "jumper", "jumperexchange", "socket", "bungee", "1inch", "1inchnetwork",
        "0x", "0xprotocol", "0xexchangeproxy", "matcha", "paraswap", "velora", "openocean", "kyberswap",
        "kyberswapaggregator", "odos", "rango", "squid", "squidrouter", "okxdex", "okxdexaggregator",
        "metamaskswaps", "metamaskbridge", "rubic", "xyfinance", "via", "symbiosisaggregator",
        "sushiswapaggregator", "sushirouteprocessor", "bebop", "enso",
    }
)


def _norm(label: str) -> str:
    return "".join(ch for ch in label.lower() if ch.isalnum())


def is_aggregator(label: Any) -> bool:
    return isinstance(label, str) and _norm(label) in AGGREGATORS


# -- swap venues ---------------------------------------------------------------

# keccak256 of each event signature (computed, not copied).
V2_SWAP = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"  # Uniswap/Sushi/Pancake v2
V3_SWAP = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"  # Uniswap/Sushi v3, Slipstream
PANCAKE_V3_SWAP = "0x19b47279256b2a23a1665c810c8d55a1758940ee09377d4f8d26497a3577dc83"
SOLIDLY_SWAP = "0xb3e2773606abfd36b5bd91394b3a54d1398336c65005baf7bf7a05efeffaf75b"  # Aerodrome/Velodrome v2
V4_SWAP = "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f"  # Uniswap v4 PoolManager
BALANCER_V2_SWAP = "0x2170c741c41531aec20e7c107c24eecfdd15e69c9bb0a8dd37b1840b9e0b207b"
BALANCER_V3_SWAP = "0x0874b2d545cb271cdbda4e093020c452328b24af12382ed62c4d00f5c26709db"
CURVE_EXCHANGES = frozenset(
    {
        "0x8b3e96f2b889fa771c53c981b40daf005f63f637f1869f707052d15a3dd97140",  # TokenExchange (stableswap)
        "0xd013ca23e77a65003c2c659c5442c00c805371b7fc1ebd4c206c41d1536bd90b",  # TokenExchangeUnderlying
        "0xb2e76ae99761dc136e598d4a629bb347eccb9532a5f8bbd72e18467c3c34cc98",  # TokenExchange (cryptoswap)
        "0x143f1f8e861fbdeddd5b46e844b7d3ac7b86a122f36e8c463859ee6811b1f29c",  # TokenExchange (tricrypto-ng)
    }
)
POOL_EVENTS = frozenset({V2_SWAP, V3_SWAP, PANCAKE_V3_SWAP, SOLIDLY_SWAP})
FACTORY_SELECTOR = "0xc45a0155"  # factory()

_UNI_V3 = "0x1f98431c8ad98523631ae4a59f267346ea31f984"
_SUSHI = "0xc35dadb65012ec5796536bd9864ed8773abc74c4"
_PANCAKE_V3 = "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865"
_BALANCER_V2 = "0xba12222222228d8ba445958a75a0704d566bf2c8"
_BALANCER_V3 = "0xba1333333333a1ba1108e8412f11850a5c319ba9"

#: (chain id, lowercase address) -> venue. Every entry was checked on its
#: chain: code present and, for v2/v3 factories, answering allPairsLength() /
#: feeAmountTickSpacing() as that factory type does.
VENUE_CONTRACTS: dict[tuple[int, str], str] = {
    # Uniswap v2 factories
    (1, "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f"): "Uniswap",
    (10, "0x0c3c1c532f1e39edf36be9fe0be1410313e074bf"): "Uniswap",
    (56, "0x8909dc15e40173ff4699343b6eb8132c65e18ec6"): "Uniswap",
    (130, "0x1f98400000000000000000000000000000000002"): "Uniswap",
    (137, "0x9e5a52f57b3038f1b8eee45f28b3c1967e22799c"): "Uniswap",
    (8453, "0x8909dc15e40173ff4699343b6eb8132c65e18ec6"): "Uniswap",
    (42161, "0xf1d7cc64fb4452f05c498126312ebe29f30fbcf9"): "Uniswap",
    (43114, "0x9e5a52f57b3038f1b8eee45f28b3c1967e22799c"): "Uniswap",
    # Uniswap v3 factories
    **{(chain, _UNI_V3): "Uniswap" for chain in (1, 10, 137, 42161)},
    (56, "0xdb1d10011ad0ff90774d0c6bb92e5c5c8b4461f7"): "Uniswap",
    (130, "0x1f98400000000000000000000000000000000003"): "Uniswap",
    (8453, "0x33128a8fc17869897dce68ed026d694621f6fdfd"): "Uniswap",
    (43114, "0x740b1c1de25031c31ff4fc9a62f554a55cdc1bad"): "Uniswap",
    (57073, "0x640887a9ba3a9c53ed27d0f7e8246a4f933f3424"): "Uniswap",
    (59144, "0x31fafd4889fa1269f7a13a66ee0fb458f27d72a9"): "Uniswap",
    (534352, "0x70c62c8b8e801124a4aa81ce07b637a3e83cb919"): "Uniswap",
    # Uniswap v4 PoolManagers (singletons: the Swap event's emitter)
    (1, "0x000000000004444c5dc75cb358380d2e3de08a90"): "Uniswap",
    (10, "0x9a13f98cb987694c9f086b1f5eb990eea8264ec3"): "Uniswap",
    (56, "0x28e2ea090877bf75740558f6bfb36a5ffee9e9df"): "Uniswap",
    (130, "0x1f98400000000000000000000000000000000004"): "Uniswap",
    (137, "0x67366782805870060151383f4bbff9dab53e5cd6"): "Uniswap",
    (8453, "0x498581ff718922c3f8e6a244956af099b2652b2b"): "Uniswap",
    (42161, "0x360e68faccca8ca495c1b759fd9eee466db9fb32"): "Uniswap",
    (43114, "0x06380c0e0912312b5150364b9dc4542ba0dbbc85"): "Uniswap",
    (57073, "0x360e68faccca8ca495c1b759fd9eee466db9fb32"): "Uniswap",
    # SushiSwap v2 + v3 factories
    (1, "0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac"): "SushiSwap",
    **{(chain, _SUSHI): "SushiSwap" for chain in (56, 137, 42161, 43114)},
    (8453, "0x71524b4f93c58fcbf659783284e38825f0622859"): "SushiSwap",
    (1, "0xbaceb8ec6b9355dfc0269c18bac9d6e2bdc29c4f"): "SushiSwap",
    (10, "0x9c6522117e2ed1fe5bdb72bb0ed5e3f2bde7dbe0"): "SushiSwap",
    (56, "0x126555dd55a39328f69400d6ae4f782bd4c34abb"): "SushiSwap",
    (137, "0x917933899c6a5f8e37f31e19f92cdbff7e8ff0e2"): "SushiSwap",
    (8453, _SUSHI): "SushiSwap",
    (42161, "0x1af415a1eba07a4986a52b6f2e7de7003d82231e"): "SushiSwap",
    (43114, "0x3e603c14af37ebdad31709c4f848fc6ad5bec715"): "SushiSwap",
    # PancakeSwap
    **{(chain, _PANCAKE_V3): "PancakeSwap" for chain in (1, 56, 8453, 42161, 59144)},
    (56, "0xca143ce32fe78f1f7019d7d551a6402fc5350c73"): "PancakeSwap",
    # Aerodrome (Base) and Velodrome (OP): v2 PoolFactory + Slipstream CL factory
    (8453, "0x420dd381b31aef6683db6b902084cb0ffece40da"): "Aerodrome",
    (8453, "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a"): "Aerodrome",
    (10, "0xf1046053aa5682b4f9a81b5481394da16be5ff5a"): "Velodrome",
    (10, "0xcc0bddb707055e04e497ab22a59c2af4391cd12f"): "Velodrome",
    # Balancer vaults (singletons)
    **{(chain, _BALANCER_V2): "Balancer" for chain in (1, 10, 137, 8453, 42161, 43114)},
    **{(chain, _BALANCER_V3): "Balancer" for chain in (1, 8453, 42161)},
}

#: Public JSON-RPC endpoints, one per chain the CoinFello app supports.
RPC_URLS: dict[int, str] = {
    1: "https://ethereum-rpc.publicnode.com",
    10: "https://optimism-rpc.publicnode.com",
    56: "https://bsc-rpc.publicnode.com",
    130: "https://unichain-rpc.publicnode.com",
    137: "https://polygon-bor-rpc.publicnode.com",
    143: "https://rpc.monad.xyz",
    5000: "https://mantle-rpc.publicnode.com",
    8453: "https://base-rpc.publicnode.com",
    42161: "https://arbitrum-one-rpc.publicnode.com",
    43114: "https://avalanche-c-chain-rpc.publicnode.com",
    57073: "https://rpc-gel.inkonchain.com",
    59144: "https://linea-rpc.publicnode.com",
    534352: "https://scroll-rpc.publicnode.com",
    747474: "https://rpc.katana.network",
}


class LookupFailed(Exception):
    """The chain could not be read; try again later (never cached)."""


def _rpc(chain_id: int, method: str, params: list, timeout: float = 8.0) -> Any:
    url = RPC_URLS.get(chain_id)
    if not url:
        raise LookupFailed(f"no RPC for chain {chain_id}")
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(
        url, data=body, headers={"content-type": "application/json", "user-agent": "coinfello-hermes"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            reply = json.load(response)
    except Exception as exc:  # network, HTTP, JSON
        raise LookupFailed(str(exc)) from exc
    if "error" in reply:
        return None  # e.g. execution reverted: an answer, not a failure
    return reply.get("result")


def _address_from_word(word: Any) -> str | None:
    if isinstance(word, str) and word.startswith("0x") and len(word) >= 42:
        return "0x" + word[-40:].lower()
    return None


def venues_from_logs(chain_id: int, logs: list, factory_of: Callable[[str], str | None]) -> list[str]:
    """Venue names in the order their swaps appear, without duplicates."""
    names: list[str] = []
    for log in logs:
        if not isinstance(log, dict) or not log.get("topics"):
            continue
        topic = str(log["topics"][0]).lower()
        emitter = str(log.get("address") or "").lower()
        name = None
        if topic in POOL_EVENTS:
            factory = factory_of(emitter)
            name = VENUE_CONTRACTS.get((chain_id, factory)) if factory else None
        elif topic in (V4_SWAP, BALANCER_V2_SWAP, BALANCER_V3_SWAP):
            name = VENUE_CONTRACTS.get((chain_id, emitter))
        elif topic in CURVE_EXCHANGES:
            name = "Curve"
        if name and name not in names:
            names.append(name)
    return names


def swap_venues(chain_id: int, tx_hash: str) -> list[str]:
    """Read the receipt and name its venues. Raises LookupFailed when the
    chain cannot be read or the transaction is not mined yet."""
    receipt = _rpc(chain_id, "eth_getTransactionReceipt", [tx_hash])
    if not isinstance(receipt, dict):
        raise LookupFailed("no receipt yet")
    factories: dict[str, str | None] = {}

    def factory_of(pool: str) -> str | None:
        if pool not in factories:
            factories[pool] = _address_from_word(
                _rpc(chain_id, "eth_call", [{"to": pool, "data": FACTORY_SELECTOR}, "latest"])
            )
        return factories[pool]

    return venues_from_logs(chain_id, receipt.get("logs") or [], factory_of)


# -- bridges -----------------------------------------------------------------------

#: LI.FI tool keys -> the bridge's own name. Anything else (an aggregator
#: nested in the route, an unknown key) is not shown.
BRIDGES = {
    "across": "Across", "layerswap": "Layerswap", "stargate": "Stargate", "stargatev2": "Stargate",
    "stargatev2bus": "Stargate", "hop": "Hop", "cbridge": "Celer cBridge", "celercircle": "Circle CCTP",
    "relay": "Relay", "mayan": "Mayan", "mayanwh": "Mayan", "mayanmctp": "Mayan", "symbiosis": "Symbiosis",
    "allbridge": "Allbridge", "chainflip": "Chainflip", "glacis": "Glacis", "polygon": "Polygon PoS Bridge",
    "arbitrum": "Arbitrum Bridge", "optimism": "OP Bridge", "gnosis": "Gnosis Bridge", "thorswap": "THORChain",
    "eco": "Eco", "omni": "Omni", "debridge": "deBridge", "dln": "deBridge", "circle": "Circle CCTP",
    "cctp": "Circle CCTP", "hyperlane": "Hyperlane",
}


def bridge_name(tool: Any) -> str | None:
    return BRIDGES.get(_norm(tool)) if isinstance(tool, str) else None


# -- cache + batch -------------------------------------------------------------------

# Versioned: a table change (a new venue) must not be masked by old "none" entries.
CACHE_FILE = Path(__file__).resolve().parent / ".coinfello-venues-v1.json"
CACHE_LIMIT = 2000
_lock = threading.Lock()


def _load_cache() -> dict:
    try:
        data = json.loads(CACHE_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    if len(cache) > CACHE_LIMIT:  # keep the newest entries (insertion order)
        cache = dict(list(cache.items())[-CACHE_LIMIT:])
    try:
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        tmp.replace(CACHE_FILE)
    except OSError:
        pass  # a cache that cannot be written only costs a re-read


def resolve(jobs: list[dict], bridge_tool: Callable[[str], Any] | None, *, deadline: float = 8.0) -> dict:
    """Venues for many transactions at once, cached; best effort within ``deadline``.

    ``jobs``: ``{"kind": "swap"|"bridge", "chain_id", "tx_hash"}``. Returns
    ``{"<chain>:<hash>": [names]}`` for those resolved; the rest are absent.
    """
    with _lock:
        cache = _load_cache()
    results: dict[str, list[str]] = {}
    todo = []
    for job in jobs:
        key = f"{job.get('chain_id')}:{str(job.get('tx_hash') or '').lower()}"
        if key in cache:
            results[key] = cache[key]
        elif key not in {k for k, _ in todo}:
            todo.append((key, job))
    if not todo:
        return results

    def run(job: dict) -> list[str]:
        if job["kind"] == "bridge":
            if bridge_tool is None:
                raise LookupFailed("no bridge status source")
            status = bridge_tool(job["tx_hash"])
            if not isinstance(status, dict) or status.get("status") not in ("DONE", "FAILED"):
                raise LookupFailed("bridge not settled")
            name = bridge_name(status.get("tool"))
            return [name] if name else []
        return swap_venues(int(job["chain_id"]), job["tx_hash"])

    fresh: dict[str, list[str]] = {}
    pool = ThreadPoolExecutor(max_workers=6)
    try:
        futures = {pool.submit(run, job): key for key, job in todo}
        done, _ = wait(futures, timeout=deadline)
        for future in done:
            try:
                fresh[futures[future]] = future.result()
            except Exception:  # LookupFailed, MCP errors: retried next time
                continue
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    if fresh:
        with _lock:
            cache = _load_cache()
            cache.update(fresh)
            _save_cache(cache)
    results.update(fresh)
    return results
