# Kryptex gzip support — Alpha 2

Version `v0.1.0-alpha.2` / package `0.1.0a2` implements Kryptex's [gzip protocol](https://gist.github.com/maxmalysh/eaaf4332dbc5ca99d0a78f24a733fffe) and uses its [documented default difficulty](https://gist.github.com/maxmalysh/f4c29f532e650a114b317e234f1393fb).

## Wire format

The miner sends object-form `mining.authorize` with `wallet`, `agent`, an empty default `password`, and `type: v2`. Its request ID is 3. Only a successful matching reply with `type: v2` enables gzip for that connection. A successful reply without `type` explicitly selects plain compatibility mode; unknown or contradictory negotiation is refused and logged.

The `plain_proof` field contains **base64(gzip(original serialized proof bytes))**. It does not contain gzip of base64 text, raw DEFLATE, or a zlib-wrapped stream. The implementation uses standard gzip with deterministic timestamp zero and level 6, compatible with zlib `wbits=31`. JSON line framing remains uncompressed. Incoming pool jobs are not treated as gzip.

Proof bytes are never edited to improve compression. The existing zero-B/sparse-A construction creates repetitive valid proofs; this update changes their transport only. User and developer pool sessions remain separate. LuckyPool retains its existing plain proof path.

## Connection safety

Each Kryptex connection has separate authorization and encoding state. Encoding captures an immutable authorization epoch and mode; the sending path rechecks that epoch after serialization. Reconnect cannot send an old proof or old codec to a new socket. A revoked authorization or failed send drops the submission and does not increment the submitted counter. Explicit stop can interrupt a blocked send.

## Measured proof payloads

Three genuine production-dimension proofs (M=16384, N=65536, K=4096, rank=128, certificate v3) were generated on M1 Max using an explicitly easy synthetic header. They are offline fixtures, not discovered pool shares. An independent zlib gzip decoder restored each complete stream with no trailing data; original bytes and SHA256 matched, and both original and restored proofs passed the official verifier.

| Fixture | Original bytes | Gzip bytes | Size ratio | Encoding ms |
| --- | ---: | ---: | ---: | ---: |
| 1 | 276161 | 2481 | 111.31x | 1.680 |
| 2 | 276161 | 2548 | 108.38x | 1.747 |
| 3 | 276161 | 2557 | 108.00x | 1.627 |

These are proof-payload reductions, not measured reductions in every network packet, a GPU hashrate improvement, or a revenue gain. Other proofs and hardware can produce different ratios and times.

Reproduce after bootstrap and local self-test:

```sh
.venv/bin/python tools/check_gzip_proof.py
```

## Tests and live scope

- 66 CPU tests passed, including 18 gzip/protocol tests and a real local TCP mock that independently decodes submitted gzip proofs.
- 28 official offline proof checks passed on the Mac build.
- Kryptex's US server explicitly negotiated `gzip-v2`, authorized the account and delivered certificate-v3 jobs during a 180-second mining trial.
- The local protocol-equivalent session rate was approximately 3.906 TH/s; 0 accepted, 0 rejected, 0 submitted. No share was found or submitted during this bounded trial. A live gzip share accepted by Kryptex remains unverified; authorization alone is not share acceptance.

The public [JSON receipt](data/gzip-validation.json) records exact times, hashes and proof sizes. Earlier Alpha 1 acceptance/performance results remain in [release validation](RELEASE_VALIDATION.md); they are not evidence of Alpha 2 gzip-share acceptance.

## Difficulty and waiting for a share

The default difficulty is 2,097,152, corresponding to approximately 9.007e15 work units under Kryptex's published formula. At 3.9 TH/s, the expected interval is approximately 38.5 minutes. Finding a share is random; a short zero-share window does not by itself diagnose a transport failure. Higher difficulty is intended for much larger workers; this release leaves the password empty to retain the pool default. Lower developer-test difficulty requires confirmation from Kryptex.

This update does not change the optional 1% developer contribution or Apache-2.0 license. Pool approval, listing and integration are separate from implementing and testing the protocol.
