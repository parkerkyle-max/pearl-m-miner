"""Kryptex's published wire contract; loopback tests do not claim pool acceptance."""
import base64
import gzip
import json
import os
import queue
import socket
import threading
import unittest
from unittest.mock import patch
import zlib

from pearl_metal_miner.stratum.dialect import Job, PoolConnection, ShareResult
from pearl_metal_miner.stratum.kryptex import KryptexDialect
from pearl_metal_miner.stratum.luckypool import LuckyPoolDialect


def ack(kind="v2", **extra):
    data = {"id": 3, "result": True, "error": None}
    if kind is not ...:
        data["type"] = kind
    data.update(extra)
    return json.dumps(data)


def job_line():
    return json.dumps({"method": "mining.notify", "params": {
        "job_id": "job_2097152", "header": bytes(range(76)).hex(),
        "height": 42, "target": "01" + "00" * 31, "cert_version": 3}})


def proof(raw):
    return base64.b64encode(raw).decode("ascii")


def receive_event(connection, kind, msg_id=None):
    while True:
        item = connection.events.get(timeout=5)
        if isinstance(item, kind) and (msg_id is None or item.msg_id == msg_id):
            return item


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    def sendall(self, data):
        self.sent.append(data)

    def shutdown(self, how):
        self.closed = True

    def close(self):
        self.closed = True


