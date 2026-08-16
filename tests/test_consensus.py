"""
Tests for otto.consensus — cross-node clustering, Sybil resistance,
geographic diversity enforcement, and arrival-time physics checks.
"""

import math
import time
import pytest

from otto.consensus import ConsensusEngine, _haversine_km, _geographic_spread_km, _arrival_consistent
from otto.events import DetectionPayload


# ── Helpers ───────────────────────────────────────────────────────────────────

def _det(node_id, lat, lon, p_arrival, conf=0.9, mag_est=4.5):
    return DetectionPayload(
        node_id=node_id, lat=lat, lon=lon,
        p_arrival=p_arrival, conf=conf, mag_est=mag_est,
        model='test/v1',
    )


# Real-ish station coordinates for test fixtures
CORVALLIS  = (44.585, -123.304)   # IU.COR — Oregon
HAWAII     = (21.423, -158.015)   # IU.KIP
JAPAN      = (36.546,  138.207)   # IU.MAJO
BOTSWANA   = (-25.015, 25.597)    # GE.LBTB
BRAZIL     = (-10.683, -41.951)   # IU.RCBR
GREECE     = (37.069,   25.531)   # GE.APE

T0 = 1_700_000_000.0  # arbitrary fixed epoch for tests


# ── Unit tests ────────────────────────────────────────────────────────────────

class TestHaversine:
    def test_same_point(self):
        assert _haversine_km(0, 0, 0, 0) == pytest.approx(0.0)

    def test_corvallis_to_hawaii(self):
        d = _haversine_km(*CORVALLIS, *HAWAII)
        assert 4000 < d < 4500   # ~4200 km

    def test_symmetry(self):
        d1 = _haversine_km(*CORVALLIS, *JAPAN)
        d2 = _haversine_km(*JAPAN, *CORVALLIS)
        assert d1 == pytest.approx(d2)


class TestGeographicSpread:
    def test_single_node(self):
        nodes = [_det('a', *CORVALLIS, T0)]
        assert _geographic_spread_km(nodes) == 0.0

    def test_global_spread(self):
        nodes = [
            _det('a', *CORVALLIS, T0),
            _det('b', *BOTSWANA, T0),
        ]
        spread = _geographic_spread_km(nodes)
        assert spread > 10_000   # Corvallis → Botswana ~14,000 km

    def test_nearby_nodes(self):
        # Two stations 50 km apart
        nodes = [
            _det('a', 44.0, -123.0, T0),
            _det('b', 44.5, -123.0, T0),
        ]
        spread = _geographic_spread_km(nodes)
        assert spread < 100


class TestArrivalConsistency:
    def test_same_location_same_time(self):
        a = _det('a', *CORVALLIS, T0)
        b = _det('b', 44.6, -123.3, T0)   # ~70 km away
        assert _arrival_consistent(a, b)

    def test_geographically_consistent(self):
        # ~4200 km apart, P-wave travel time ~525s → arrivals can differ by up to ~555s
        a = _det('a', *CORVALLIS, T0)
        b = _det('b', *HAWAII, T0 + 500)
        assert _arrival_consistent(a, b)

    def test_physically_impossible(self):
        # Same location but arrivals 1000s apart — impossible
        a = _det('a', *CORVALLIS, T0)
        b = _det('b', *CORVALLIS, T0 + 1000)
        assert not _arrival_consistent(a, b)

    def test_too_fast_for_distance(self):
        # ~8000 km apart, arrivals only 10s apart.
        # This IS physically consistent if the epicenter is equidistant between
        # the two stations — the consistency check is upper-bound only.
        # What we CAN assert: arrivals 2000s apart at same location are inconsistent.
        a = _det('a', *CORVALLIS, T0)
        b = _det('b', *CORVALLIS, T0 + 2000)
        assert not _arrival_consistent(a, b)


