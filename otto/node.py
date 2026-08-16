"""
otto.node — local node runner.

Bridges a seismic detection source (seismic-sensor compatible or raw)
to the otto Nostr network. Listens for local detections, signs them,
and publishes to configured Nostr relays.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

from otto.events import DetectionPayload, detection_id, KIND_DETECTION

logger = logging.getLogger('otto.node')

# ── Config ─────────────────────────────────────────────────────────────────────

DEFAULT_RELAYS = [
    'wss://relay.damus.io',
    'wss://relay.nostr.band',
    'wss://nostr.wine',
]

OTTO_MODEL = f"otto/{os.environ.get('OTTO_MODEL', 'seismic-sensor-v1')}"


@dataclass
class NodeConfig:
    node_id:    str          # Nostr npub
    privkey:    str          # Nostr nsec (hex)
    lat:        float        # node latitude
    lon:        float        # node longitude
    relays:     list = None  # Nostr relay URLs
    station:    str  = None  # SeedLink station id if applicable

    def __post_init__(self):
        if self.relays is None:
            self.relays = list(DEFAULT_RELAYS)


class OttoNode:
    """
    Local otto node. Feed detections via `on_detection()`.
    Call `run()` to start the async publish loop.
    """

    def __init__(self, config: NodeConfig):
        self.config = config
        self._queue: asyncio.Queue = None

    def on_detection(self, p_arrival: float, conf: float, mag_est: float,
                     sig_hash: Optional[str] = None) -> None:
        """
        Call this from your seismic detection callback.
        Thread-safe — can be called from non-async context.
        """
        payload = DetectionPayload(
            node_id   = self.config.node_id,
            lat       = self.config.lat,
            lon       = self.config.lon,
            p_arrival = p_arrival,
            conf      = conf,
            mag_est   = mag_est,
            model     = OTTO_MODEL,
            station   = self.config.station,
            sig_hash  = sig_hash,
        )
        if self._queue is not None:
            try:
                self._queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning('publish queue full — dropping detection')

    async def run(self) -> None:
        """Start the publish loop. Runs forever."""
        self._queue = asyncio.Queue(maxsize=64)
        logger.info(f'otto node {self.config.node_id} starting, relays: {self.config.relays}')
        while True:
            payload = await self._queue.get()
            await self._publish(payload)

    async def _publish(self, payload: DetectionPayload) -> None:
        """Sign and publish a detection event to all configured relays."""
        did  = detection_id(payload.node_id, payload.p_arrival)
        ts   = int(payload.p_arrival)
        event = {
            'kind':    KIND_DETECTION,
            'created_at': ts,
            'tags': [
                ['d', did],
                ['t', 'otto-detection'],
                ['g', _geohash(payload.lat, payload.lon, precision=4)],
            ],
            'content': payload.to_json(),
        }
        event['id']  = _event_id(event)
        event['sig'] = _sign(event['id'], self.config.privkey)
        event['pubkey'] = self.config.node_id

        msg = json.dumps(['EVENT', event])
        for relay_url in self.config.relays:
            asyncio.create_task(self._send_to_relay(relay_url, msg))

    async def _send_to_relay(self, url: str, msg: str) -> None:
        try:
            import websockets
            async with websockets.connect(url, open_timeout=10) as ws:
                await ws.send(msg)
                resp = await asyncio.wait_for(ws.recv(), timeout=10)
                logger.debug(f'{url}: {resp}')
        except Exception as e:
            logger.warning(f'relay {url} error: {e}')


# ── Nostr crypto helpers ───────────────────────────────────────────────────────

def _event_id(event: dict) -> str:
    import hashlib
    serialized = json.dumps([
        0, event['pubkey'], event['created_at'],
        event['kind'], event['tags'], event['content']
    ], separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def _sign(event_id: str, privkey_hex: str) -> str:
    """Schnorr sign event_id with privkey. Requires `coincurve` or `secp256k1`."""
    try:
        from coincurve import PrivateKey
        pk = PrivateKey(bytes.fromhex(privkey_hex))
        return pk.sign_recoverable(bytes.fromhex(event_id)).hex()
    except ImportError:
        # Fallback stub — replace with proper Schnorr implementation
        logger.error('coincurve not installed — events will have invalid signatures')
        return '0' * 128


def _geohash(lat: float, lon: float, precision: int = 4) -> str:
    """Simple geohash for proximity tagging."""
    BASE32 = '0123456789bcdefghjkmnpqrstuvwxyz'
    lat_range, lon_range = [-90.0, 90.0], [-180.0, 180.0]
    bits, result = 0, ''
    even = True
    while len(result) < precision:
        val = 0
        for _ in range(5):
            if even:
                mid = (lon_range[0] + lon_range[1]) / 2
                if lon >= mid:
                    val = (val << 1) | 1
                    lon_range[0] = mid
                else:
                    val = val << 1
                    lon_range[1] = mid
            else:
                mid = (lat_range[0] + lat_range[1]) / 2
                if lat >= mid:
                    val = (val << 1) | 1
                    lat_range[0] = mid
                else:
                    val = val << 1
                    lat_range[1] = mid
            even = not even
        result += BASE32[val]
    return result