class EncodingTests(unittest.TestCase):
    def test_object_authorize_requests_v2_and_default_difficulty(self):
        messages = KryptexDialect().handshake_lines("krxExample123", "mac")
        self.assertEqual(len(messages), 1)
        message = messages[0]
        self.assertEqual(message["id"], 3)
        self.assertEqual(message["method"], "mining.authorize")
        self.assertEqual(message["params"]["wallet"], "krxExample123.mac")
        self.assertEqual(message["params"]["type"], "v2")
        self.assertEqual(message["params"]["password"], "")
        self.assertTrue(message["params"]["agent"].startswith("pearl-m-miner/"))

    def test_gzip_is_over_original_binary_with_wrapper_31(self):
        d = KryptexDialect(); result = d.parse(ack())
        self.assertTrue(result.accepted)
        raw = bytes(range(256)) + bytes(256 * 1024) + b"proof-tail"
        item = d.submit_line(11, "wallet", "worker", "job", proof(raw))
        compressed = base64.b64decode(item["params"]["plain_proof"], validate=True)
        self.assertEqual(compressed[:3], b"\x1f\x8b\x08")
        self.assertEqual(zlib.decompress(compressed, wbits=31), raw)
        self.assertEqual(gzip.decompress(compressed), raw)
        self.assertLess(len(compressed), len(raw) / 100)
        self.assertIn("raw_bytes=" + str(len(raw)), d.submission_note())
        self.assertIn("gzip_bytes=" + str(len(compressed)), d.submission_note())
        self.assertIn("compression_ms=", d.submission_note())
        self.assertEqual(set(item["params"]), {"worker", "job_id", "plain_proof"})
        # A decoder must validate the gzip footer, not merely accept raw deflate.
        with self.assertRaises(zlib.error):
            zlib.decompress(compressed[:-4], wbits=31)
        corrupted = bytearray(compressed); corrupted[-8] ^= 1
        with self.assertRaises(zlib.error):
            zlib.decompress(corrupted, wbits=31)

    def test_incompressible_proof_still_uses_negotiated_gzip(self):
        d = KryptexDialect(); d.parse(ack())
        raw = os.urandom(4096)
        encoded = d.submit_line(11, "w", "x", "job", proof(raw))["params"]["plain_proof"]
        self.assertEqual(gzip.decompress(base64.b64decode(encoded)), raw)

    def test_gzip_fixture_is_deterministic_and_not_base64_text_compressed(self):
        d = KryptexDialect(); d.parse(ack())
        raw = b"\x00\x01\xfe\xff" * 10
        first = d.submit_line(11, "w", "x", "job", proof(raw))["params"]["plain_proof"]
        second = d.submit_line(12, "w", "x", "job", proof(raw))["params"]["plain_proof"]
        self.assertEqual(first, second)
        self.assertEqual(base64.b64decode(first)[4:8], bytes(4))
        self.assertEqual(gzip.decompress(base64.b64decode(first)), raw)
        self.assertNotEqual(gzip.decompress(base64.b64decode(first)), proof(raw).encode())

    def test_missing_type_success_is_explicit_plain_fallback(self):
        d = KryptexDialect(); self.assertTrue(d.parse(ack(...)).accepted)
        raw = proof(b"not gzip")
        self.assertEqual(d.proof_encoding, "plain-v1")
        self.assertEqual(d.submit_line(11, "w", "x", "j", raw)["params"]["plain_proof"], raw)
        self.assertIsNone(d.submission_note())

    def test_no_work_or_submission_before_matching_authorization(self):
        for reply in (None, ack(id=1), ack(id="3"), ack(id=3.0), ack(id=True)):
            with self.subTest(reply=reply):
                d = KryptexDialect()
                if reply is not None: d.parse(reply)
                self.assertIsNone(d.proof_encoding)
                self.assertIsNone(d.parse(job_line()))
                with self.assertRaises(RuntimeError):
                    d.submit_line(11, "w", "x", "j", proof(b"raw"))

    def test_bad_authorization_is_terminal_for_that_connection(self):
        for reply in (ack("v3"), ack(None), ack(""), ack(result=False),
                      ack(result=1), ack(result="true"), ack(error={"code": 1}),
                      json.dumps({"id": 3, "type": "v2"})):
            with self.subTest(reply=reply):
                d = KryptexDialect(); result = d.parse(reply)
                self.assertEqual(result.msg_id, 3); self.assertFalse(result.accepted)
                self.assertIsNone(d.proof_encoding)
                self.assertFalse(d.parse(ack()).accepted)
                with self.assertRaises(RuntimeError):
                    d.submit_line(11, "w", "x", "j", proof(b"raw"))

    def test_duplicate_ack_cannot_change_the_session_mode(self):
        d = KryptexDialect(); d.parse(ack())
        self.assertIsNone(d.parse(ack()))
        self.assertFalse(d.parse(ack(...)).accepted)
        self.assertIsNone(d.proof_encoding)
        with self.assertRaises(RuntimeError): d.submit_line(11, "w", "x", "j", "AA==")

    def test_reconnect_has_fresh_negotiation_state(self):
        old = KryptexDialect(); old.parse(ack())
        new = old.for_session()
        self.assertIsNot(old, new); self.assertIsNone(new.proof_encoding)
        old.parse(ack(...))
        self.assertIsNone(new.proof_encoding)
        self.assertTrue(new.parse(ack()).accepted)

    def test_invalid_base64_is_not_submitted_as_gzip(self):
        d = KryptexDialect(); d.parse(ack())
        for value in ("not base64!", "AA==\n", "🤖"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                d.submit_line(11, "w", "x", "j", value)

    def test_luckypool_wire_format_unchanged(self):
        d = LuckyPoolDialect(); p = proof(b"raw")
        self.assertIs(d.for_session(), d)
        self.assertEqual(d.handshake_lines("wallet", "worker")[0]["id"], 2)
        result = d.submit_line(11, "wallet", "worker", "job", p)
        self.assertEqual(result["params"], {"wallet": "wallet", "worker": "worker", "job_id": "job", "plain_proof": p})


class ConnectionTests(unittest.TestCase):
    def connection(self, dialect=None):
        return PoolConnection(dialect or KryptexDialect(), "127.0.0.1", 0,
                              "krxExample123", "mac", log=lambda message: None)

    def test_old_reader_auth_cannot_authorize_or_enqueue_into_new_session(self):
        entered = threading.Event(); release = threading.Event()
        class Delayed(KryptexDialect):
            def parse(self, line):
                entered.set()
                if not release.wait(5): raise RuntimeError("test timeout")
                return super().parse(line)
        old_dialect = Delayed(); c = self.connection(old_dialect)
        reader_sock, sender_sock = socket.socketpair()
        new_sock = FakeSocket()
        c._sock = reader_sock; c.generation = 1
        thread = threading.Thread(target=c._reader, args=(reader_sock, old_dialect), daemon=True)
        thread.start(); sender_sock.sendall((ack() + "\n").encode())
        try:
            self.assertTrue(entered.wait(5))
            with c._session_lock:
                c._sock = new_sock; c.dialect = KryptexDialect(); c.generation = 2
            release.set(); thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(c.events.empty()); self.assertFalse(c.dead.is_set())
            self.assertIsNone(c.dialect.proof_encoding)
        finally:
            release.set(); c.close(); reader_sock.close(); sender_sock.close()

    def test_compression_overlapping_reconnect_never_uses_new_socket(self):
        entered = threading.Event(); release = threading.Event()
        class Delayed(KryptexDialect):
            def submit_line(self, *args):
                entered.set()
                if not release.wait(5): raise RuntimeError("test timeout")
                return super().submit_line(*args)
        d = Delayed(); d.parse(ack()); c = self.connection(d)
        old, new = FakeSocket(), FakeSocket(); c._sock = old
        outcome = []
        thread = threading.Thread(target=lambda: outcome.append(c.submit("job", proof(b"raw"))), daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            with c._session_lock:
                c._sock = new; c.dialect = KryptexDialect(); c.dialect.parse(ack(...))
            release.set(); thread.join(5)
            self.assertFalse(thread.is_alive()); self.assertEqual(outcome, [None])
            self.assertFalse(old.sent); self.assertFalse(new.sent); self.assertFalse(c.dead.is_set())
        finally: release.set(); c.close()

    def test_failed_and_closed_socket_never_reports_a_submitted_id(self):
        class Failed(FakeSocket):
            def sendall(self, data): raise OSError("connection lost")
        d = KryptexDialect(); d.parse(ack()); c = self.connection(d)
        self.assertIsNone(c.submit("job", proof(b"raw")))
        c._sock = Failed(); c.dead.clear()
        self.assertIsNone(c.submit("job", proof(b"raw"))); self.assertTrue(c.dead.is_set())

    def test_contradictory_auth_during_compression_drops_without_raw_fallback(self):
        entered = threading.Event(); release = threading.Event()
        compress = gzip.compress
        compressed_messages = []
        def delayed(raw, **kwargs):
            entered.set()
            if not release.wait(5): raise RuntimeError("test timeout")
            result = compress(raw, **kwargs); compressed_messages.append(result)
            return result
        d = KryptexDialect(); d.parse(ack()); c = self.connection(d)
        c._sock = FakeSocket(); result, errors = [], []
        raw = bytes(32768) + b"unchanged-original-proof"
        def submit():
            try: result.append(c.submit("job", proof(raw)))
            except BaseException as error: errors.append(error)
        with patch("pearl_metal_miner.stratum.kryptex.gzip.compress", side_effect=delayed):
            thread = threading.Thread(target=submit, daemon=True); thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertFalse(d.parse(ack(...)).accepted)
                release.set(); thread.join(5)
                self.assertFalse(thread.is_alive()); self.assertFalse(errors, repr(errors))
                self.assertEqual(result, [None]); self.assertFalse(c._sock.sent)
                self.assertEqual(len(compressed_messages), 1)
                self.assertEqual(gzip.decompress(compressed_messages[0]), raw)
                self.assertFalse(d.submission_guard()())
            finally: release.set(); c.close()

    def test_close_interrupts_blocked_send_without_waiting_for_send_lock(self):
        entered = threading.Event(); shutdown = threading.Event()
        class Blocked(FakeSocket):
            def sendall(self, data):
                entered.set(); shutdown.wait(5); raise OSError("closed")
            def shutdown(self, how): shutdown.set()
        d = KryptexDialect(); d.parse(ack()); c = self.connection(d); c._sock = Blocked()
        result = []
        thread = threading.Thread(target=lambda: result.append(c.submit("job", proof(b"raw"))), daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(5)); c.close(); thread.join(5)
            self.assertFalse(thread.is_alive()); self.assertEqual(result, [None])
        finally: shutdown.set(); c.close()

    def test_old_send_failure_cannot_kill_a_replacement_session(self):
        entered = threading.Event(); release = threading.Event()
        class DelayedFailure(FakeSocket):
            def sendall(self, data):
                entered.set(); release.wait(5); raise OSError("old route failed")
        d = KryptexDialect(); d.parse(ack()); c = self.connection(d); c._sock = DelayedFailure()
        result = []
        thread = threading.Thread(target=lambda: result.append(c.submit("job", proof(b"raw"))), daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            with c._session_lock:
                c._sock = FakeSocket(); c.dialect = KryptexDialect()
            release.set(); thread.join(5)
            self.assertFalse(thread.is_alive()); self.assertEqual(result, [None])
            self.assertFalse(c.dead.is_set()); self.assertFalse(c._sock.sent)
        finally: release.set(); c.close()

    def test_local_tcp_negotiates_gzip_and_reconnect_plain_without_leakage(self):
        raw = b"synthetic-proof-prefix" + bytes(128 * 1024) + bytes(range(256))
        errors, received, logs = [], [], []
        listener = socket.socket(); listener.bind(("127.0.0.1", 0)); listener.listen(2); listener.settimeout(5)
        c = PoolConnection(KryptexDialect(), "127.0.0.1", listener.getsockname()[1],
                           "krxExample123", "mac", log=logs.append)
        def serve():
            try:
                for mode in ("v2", ...):
                    client, _ = listener.accept()
                    with client:
                        client.settimeout(5)
                        with client.makefile("rwb") as stream:
                            auth = json.loads(stream.readline())
                            self.assertEqual(auth["params"]["type"], "v2")
                            self.assertEqual(auth["params"]["wallet"], "krxExample123.mac")
                            payload = (ack(mode) + "\n" + job_line() + "\n").encode()
                            stream.write(payload[:7]); stream.flush()
                            stream.write(payload[7:]); stream.flush()
                            submit = json.loads(stream.readline())
                            data = base64.b64decode(submit["params"]["plain_proof"], validate=True)
                            self.assertEqual(zlib.decompress(data, 31) if mode == "v2" else data, raw)
                            received.append((mode, len(data)))
                            stream.write((json.dumps({"id": submit["id"], "result": True, "error": None}) + "\n").encode()); stream.flush()
            except BaseException as error: errors.append(error)
        server = threading.Thread(target=serve, daemon=True); server.start()
        try:
            for encoding in ("gzip-v2", "plain-v1"):
                c.connect()
                self.assertTrue(receive_event(c, ShareResult, 3).accepted)
                job = receive_event(c, Job); self.assertEqual(job.session_generation, c.generation)
                self.assertEqual(c.dialect.proof_encoding, encoding)
                msg_id = c.submit(job.job_id, proof(raw)); self.assertIsInstance(msg_id, int)
                self.assertTrue(receive_event(c, ShareResult, msg_id).accepted)
                c.close()
            server.join(5); self.assertFalse(server.is_alive())
            self.assertFalse(errors, repr(errors)); self.assertEqual(len(received), 2)
            self.assertLess(received[0][1], len(raw)); self.assertEqual(received[1][1], len(raw))
            self.assertTrue(any("proof encoding negotiated: gzip-v2" in line for line in logs))
            self.assertTrue(any("proof encoding negotiated: plain-v1" in line for line in logs))
            notes = [line for line in logs if "compression_ms=" in line]
            self.assertEqual(len(notes), 1); self.assertNotIn("krxExample123", notes[0])
        finally:
            c.close(); listener.close(); server.join(5)


if __name__ == "__main__": unittest.main()