class TestConsensusEngine:
    def _engine(self, min_nodes=3, min_spread_km=1000):
        return ConsensusEngine(min_nodes=min_nodes, min_spread_km=min_spread_km,
                               window_s=120.0)

    def test_no_confirmation_below_min_nodes(self):
        eng = self._engine(min_nodes=3)
        eng.ingest(_det('a', *CORVALLIS, T0))
        eng.ingest(_det('b', *HAWAII,    T0 + 10))
        assert eng.drain_confirmed() == []

    def test_confirms_with_sufficient_diverse_nodes(self):
        eng = self._engine(min_nodes=3)
        eng.ingest(_det('a', *CORVALLIS, T0))
        eng.ingest(_det('b', *HAWAII,    T0 + 480))   # ~3840km/8km/s
        eng.ingest(_det('c', *JAPAN,     T0 + 870))   # ~6960km/8km/s
        confirmed = eng.drain_confirmed()
        assert len(confirmed) == 1
        c = confirmed[0]
        assert c.node_count == 3
        assert set(c.node_ids) == {'a', 'b', 'c'}

    def test_no_confirmation_insufficient_spread(self):
        """Three nearby nodes should not confirm — Sybil cluster."""
        eng = self._engine(min_nodes=3, min_spread_km=1000)
        # Three stations all within ~100km of Corvallis
        eng.ingest(_det('a', 44.5, -123.3, T0))
        eng.ingest(_det('b', 44.6, -123.1, T0 + 1))
        eng.ingest(_det('c', 44.4, -123.5, T0 + 2))
        assert eng.drain_confirmed() == []

    def test_no_confirmation_inconsistent_arrivals(self):
        """Nodes that are too close but have wildly different arrivals don't cluster."""
        eng = self._engine(min_nodes=3)
        eng.ingest(_det('a', *CORVALLIS, T0))
        eng.ingest(_det('b', *CORVALLIS, T0 + 500))   # same location, 500s later
        eng.ingest(_det('c', *CORVALLIS, T0 + 1000))
        assert eng.drain_confirmed() == []

    def test_no_duplicate_confirmation(self):
        """Same event should not be confirmed twice."""
        eng = self._engine(min_nodes=3)
        for _ in range(2):
            eng.ingest(_det('a', *CORVALLIS, T0))
            eng.ingest(_det('b', *HAWAII,    T0 + 480))
            eng.ingest(_det('c', *JAPAN,     T0 + 870))
        confirmed = eng.drain_confirmed()
        assert len(confirmed) <= 1

    def test_confirmed_payload_fields(self):
        eng = self._engine(min_nodes=3)
        eng.ingest(_det('a', *CORVALLIS, T0, mag_est=5.0))
        eng.ingest(_det('b', *HAWAII,    T0 + 480, mag_est=4.8))
        eng.ingest(_det('c', *JAPAN,     T0 + 870, mag_est=5.2))
        confirmed = eng.drain_confirmed()
        assert len(confirmed) == 1
        c = confirmed[0]
        assert c.mag == pytest.approx((5.0 + 4.8 + 5.2) / 3, abs=0.01)
        assert c.node_count == 3
        assert c.p_arrival_utc.endswith('Z')
        assert c.anchor_txid is None

    def test_two_separate_events(self):
        """Two distinct events in the window should produce two confirmations."""
        eng = self._engine(min_nodes=3)
        # Event 1
        eng.ingest(_det('a1', *CORVALLIS, T0,        mag_est=4.5))
        eng.ingest(_det('b1', *HAWAII,    T0 + 480,  mag_est=4.5))
        eng.ingest(_det('c1', *JAPAN,     T0 + 870,  mag_est=4.5))
        # Event 2 — 300s later, physically consistent offsets
        T1 = T0 + 300
        eng.ingest(_det('a2', *CORVALLIS, T1,        mag_est=5.5))
        eng.ingest(_det('b2', *HAWAII,    T1 + 480,  mag_est=5.5))
        eng.ingest(_det('c2', *JAPAN,     T1 + 870,  mag_est=5.5))
        confirmed = eng.drain_confirmed()
        assert len(confirmed) == 2

    def test_global_stations_confirm(self):
        """Simulate a global event — 5 stations across 5 continents."""
        eng = self._engine(min_nodes=4, min_spread_km=2000)
        base = T0
        for node_id, coords in [
            ('cor',   CORVALLIS),
            ('kip',   HAWAII),
            ('majo',  JAPAN),
            ('lbtb',  BOTSWANA),
            ('rcbr',  BRAZIL),
        ]:
            # Approximate P-arrival based on distance from a fake epicenter at 0,0
            dist = _haversine_km(0, 0, *coords)
            arr  = base + dist / 8.0
            eng.ingest(_det(node_id, *coords, arr))
        confirmed = eng.drain_confirmed()
        assert len(confirmed) == 1
        assert confirmed[0].node_count >= 4
