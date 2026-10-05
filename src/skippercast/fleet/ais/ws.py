"""A minimal WebSocket client for the AIS listener (RFC 6455, standard library only).

The listener needs one long-lived ``wss://`` connection that sends a single
subscription frame and then reads messages, so a full WebSocket library is not
worth a dependency: this client does the opening handshake, client-masked text
frames out, and text, binary, continuation, ping, pong and close frames in. No
extensions (``permessage-deflate``) are negotiated, so a frame with an RSV bit
set is a protocol error.

Connection policy follows ``skippercast.http``: ``wss`` only, the host is
resolved once and every address must be public, the socket goes to that checked
address while TLS verifies the certificate for the hostname (SNI), with
``http.tls_context()`` (the OS trust store through ``truststore`` when
installed). HTTP proxies are not supported; the listener runs on the data
runner, which reaches the internet directly.

``connect`` returns a ``WebSocket`` with ``send(text)``, ``recv()`` (``str`` for
text, ``bytes`` for binary messages) and ``close()``. ``recv`` raises
``ConnectionClosed`` when the peer closes or the stream ends.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import os
import socket
import struct
from urllib.parse import urlsplit

__all__ = ["ConnectionClosed", "HandshakeError", "ProtocolError", "WebSocket", "connect", "accept_key",
           "encode_frame", "MAX_MESSAGE_BYTES"]

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE_BYTES = 1 << 20          # an AIS envelope is about 1 KB
MAX_HEADER_BYTES = 16 * 1024
OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


class ConnectionClosed(ConnectionError):
    """The peer closed the connection (``code`` is the close code, or ``None``) or the stream ended."""

    def __init__(self, code: int | None = None, reason: str = ""):
        super().__init__(f"websocket closed ({code if code is not None else 'no close frame'}){': ' + reason if reason else ''}")
        self.code = code
        self.reason = reason


class HandshakeError(ConnectionError):
    """The server did not accept the WebSocket upgrade."""


class ProtocolError(ConnectionError):
    """The server sent a frame this client must reject (RFC 6455 section 7.1.7)."""


def accept_key(key: str) -> str:
    """The ``Sec-WebSocket-Accept`` value a server must return for ``key``."""
    return base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")


def encode_frame(opcode: int, payload: bytes, mask: bytes | None = None, fin: bool = True) -> bytes:
    """One frame; client frames are always masked (``mask`` is four bytes, random when ``None``)."""
    mask = os.urandom(4) if mask is None else mask
    if len(mask) != 4:
        raise ValueError("a frame mask is four bytes")
    head = bytes([(0x80 if fin else 0) | opcode])
    length = len(payload)
    if length < 126:
        head += bytes([0x80 | length])
    elif length < 1 << 16:
        head += bytes([0x80 | 126]) + struct.pack("!H", length)
    else:
        head += bytes([0x80 | 127]) + struct.pack("!Q", length)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return head + mask + masked


class WebSocket:
    """An open client connection over an asyncio stream pair."""

    def __init__(self, reader: asyncio.StreamReader, writer, max_size: int = MAX_MESSAGE_BYTES):
        self._reader = reader
        self._writer = writer
        self._max_size = max_size
        self._closed = False

    async def send(self, text: str) -> None:
        if self._closed:
            raise ConnectionClosed(None, "send after close")
        self._writer.write(encode_frame(OP_TEXT, text.encode("utf-8")))
        await self._writer.drain()

    async def _frame(self) -> tuple[bool, int, bytes]:
        try:
            first, second = await self._reader.readexactly(2)
            if first & 0x70:
                raise ProtocolError("reserved bits set without a negotiated extension")
            if second & 0x80:
                raise ProtocolError("server frames must not be masked")
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", await self._reader.readexactly(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", await self._reader.readexactly(8))[0]
            opcode = first & 0x0F
            if opcode >= 0x8 and (length > 125 or not first & 0x80):
                raise ProtocolError("control frames are unfragmented and at most 125 bytes")
            if length > self._max_size:
                raise ProtocolError(f"frame of {length} bytes is over the {self._max_size}-byte limit")
            payload = await self._reader.readexactly(length) if length else b""
        except asyncio.IncompleteReadError:
            self._closed = True
            raise ConnectionClosed(None, "stream ended") from None
        return bool(first & 0x80), opcode, payload

    async def recv(self) -> str | bytes:
        """The next data message; answers pings and the close handshake on the way."""
        if self._closed:
            raise ConnectionClosed(None, "recv after close")
        parts: list[bytes] = []
        kind = None
        while True:
            fin, opcode, payload = await self._frame()
            if opcode == OP_PING:
                self._writer.write(encode_frame(OP_PONG, payload))
                await self._writer.drain()
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else None
                reason = payload[2:].decode("utf-8", errors="replace")
                await self._shutdown(payload[:2])
                raise ConnectionClosed(code, reason)
            if opcode in (OP_TEXT, OP_BINARY):
                if kind is not None:
                    raise ProtocolError("a new message started before the last one finished")
                kind = opcode
            elif opcode == OP_CONT:
                if kind is None:
                    raise ProtocolError("continuation frame without a message")
            else:
                raise ProtocolError(f"unknown opcode {opcode:#x}")
            parts.append(payload)
            if sum(len(p) for p in parts) > self._max_size:
                raise ProtocolError(f"message over the {self._max_size}-byte limit")
            if fin:
                data = b"".join(parts)
                if kind == OP_TEXT:
                    try:
                        return data.decode("utf-8")
                    except UnicodeDecodeError:
                        raise ProtocolError("text message is not UTF-8") from None
                return data

    async def _shutdown(self, code: bytes = b"\x03\xe8") -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._writer.write(encode_frame(OP_CLOSE, code))
            await self._writer.drain()
        except (ConnectionError, OSError, RuntimeError):
            pass
        finally:
            self._writer.close()

    async def close(self) -> None:
        """Send a normal close frame and drop the transport (no wait for the server's reply)."""
        await self._shutdown()


async def _resolve_public(host: str, port: int) -> list[tuple]:
    from ...http import public_address   # the shared policy (engineering audit finding A38)

    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not infos:
        raise OSError(f"{host}: no addresses")
    for info in infos:
        if not public_address(ipaddress.ip_address(info[4][0])):
            raise HandshakeError(f"{host} resolves to a non-public address")
    return infos


async def connect(url: str, *, open_timeout: float = 15.0, max_size: int = MAX_MESSAGE_BYTES,
                  ssl_context=None) -> WebSocket:
    """Open ``url`` (``wss://`` only) and complete the opening handshake."""
    from ...http import tls_context

    parts = urlsplit(url)
    if parts.scheme != "wss" or not parts.hostname:
        raise ValueError("the AIS listener connects to wss:// URLs only")
    host, port = parts.hostname, parts.port or 443
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")

    async def opening() -> WebSocket:
        infos = await _resolve_public(host, port)
        family, _, _, _, address = infos[0]
        reader, writer = await asyncio.open_connection(
            address[0], address[1], family=family, ssl=ssl_context or tls_context(), server_hostname=host)
        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            writer.write((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                          f"User-Agent: SkipperCast fleet AIS listener\r\n\r\n").encode("ascii"))
            await writer.drain()
            await handshake_response(reader, key)
        except BaseException:
            writer.close()
            raise
        return WebSocket(reader, writer, max_size)

    return await asyncio.wait_for(opening(), open_timeout)


async def handshake_response(reader: asyncio.StreamReader, key: str) -> None:
    """Read and check the server's ``101 Switching Protocols`` response to ``key``."""
    try:
        head = await reader.readuntil(b"\r\n\r\n")
    except asyncio.IncompleteReadError:
        raise HandshakeError("connection closed during the handshake") from None
    except asyncio.LimitOverrunError:
        raise HandshakeError("handshake response headers are too long") from None
    if len(head) > MAX_HEADER_BYTES:
        raise HandshakeError("handshake response headers are too long")
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0].split(" ", 2)
    if len(status) < 2 or status[1] != "101":
        raise HandshakeError(f"upgrade refused: {lines[0][:80]}")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    if headers.get("upgrade", "").lower() != "websocket" or "upgrade" not in headers.get("connection", "").lower():
        raise HandshakeError("response is not a WebSocket upgrade")
    if headers.get("sec-websocket-accept") != accept_key(key):
        raise HandshakeError("Sec-WebSocket-Accept does not match the key")
    if headers.get("sec-websocket-extensions"):
        raise HandshakeError("server negotiated an extension this client did not offer")
