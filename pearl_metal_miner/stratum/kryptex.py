"""Kryptex's negotiated Pearl proof encoding.

Specification: https://gist.github.com/maxmalysh/eaaf4332dbc5ca99d0a78f24a733fffe
Difficulty: https://gist.github.com/maxmalysh/f4c29f532e650a114b317e234f1393fb

Request type=v2 in object-form authorization. A successful matching reply
with type=v2 commits this session to base64(gzip(raw PlainProof bytes)),
using the gzip wrapper (zlib wbits=31), not a zlib or raw-deflate wrapper.
A successful reply without type selects the documented uncompressed form.
Unknown/contradictory negotiation is rejected; no payload sniffing is used.

This module never changes proof construction to obtain compression. The
locally verified original proof must round-trip byte for byte.
"""

from __future__ import annotations

import base64
import gzip
import json
import threading
import time

from .. import __version__
from .dialect import Dialect, Job, ShareResult


class KryptexDialect(Dialect):
    name = "kryptex"
    miner_chooses_params = True

    def __init__(self):
        self.proof_encoding = None
        self._authorization = "pending"
        self._authorization_epoch = 0
        self._authorization_lock = threading.Lock()
        self._submission_note = None
        self._submission_snapshot = None

    def for_session(self):
        # Readers and submitters retain their own instance across reconnect.
        return type(self)()

    def protocol_status(self):
        with self._authorization_lock:
            return self.proof_encoding

    def submission_note(self):
        return self._submission_note

    def submission_guard(self):
        # Capture the encoding used for this message, not a later mutable mode.
        snapshot = self._submission_snapshot
        def current():
            with self._authorization_lock:
                return (self._authorization == "accepted" and snapshot is not None
                        and snapshot == (self._authorization_epoch, self.proof_encoding))
        return current

    def handshake_lines(self, address, worker):
        return [
            {"id": 3, "method": "mining.authorize",
             "params": {"wallet": f"{address}.{worker}",
                        "agent": f"pearl-m-miner/{__version__}",
                        "password": "", "type": "v2"}},
        ]

    def parse(self, line: str):
        msg = json.loads(line)
        if not isinstance(msg, dict):
            raise ValueError("Kryptex message must be a JSON object")
        # IDs are JSON integers; booleans/floats/strings cannot authenticate.
        msg_id = msg.get("id")
        if type(msg_id) is int and msg_id == 3:
            ok = msg.get("result") is True and not msg.get("error")
            encoding = ("gzip-v2" if msg.get("type") == "v2" else
                        "plain-v1" if "type" not in msg else None)
            with self._authorization_lock:
                if not ok or encoding is None or self._authorization == "refused":
                    self._authorization_epoch += 1
                    self._authorization = "refused"
                    self.proof_encoding = None
                    return ShareResult(msg_id=3, accepted=False, raw=line)
                if self._authorization == "accepted":
                    if encoding == self.proof_encoding:
                        return None  # identical duplicate acknowledgement
                    self._authorization_epoch += 1
                    self._authorization = "refused"
                    self.proof_encoding = None
                    return ShareResult(msg_id=3, accepted=False, raw=line)
                self._authorization_epoch += 1
                self._authorization = "accepted"
                self.proof_encoding = encoding
                return ShareResult(msg_id=3, accepted=True, raw=line)
        if msg.get("method") == "mining.notify":
            with self._authorization_lock:
                if self._authorization != "accepted":
                    return None  # never mine before the session encoding is known
            p = msg["params"]
            return Job(
                job_id=str(p["job_id"]),
                header_bytes=bytes.fromhex(p["header"]),
                target=int(p["target"], 16),
                height=int(p.get("height", 0)),
                cert_version=int(p.get("cert_version", 2)),
            )
        if "result" in msg and type(msg_id) is int:
            ok = msg.get("result") is True and not msg.get("error")
            return ShareResult(msg_id=msg_id, accepted=ok, raw=line)
        return None

    def submit_line(self, msg_id, address, worker, job_id, proof_b64):
        with self._authorization_lock:
            if self._authorization != "accepted" or self.proof_encoding is None:
                raise RuntimeError("Kryptex proof encoding is not authorized for this session")
            encoding = self.proof_encoding
            self._submission_snapshot = (self._authorization_epoch, encoding)
        self._submission_note = None
        # No lock is held while compressing. A contradictory reply can revoke
        # authorization, but can never turn this captured v2 proof into raw data.
        if encoding == "gzip-v2":
            raw_proof = base64.b64decode(proof_b64, validate=True)
            started = time.perf_counter()
            compressed = gzip.compress(raw_proof, compresslevel=6, mtime=0)
            elapsed_ms = (time.perf_counter() - started) * 1000
            proof_b64 = base64.b64encode(compressed).decode("ascii")
            self._submission_note = (f"gzip proof raw_bytes={len(raw_proof)} "
                                     f"gzip_bytes={len(compressed)} "
                                     f"compression_ms={elapsed_ms:.3f}")
        return {"id": msg_id, "method": "mining.submit",
                "params": {"worker": f"{address}.{worker}", "job_id": job_id,
                           "plain_proof": proof_b64}}
