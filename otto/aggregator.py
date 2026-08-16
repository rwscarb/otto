"""
otto.aggregator — Nostr relay listener and cross-node consensus aggregator.

Subscribes to otto-detection events from all relays, feeds them to the
ConsensusEngine, and publishes ConfirmedEvents when consensus is reached.
"""

import asyncio
import json
import logging
import time
from typing import Optional

from otto.events import DetectionPayload, KIND_DETECTION, KIND_CONFIRMED
from otto.consensus import ConsensusEngine
from otto.reputation import ReputationRegistry
from otto.anchor import AnchorBuffer

logger = logging.getLogger('otto.aggregator')

DEFAULT_RELAYS = [
    'wss://relay.damus.io',
    'wss://relay.nostr.band',
    'wss://nostr.wine',
]

SUBSCRIPTION_FILTER = {
    'kinds': [KIND_DETECTION],
    '#t': ['otto-detection'],
    'since': None,  # filled at runtime
}


class OttoAggregator:
    """
    Listens to Nostr relays for otto detection events, runs consensus,
    and publishes confirmed events.
    """

    def __init__(self,
                 pubkey: str,
                 privkey: str,
                 relays: list = None,
                 reputation_path: Optional[str] = None):
        self.pubkey  = pubkey
        self.privkey = privkey
        self.relays  = relays or list(DEFAULT_RELAYS)
        self.engine  = ConsensusEngine()
        self.rep     = ReputationRegistry(path=reputation_path)
        self.anchor  = AnchorBuffer()
        self._seen: set = set()   # deduplicate event ids across relays

    async def run(self) -> None:
        logger.info(f'otto aggregator starting, watching {len(self.relays)} relays')
        tasks = [self._listen(relay) for relay in self.relays]
        tasks.append(self._confirm_loop())
        await asyncio.gather(*tasks)

    async def _listen(self, relay_url: str) -> None:
        """Subscribe to a relay and feed detections into the consensus engine."""
        import websockets
        sub_id = f'otto-{int(time.time())}'
        filt = dict(SUBSCRIPTION_FILTER)
        filt['since'] = int(time.time()) - 300   # catch last 5 min on connect

        while True:
            try:
                async with websockets.connect(relay_url, open_timeout=15) as ws:
                    await ws.send(json.dumps(['REQ', sub_id, filt]))
                    logger.info(f'subscribed to {relay_url}')
                    async for raw in ws:
                        await self._handle_message(raw)
            except Exception as e:
                logger.warning(f'{relay_url} disconnected: {e} — reconnecting in 30s')
                await asyncio.sleep(30)

    async def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            return
        if not isinstance(msg, list) or msg[0] != 'EVENT':
            return
        event = msg[2] if len(msg) > 2 else None
        if not event or event.get('id') in self._seen:
            return
        self._seen.add(event['id'])

        try:
            payload = DetectionPayload.from_json(event.get('content', '{}'))
            self.engine.ingest(payload)
        except Exception as e:
            logger.debug(f'failed to parse detection: {e}')

    async def _confirm_loop(self) -> None:
        """Drain confirmed events from the engine and publish them."""
        while True:
            await asyncio.sleep(5)
            confirmed = self.engine.drain_confirmed()
            for c in confirmed:
                logger.info(f'CONFIRMED {c.p_arrival_utc} M{c.mag} '
                            f'{c.lat:.2f}/{c.lon:.2f} ({c.node_count} nodes)')
                # Update reputation for contributing nodes
                for node_id in c.node_ids:
                    # Approximate lat/lon from confirmed centroid for now
                    self.rep.record_confirmed(node_id, c.lat, c.lon)
                self.anchor.add(c)
                await self._publish_confirmed(c)

    async def _publish_confirmed(self, confirmed) -> None:
        from otto.events import confirmed_id, KIND_CONFIRMED
        from otto.node import _event_id, _sign
        cid = confirmed_id(confirmed.p_arrival_utc, confirmed.lat, confirmed.lon)
        event = {
            'kind':       KIND_CONFIRMED,
            'created_at': int(time.time()),
            'pubkey':     self.pubkey,
            'tags': [
                ['d', cid],
                ['t', 'otto-confirmed'],
            ],
            'content': confirmed.to_json(),
        }
        event['id']  = _event_id(event)
        event['sig'] = _sign(event['id'], self.privkey)

        import websockets
        msg = json.dumps(['EVENT', event])
        for relay_url in self.relays:
            try:
                async with websockets.connect(relay_url, open_timeout=10) as ws:
                    await ws.send(msg)
            except Exception as e:
                logger.warning(f'failed to publish confirmed to {relay_url}: {e}')
