"""
otto.events — Nostr event schema for otto detection and confirmation events.

Otto uses two custom Nostr event kinds:
  KIND_DETECTION  = 30078  (NIP-78 arbitrary application data)
  KIND_CONFIRMED  = 30079

DetectionEvent (published by individual nodes):
{
  "kind": 30078,
  "content": "<json payload>",
  "tags": [
    ["d", "<unique detection id>"],
    ["t", "otto-detection"],
    ["g", "<geohash of node location>"]
  ]
}

Payload schema:
{
  "version":    1,
  "node_id":    "<npub>",
  "lat":        float,
  "lon":        float,
  "p_arrival":  float,          # unix timestamp of estimated P-wave arrival
  "conf":       float,          # model confidence 0-1
  "mag_est":    float,          # local magnitude estimate
  "model":      str,            # model name + version
  "station":    str | null,     # SeedLink station id if applicable, else null
  "sig_hash":   str             # sha256 of raw waveform window (for cross-validation)
}

ConfirmedEvent (published by consensus aggregators):
{
  "kind": 30079,
  "content": "<json payload>",
  "tags": [
    ["d", "<confirmed event id>"],
    ["t", "otto-confirmed"],
    ["e", "<detection event id 1>"],
    ["e", "<detection event id 2>"],
    ...
  ]
}

Payload schema:
{
  "version":       1,
  "p_arrival_utc": str,         # ISO8601 consensus P-arrival
  "lat":           float,       # estimated epicenter latitude
  "lon":           float,       # estimated epicenter longitude
  "mag":           float,       # consensus magnitude
  "node_count":    int,         # number of contributing nodes
  "node_ids":      list[str],   # npubs of contributing nodes
  "usgs_id":       str | null,  # matched USGS event id if available
  "anchor_txid":   str | null   # Bitcoin txid of OP_RETURN anchor
}
"""

import json
import hashlib
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

KIND_DETECTION = 30078
KIND_CONFIRMED = 30079

OTTO_VERSION = 1


@dataclass
class DetectionPayload:
    node_id:   str
    lat:       float
    lon:       float
    p_arrival: float
    conf:      float
    mag_est:   float
    model:     str
    station:   Optional[str] = None
    sig_hash:  Optional[str] = None
    version:   int = OTTO_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(',', ':'))

    @classmethod
    def from_json(cls, s: str) -> 'DetectionPayload':
        d = json.loads(s)
        d.pop('version', None)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ConfirmedPayload:
    p_arrival_utc: str
    lat:           float
    lon:           float
    mag:           float
    node_count:    int
    node_ids:      list
    usgs_id:       Optional[str] = None
    anchor_txid:   Optional[str] = None
    version:       int = OTTO_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(',', ':'))


def detection_id(node_id: str, p_arrival: float) -> str:
    """Deterministic detection id — hash of node_id + p_arrival."""
    raw = f"{node_id}:{p_arrival:.3f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def confirmed_id(p_arrival_utc: str, lat: float, lon: float) -> str:
    """Deterministic confirmed event id."""
    raw = f"{p_arrival_utc}:{lat:.4f}:{lon:.4f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
