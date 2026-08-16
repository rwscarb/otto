#!/usr/bin/env python3
"""
Generate an otto node keypair (Nostr-compatible secp256k1).

Usage:
    python tools/generate_keypair.py

Output:
    OTTO_PRIVKEY=<hex>   # store as Fly secret: fly secrets set OTTO_PRIVKEY=...
    OTTO_PUBKEY=<hex>    # safe to store in fly.toml env
"""

import secrets
import sys


def main():
    try:
        from coincurve import PrivateKey
    except ImportError:
        print("pip install coincurve", file=sys.stderr)
        sys.exit(1)

    privkey_bytes = secrets.token_bytes(32)
    privkey_hex   = privkey_bytes.hex()
    pubkey_hex    = PrivateKey(privkey_bytes).public_key.format(compressed=True)[1:].hex()
    # Nostr uses the 32-byte x-only pubkey (strip the 02/03 prefix)

    print(f"\nOTTO_PRIVKEY={privkey_hex}")
    print(f"OTTO_PUBKEY={pubkey_hex}")
    print()
    print("Store OTTO_PRIVKEY as a Fly secret (never commit it):")
    print(f"  fly secrets set OTTO_PRIVKEY={privkey_hex} -a seismic-sensor")
    print()
    print("Add OTTO_PUBKEY, OTTO_LAT, OTTO_LON, OTTO_ENABLED=1 to fly.toml [env]")


if __name__ == '__main__':
    main()
