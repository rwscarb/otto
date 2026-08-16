"""
otto.consensus — cross-node consensus engine.

Clusters incoming DetectionPayloads by physically-consistent P-arrival time,
accounting for geographic distance between nodes. When N geographically-diverse
nodes agree, emits a ConfirmedPayload.

Geographic diversity is enforced by requiring that contributing nodes span at
least MIN_SPREAD_KM kilometers — prevents Sybil clusters in one location from
gaming consensus.
"""

import math
import time
import collections
from typing import Optional

from otto.events import DetectionPayload, ConfirmedPayload, confirmed_id

# ── Config ────────────────────────────────────────────────────────────────────

CONSENSUS_WINDOW_S  = 120.0   # max spread in P-arrival times across nodes
MIN_NODES           = 3       # minimum contributing nodes for confirmation
MIN_SPREAD_KM       = 1000.0  # minimum geographic spread across contributing nodes
P_VEL_KM_S         = 8.0     # teleseismic P-wave speed for arrival consistency check
MAX_RESIDUAL_S      = 30.0    # max allowed P-arrival residual vs. predicted travel time

# ── Haversine ─────────────────────────────────────────────────────────────────

def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def _geographic_spread_km(nodes: list[DetectionPayload]) -> float:
    """Max pairwise distance between contributing nodes."""
    if len(nodes) < 2:
        return 0.0
    max_d = 0.0
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            d = _haversine_km(nodes[i].lat, nodes[i].lon, nodes[j].lat, nodes[j].lon)
            max_d = max(max_d, d)
    return max_d


def _arrival_consistent(a: DetectionPayload, b: DetectionPayload) -> bool:
    """
    Check whether two P-arrival times are physically consistent given the
    distance between the two nodes. The difference in arrival times cannot
    exceed dist/P_VEL + MAX_RESIDUAL_S.
    """
    dist_km = _haversine_km(a.lat, a.lon, b.lat, b.lon)
    max_diff = dist_km / P_VEL_KM_S + MAX_RESIDUAL_S
    return abs(a.p_arrival - b.p_arrival) <= max_diff


# ── Consensus engine ──────────────────────────────────────────────────────────

class ConsensusEngine:
    """
    Stateful engine. Feed DetectionPayloads via `ingest()`; collect
    ConfirmedPayloads via `drain_confirmed()`.
    """

    def __init__(self,
                 min_nodes: int = MIN_NODES,
                 min_spread_km: float = MIN_SPREAD_KM,
                 window_s: float = CONSENSUS_WINDOW_S):
        self.min_nodes     = min_nodes
        self.min_spread_km = min_spread_km
        self.window_s      = window_s
        self._pending: list[tuple[float, DetectionPayload]] = []   # (ingested_at, payload)
        self._confirmed: list[ConfirmedPayload] = []
        self._fired_ids: set[str] = set()   # confirmed_ids already emitted

    def ingest(self, payload: DetectionPayload) -> None:
        now = time.time()
        self._pending.append((now, payload))
        self._expire(now)
        self._try_confirm(now)

    def drain_confirmed(self) -> list[ConfirmedPayload]:
        out, self._confirmed = self._confirmed, []
        return out

    def _expire(self, now: float) -> None:
        cutoff = now - self.window_s * 2
        self._pending = [(t, p) for t, p in self._pending if t >= cutoff]

    def _try_confirm(self, now: float) -> None:
        cutoff_arr = now - self.window_s
        candidates = [p for _, p in self._pending if p.p_arrival >= cutoff_arr]
        if len(candidates) < self.min_nodes:
            return

        # Cluster by arrival-time consistency
        clusters = self._cluster(candidates)
        for cluster in clusters:
            if len(cluster) < self.min_nodes:
                continue
            spread = _geographic_spread_km(cluster)
            if spread < self.min_spread_km:
                continue

            # Build confirmed event
            mean_arr  = sum(p.p_arrival for p in cluster) / len(cluster)
            mean_lat  = sum(p.lat for p in cluster) / len(cluster)
            mean_lon  = sum(p.lon for p in cluster) / len(cluster)
            mean_mag  = sum(p.mag_est for p in cluster) / len(cluster)
            arr_utc   = _unix_to_utc(mean_arr)
            cid       = confirmed_id(arr_utc, mean_lat, mean_lon)

            if cid in self._fired_ids:
                continue
            self._fired_ids.add(cid)

            confirmed = ConfirmedPayload(
                p_arrival_utc = arr_utc,
                lat           = round(mean_lat, 4),
                lon           = round(mean_lon, 4),
                mag           = round(mean_mag, 2),
                node_count    = len(cluster),
                node_ids      = [p.node_id for p in cluster],
            )
            self._confirmed.append(confirmed)

    def _cluster(self, payloads: list[DetectionPayload]) -> list[list[DetectionPayload]]:
        """Greedy clustering by pairwise arrival consistency."""
        remaining = list(payloads)
        clusters = []
        while remaining:
            seed = remaining.pop(0)
            cluster = [seed]
            still_remaining = []
            for p in remaining:
                if all(_arrival_consistent(p, c) for c in cluster):
                    cluster.append(p)
                else:
                    still_remaining.append(p)
            remaining = still_remaining
            clusters.append(cluster)
        return clusters


def _unix_to_utc(ts: float) -> str:
    import datetime
    return datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%SZ')
