"""
otto.reputation — node reputation tracking.

Reputation accumulates from confirmed detections. Nodes in underserved
regions carry higher weight. Nodes that contribute false positives
(detections that never get confirmed) are downweighted over time.

Reputation is public and verifiable from the confirmed event log.
"""

import math
import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

# ── Geographic coverage weight ─────────────────────────────────────────────────
# Regions with fewer nodes get a higher reward multiplier.
# Simple proxy: reciprocal of node density in a ~2000km radius.

BASE_REWARD          = 1.0
CONFIRMED_BONUS      = 2.0    # extra reward for contributing to a confirmed event
UNCONFIRMED_PENALTY  = 0.1    # penalty per detection that never confirms
RARITY_MAX_MULT      = 5.0    # max geographic rarity multiplier


@dataclass
class NodeReputation:
    node_id:        str
    lat:            float
    lon:            float
    score:          float = 0.0
    confirmed:      int   = 0     # events this node contributed to confirmed detections
    unconfirmed:    int   = 0     # detections that never confirmed
    last_seen:      float = 0.0
    first_seen:     float = field(default_factory=time.time)


class ReputationRegistry:
    """
    In-memory reputation store. Persist by calling save()/load().
    """

    def __init__(self, path: Optional[str] = None):
        self._nodes: dict[str, NodeReputation] = {}
        self._path = path
        if path and os.path.exists(path):
            self.load(path)

    def record_confirmed(self, node_id: str, lat: float, lon: float) -> None:
        """Call when a node's detection contributed to a confirmed event."""
        rep = self._get_or_create(node_id, lat, lon)
        rarity = self._rarity_multiplier(lat, lon)
        rep.score    += (BASE_REWARD + CONFIRMED_BONUS) * rarity
        rep.confirmed += 1
        rep.last_seen  = time.time()
        self._maybe_save()

    def record_unconfirmed(self, node_id: str, lat: float, lon: float) -> None:
        """Call when a node's detection expired without confirmation."""
        rep = self._get_or_create(node_id, lat, lon)
        rep.score       = max(0.0, rep.score - UNCONFIRMED_PENALTY)
        rep.unconfirmed += 1
        self._maybe_save()

    def get(self, node_id: str) -> Optional[NodeReputation]:
        return self._nodes.get(node_id)

    def leaderboard(self, n: int = 20) -> list[NodeReputation]:
        return sorted(self._nodes.values(), key=lambda r: r.score, reverse=True)[:n]

    def _get_or_create(self, node_id: str, lat: float, lon: float) -> NodeReputation:
        if node_id not in self._nodes:
            self._nodes[node_id] = NodeReputation(node_id=node_id, lat=lat, lon=lon)
        return self._nodes[node_id]

    def _rarity_multiplier(self, lat: float, lon: float) -> float:
        """
        Nodes in regions with fewer registered nodes get a higher multiplier.
        Simple heuristic: count nodes within 2000km, invert.
        """
        RADIUS_KM = 2000.0
        nearby = sum(
            1 for r in self._nodes.values()
            if _haversine_km(lat, lon, r.lat, r.lon) <= RADIUS_KM
        )
        nearby = max(1, nearby)
        mult = 1.0 + (RARITY_MAX_MULT - 1.0) / nearby
        return min(mult, RARITY_MAX_MULT)

    def save(self, path: Optional[str] = None) -> None:
        path = path or self._path
        if not path:
            return
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump([asdict(r) for r in self._nodes.values()], f, indent=2)
        os.replace(tmp, path)

    def load(self, path: str) -> None:
        with open(path) as f:
            rows = json.load(f)
        for row in rows:
            r = NodeReputation(**row)
            self._nodes[r.node_id] = r

    def _maybe_save(self) -> None:
        if self._path:
            self.save()


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))
