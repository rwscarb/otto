"""
otto.anchor — Bitcoin OP_RETURN anchoring for confirmed otto events.

Periodically commits a merkle root of recent confirmed events to Bitcoin,
producing a tamper-evident public record. Uses btcvm's broadcast module.

Config (env vars):
  OTTO_BTC_WIF      — WIF private key for OP_RETURN broadcast
  OTTO_BTC_NETWORK  — 'testnet' (default) or 'mainnet'
  OTTO_ANCHOR_EVERY — anchor after this many confirmed events (default: 5)
"""

import hashlib
import json
import logging
import os
import sys
import time
from typing import Optional

from otto.events import ConfirmedPayload

logger = logging.getLogger('otto.anchor')

BTC_WIF          = os.environ.get('OTTO_BTC_WIF', '')
BTC_NETWORK      = os.environ.get('OTTO_BTC_NETWORK', 'testnet')
ANCHOR_EVERY     = int(os.environ.get('OTTO_ANCHOR_EVERY', '5'))

# Path to btcvm — try sibling directory or installed package
_BTCVM_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'btcvm')


def _load_broadcast():
    """Lazy-load btcvm broadcast module."""
    if _BTCVM_PATH not in sys.path:
        sys.path.insert(0, _BTCVM_PATH)
    try:
        from broadcast import broadcast_commitment, get_balance
        return broadcast_commitment, get_balance
    except ImportError as e:
        raise ImportError(f'btcvm not found at {_BTCVM_PATH}: {e}')


# ── Merkle root ────────────────────────────────────────────────────────────────

def _merkle_root(items: list[str]) -> str:
    """Compute a simple binary merkle root over a list of hex strings."""
    if not items:
        return '0' * 64
    layer = [hashlib.sha256(bytes.fromhex(h) if len(h) == 64
                            else h.encode()).hexdigest()
             for h in items]
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])   # duplicate last if odd
        layer = [
            hashlib.sha256((layer[i] + layer[i+1]).encode()).hexdigest()
            for i in range(0, len(layer), 2)
        ]
    return layer[0]


def _event_hash(c: ConfirmedPayload) -> str:
    """Deterministic hash of a confirmed event."""
    raw = json.dumps({
        'p_arrival_utc': c.p_arrival_utc,
        'lat': c.lat,
        'lon': c.lon,
        'mag': c.mag,
        'node_count': c.node_count,
        'node_ids': sorted(c.node_ids),
    }, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


# ── Anchor state ───────────────────────────────────────────────────────────────

class AnchorBuffer:
    """
    Accumulates confirmed events and anchors to Bitcoin every ANCHOR_EVERY events.
    """

    def __init__(self,
                 wif: str = BTC_WIF,
                 network: str = BTC_NETWORK,
                 anchor_every: int = ANCHOR_EVERY):
        self.wif          = wif
        self.network      = network
        self.anchor_every = anchor_every
        self._pending: list[ConfirmedPayload] = []
        self._anchored: list[dict] = []    # {txid, merkle_root, events, ts}

    def add(self, confirmed: ConfirmedPayload) -> Optional[str]:
        """
        Add a confirmed event. Returns txid if an anchor was broadcast, else None.
        Mutates confirmed.anchor_txid on success.
        """
        self._pending.append(confirmed)
        if len(self._pending) >= self.anchor_every:
            return self._anchor()
        return None

    def flush(self) -> Optional[str]:
        """Force anchor whatever is pending, even if below threshold."""
        if self._pending:
            return self._anchor()
        return None

    def _anchor(self) -> Optional[str]:
        if not self.wif:
            logger.warning('OTTO_BTC_WIF not set — skipping anchor')
            return None

        hashes = [_event_hash(c) for c in self._pending]
        root   = _merkle_root(hashes)

        try:
            broadcast_commitment, _ = _load_broadcast()
            txid = broadcast_commitment(root[:64], self.wif, self.network)
        except Exception as e:
            logger.error(f'anchor broadcast failed: {e}')
            return None

        ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        logger.info(f'anchored {len(self._pending)} event(s) — txid={txid} root={root[:16]}...')

        record = {
            'txid':        txid,
            'merkle_root': root,
            'ts':          ts,
            'events':      [c.p_arrival_utc for c in self._pending],
        }
        self._anchored.append(record)

        # Tag each confirmed event with its txid
        for c in self._pending:
            c.anchor_txid = txid

        self._pending.clear()
        return txid

    def anchored_log(self) -> list[dict]:
        return list(self._anchored)
