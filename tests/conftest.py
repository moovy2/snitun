"""Pytest fixtures for SniTun."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
import os
import select
import socket
from threading import Thread
from unittest.mock import patch

import pytest

import snitun
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.crypto import CryptoTransport
from snitun.server.listener_peer import PeerListener
from snitun.server.listener_sni import SNIProxy
from snitun.server.peer import Peer
from snitun.server.peer_manager import PeerManager
from snitun.utils.asyncio import asyncio_timeout

from .server.const_fernet import FERNET_TOKENS

logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session.

    Note: pytest-asyncio 1.x removed the event_loop fixture but we still need it
    for testing sync functions. Otherwise we need to rewrite tons of tests.
    It's restored here so we can do a gradual migration but keep the CI working.
    All the async functions have been updated to use asyncio.get_running_loop().
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@dataclass
class Client:
    """Represent a TCP client object."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    close: asyncio.Event = field(default_factory=asyncio.Event)


@pytest.fixture
def raise_timeout() -> Generator[None, None, None]:
    """Raise timeout on async-timeout."""
    with patch.object(asyncio_timeout, "timeout", side_effect=TimeoutError()):
        yield


@pytest.fixture
async def test_server() -> AsyncGenerator[list[Client], None]:
    """Create a TCP test server."""
    connections = []

    async def process_data(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Read data from client."""
        client = Client(reader, writer)
        connections.append(client)
        await client.close.wait()

    server = await asyncio.start_server(process_data, host="127.0.0.1", port="8866")

    yield connections

    server.close()


@pytest.fixture
async def test_endpoint() -> AsyncGenerator[list[Client], None]:
    """Create a TCP test endpoint."""
    connections = []

    async def process_data(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Read data from client."""
        client = Client(reader, writer)
        connections.append(client)
        await client.close.wait()

    server = await asyncio.start_server(process_data, host="127.0.0.1", port="8822")

    yield connections

    server.close()


@pytest.fixture
async def test_client(test_server: list[Client]) -> AsyncGenerator[Client, None]:
    """Create a TCP test client."""
    reader, writer = await asyncio.open_connection(host="127.0.0.1", port="8866")

    yield Client(reader, writer)

    writer.close()


@pytest.fixture
def test_server_sync(
    event_loop: asyncio.AbstractEventLoop,
) -> Generator[list[socket.socket], None, None]:
    """Create a TCP test server."""
    connections: list[socket.socket] = []
    shutdown = False

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 8366))
    sock.listen(2)
    sock.setblocking(False)

    def _incoming() -> None:
        nonlocal shutdown
        poller = select.epoll()

        poller.register(sock, select.EPOLLIN)
        while not shutdown:
            events = poller.poll(0.1)
            for _, _ in events:
                connection, _ = sock.accept()
                connections.append(connection)

        poller.close()

    runner = Thread(target=_incoming)
    runner.start()

    yield connections

    shutdown = True
    runner.join()
    sock.close()


@pytest.fixture
def test_client_sync(
    test_server_sync: list[socket.socket],
) -> Generator[socket.socket, None, None]:
    """Create a TCP test client."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 8366))

    yield sock

    sock.close()


@pytest.fixture
def test_client_ssl_sync(
    test_server_sync: list[socket.socket],
) -> Generator[socket.socket, None, None]:
    """Create a TCP test client for SSL."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 8366))

    yield sock

    sock.close()


@pytest.fixture
async def multiplexer_server(
    test_server: list[Client],
    test_client: Client,
    crypto_key_iv: tuple[bytes, bytes],
) -> AsyncGenerator[Multiplexer, None]:
    """Create a multiplexer client from server."""
    client = test_server[0]

    async def mock_new_channel(
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Mock new channel."""

    multiplexer = Multiplexer(
        CryptoTransport(*crypto_key_iv),
        client.reader,
        client.writer,
        snitun.PROTOCOL_VERSION,
        mock_new_channel,
    )

    yield multiplexer

    multiplexer.shutdown()
    client.close.set()


@pytest.fixture
async def multiplexer_server_peer_protocol_0(
    test_server: list[Client],
    test_client: Client,
    crypto_key_iv: tuple[bytes, bytes],
) -> AsyncGenerator[Multiplexer, None]:
    """Create a multiplexer client from server with the peer using protocol 0."""
    client = test_server[0]

    async def mock_new_channel(
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Mock new channel."""

    multiplexer = Multiplexer(
        CryptoTransport(*crypto_key_iv),
        client.reader,
        client.writer,
        0,
        mock_new_channel,
    )

    yield multiplexer

    multiplexer.shutdown()
    client.close.set()


@pytest.fixture
async def multiplexer_client(
    test_client: Client,
    crypto_key_iv: tuple[bytes, bytes],
) -> AsyncGenerator[Multiplexer, None]:
    """Create a multiplexer client from server."""

    async def mock_new_channel(
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Mock new channel."""

    multiplexer = Multiplexer(
        CryptoTransport(*crypto_key_iv),
        test_client.reader,
        test_client.writer,
        snitun.PROTOCOL_VERSION,
        mock_new_channel,
    )

    yield multiplexer

    multiplexer.shutdown()


@pytest.fixture
async def peer_manager(multiplexer_server: Multiplexer, peer: Peer) -> PeerManager:
    """Create a localhost peer for tests."""
    manager = PeerManager(FERNET_TOKENS)
    manager._peers[peer.hostname] = peer
    return manager


@pytest.fixture
async def sni_proxy(peer_manager: PeerManager) -> AsyncGenerator[SNIProxy, None]:
    """Create a SNI Proxy."""
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863")
    await proxy.start()

    yield proxy
    await proxy.stop()


@pytest.fixture
async def test_client_ssl(sni_proxy: SNIProxy) -> AsyncGenerator[Client, None]:
    """Create a TCP test client."""
    reader, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    yield Client(reader, writer)

    writer.close()


@pytest.fixture
def crypto_key_iv() -> tuple[bytes, bytes]:
    """Create a key and iv."""
    key = os.urandom(32)
    iv = os.urandom(16)
    return key, iv


@pytest.fixture
async def peer(
    crypto_key_iv: tuple[bytes, bytes],
    multiplexer_server: Multiplexer,
) -> Peer:
    """Init a peer with transport."""
    valid = datetime.now(tz=UTC) + timedelta(days=1)
    peer = Peer(
        "localhost",
        valid,
        os.urandom(32),
        os.urandom(16),
        snitun.PROTOCOL_VERSION,
    )
    peer._crypto = CryptoTransport(*crypto_key_iv)
    peer._multiplexer = multiplexer_server

    return peer


@pytest.fixture
async def peer_listener(
    peer_manager: PeerManager,
    peer: Peer,
) -> AsyncGenerator[PeerListener, None]:
    """Create a Peer listener."""
    listener = PeerListener(peer_manager, "127.0.0.1", "8893")
    await listener.start()

    # Cleanup mock peer
    peer_manager.remove_peer(peer)

    yield listener
    await listener.stop()


@pytest.fixture
async def test_client_peer(peer_listener: PeerListener) -> AsyncGenerator[Client, None]:
    """Create a TCP test client."""
    reader, writer = await asyncio.open_connection(host="127.0.0.1", port="8893")

    yield Client(reader, writer)

    writer.close()
