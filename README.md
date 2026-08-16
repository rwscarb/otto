# otto

A decentralized, open seismic monitoring network.

Anyone can run a node. Nodes detect earthquakes locally using an ML model, publish signed detection events to the Nostr protocol, and the network collectively confirms events through geographically-diverse consensus.

**No central coordinator. No trusted authority. Just physics and math.**

---

## How it works

1. **Node** — runs a local seismic sensor (MEMS accelerometer, geophone, or SeedLink-connected seismometer) and an ML inference model. Detects P-wave arrivals.
2. **Publish** — on detection, the node signs and publishes a `DetectionEvent` to one or more Nostr relays.
3. **Consensus** — nodes (and relay listeners) cluster incoming events by expected P-arrival time across geographic coordinates. When N geographically-diverse nodes agree within a physically-consistent time window, a `ConfirmedEvent` is published.
4. **Anchor** — confirmed events are periodically anchored to Bitcoin via OP_RETURN, producing a tamper-evident public record.

## Incentives

- Nodes accumulate **reputation** from confirmed detections
- Nodes in underserved regions (Pacific, Africa, Indian Ocean) carry higher consensus weight
- Sybil resistance via P-arrival time consistency — fake location claims are detectable by physics

## Status

Early design. Core components:

- [ ] Nostr event schema (`otto/events.py`)
- [ ] Node runner (`otto/node.py`)
- [ ] Consensus engine (`otto/consensus.py`)
- [ ] Reputation system (`otto/reputation.py`)
- [ ] Bitcoin anchor (`otto/anchor.py`)
- [ ] Relay listener / aggregator (`otto/aggregator.py`)

## Related

- [seismic-sensor](https://github.com/rwscarb/seismic-sensor) — the single-node ML seismic detector otto is built on top of
- [btcvm](https://github.com/rwscarb/btcvm) — Bitcoin-clocked VM used for event anchoring
