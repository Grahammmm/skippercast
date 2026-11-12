"""The AIS WebSocket handshake requires a real ``Upgrade`` token in Connection (RFC 6455 §4.1).

Offline only: synthetic response bytes go to the real ``handshake_response`` through
an in-memory StreamReader, using the public RFC 6455 worked-example key and accept value.
"""
import asyncio
import unittest

from skippercast.fleet.ais import ws

KEY = "dGhlIHNhbXBsZSBub25jZQ=="
ACCEPT = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
MESSAGE = "response is not a WebSocket upgrade"


def response(connection: str | None = "Upgrade", *, status="101 Switching Protocols", upgrade="websocket",
             accept=ACCEPT, extra=""):
    lines = [f"HTTP/1.1 {status}", f"Upgrade: {upgrade}"]
    if connection is not None:
        lines.append(f"Connection: {connection}")
    lines.append(f"Sec-WebSocket-Accept: {accept}")
    return ("\r\n".join(lines) + "\r\n" + extra + "\r\n").encode("latin-1")


def check(raw):
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(raw)
        reader.feed_eof()
        await ws.handshake_response(reader, KEY)
    asyncio.run(run())


class ConnectionTokenTests(unittest.TestCase):
    def test_connection_lookalikes_are_refused(self):
        for value in ("notupgrade", "upgraded", "x-upgrade-x", '"upgrade"', "up grade", "",
                      "keep-alive", "notupgrade, upgraded", "keep-alive, x-upgrade-x", None):
            with self.subTest(connection=value):
                with self.assertRaises(ws.HandshakeError) as caught:
                    check(response(value))
                self.assertEqual(str(caught.exception), MESSAGE)

    def test_real_upgrade_token_survives_case_lists_and_whitespace(self):
        for value in ("Upgrade", "upgrade", "uPgRaDe", "keep-alive, Upgrade", "Upgrade, keep-alive",
                      " \t Upgrade \t ", "keep-alive ,\tUPGRADE", ",, Upgrade,", "foo-bar, Upgrade, baz"):
            with self.subTest(connection=value):
                check(response(value))
        check(response("Upgrade").replace(b"Connection:", b"CONNECTION:"))

    def test_token_presence_not_suffix_or_prefix(self):
        with self.assertRaises(ws.HandshakeError):
            check(response("keep-alive, x-upgrade-x"))
        check(response("notupgrade, Upgrade"))

    def test_neighboring_handshake_gates_still_refuse(self):
        for name, raw in (("upgrade", response(upgrade="h2c")),
                          ("accept", response(accept="wrong=")),
                          ("status", response(status="401 Unauthorized")),
                          ("extension", response(extra="Sec-WebSocket-Extensions: permessage-deflate\r\n"))):
            with self.subTest(gate=name):
                with self.assertRaises(ws.HandshakeError):
                    check(raw)


if __name__ == "__main__":
    unittest.main()
