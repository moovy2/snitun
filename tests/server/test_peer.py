"""Test a Peer object."""

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import os

import pytest

import snitun
from snitun.exceptions import SniTunChallengeError
from snitun.multiplexer.crypto import CryptoTransport
from snitun.multiplexer.message import CHANNEL_FLOW_PING
from snitun.server.peer import Peer

from ..conftest import Client


def test_init_peer() -> None:
    """Test simple init of peer."""
    valid = datetime.now(tz=UTC) + timedelta(days=1)
    peer = Peer(
        "localhost",
        valid,
        os.urandom(32),
        os.urandom(16),
        snitun.PROTOCOL_VERSION,
        alias="localhost.custom",
    )

    assert peer.is_valid
    assert peer.hostname == "localhost"
    assert peer.multiplexer is None
    assert peer.alias == "localhost.custom"


async def test_init_peer_multiplexer(
    test_client: Client,
    test_server: list[Client],
) -> None:
    """Test setup multiplexer."""
    loop = asyncio.get_running_loop()
    client = test_server[0]
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    valid = datetime.now(tz=UTC) + timedelta(days=1)

    peer = Peer("localhost", valid, aes_key, aes_iv, snitun.PROTOCOL_VERSION)
    crypto = CryptoTransport(aes_key, aes_iv)

    with pytest.raises(RuntimeError):
        await peer.wait_disconnect()

    init_task = loop.create_task(
        peer.init_multiplexer_challenge(test_client.reader, test_client.writer),
    )
    await asyncio.sleep(0.1)

    assert not init_task.done()
    assert not peer.is_ready
    assert not peer.is_connected

    token = await client.reader.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    client.writer.write(crypto.encrypt(token))
    await client.writer.drain()
    await asyncio.sleep(0.1)

    assert init_task.exception() is None
    assert init_task.done()
    assert peer.is_ready
    assert peer.is_connected
    assert peer.multiplexer._throttling is None

    client.writer.close()
    client.close.set()

    await asyncio.sleep(0.1)
    assert not peer.multiplexer.is_connected


async def test_init_peer_multiplexer_crypto(
    test_client: Client,
    test_server: list[Client],
) -> None:
    """Test setup multiplexer with crypto."""
    loop = asyncio.get_running_loop()
    client = test_server[0]
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    valid = datetime.now(tz=UTC) + timedelta(days=1)

    peer = Peer("localhost", valid, aes_key, aes_iv, snitun.PROTOCOL_VERSION)
    crypto = CryptoTransport(aes_key, aes_iv)

    with pytest.raises(RuntimeError):
        await peer.wait_disconnect()

    init_task = loop.create_task(
        peer.init_multiplexer_challenge(test_client.reader, test_client.writer),
    )
    await asyncio.sleep(0.1)

    assert not init_task.done()
    assert not peer.is_ready
    assert not peer.is_connected

    token = await client.reader.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    client.writer.write(crypto.encrypt(token))
    await client.writer.drain()
    await asyncio.sleep(0.1)

    assert init_task.exception() is None
    assert init_task.done()
    assert peer.is_ready
    assert peer.is_connected

    ping_task = loop.create_task(peer.multiplexer.ping())
    await asyncio.sleep(0.1)

    ping_data = await client.reader.read(1024)
    ping = crypto.decrypt(ping_data)

    assert ping[16] == CHANNEL_FLOW_PING
    assert int.from_bytes(ping[17:21], "big") == 0
    assert ping[21:25] == b"ping"

    ping_task.cancel()
    client.writer.close()
    client.close.set()

    await asyncio.sleep(0.1)
    assert peer.multiplexer.wait().done()


async def test_init_peer_wrong_challenge(
    test_client: Client,
    test_server: list[Client],
) -> None:
    """Test setup multiplexer wrong challenge."""
    loop = asyncio.get_running_loop()
    client = test_server[0]
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    valid = datetime.now(tz=UTC) + timedelta(days=1)

    peer = Peer("localhost", valid, aes_key, aes_iv, snitun.PROTOCOL_VERSION)
    crypto = CryptoTransport(aes_key, aes_iv)

    with pytest.raises(RuntimeError):
        await peer.wait_disconnect()

    init_task = loop.create_task(
        peer.init_multiplexer_challenge(test_client.reader, test_client.writer),
    )
    await asyncio.sleep(0.1)

    assert not init_task.done()

    token = await client.reader.readexactly(32)
    client.writer.write(crypto.encrypt(token))
    await client.writer.drain()
    await asyncio.sleep(0.1)

    with pytest.raises(SniTunChallengeError):
        raise init_task.exception()
    assert init_task.done()

    client.writer.close()
    client.close.set()


def test_init_peer_invalid() -> None:
    """Test simple init of peer with invalid date."""
    valid = datetime.now(tz=UTC) - timedelta(days=1)
    peer = Peer(
        "localhost",
        valid,
        os.urandom(32),
        os.urandom(16),
        snitun.PROTOCOL_VERSION,
    )

    assert not peer.is_valid
    assert peer.hostname == "localhost"
    assert peer.multiplexer is None


async def test_init_peer_multiplexer_throttling(
    test_client: Client,
    test_server: list[Client],
) -> None:
    """Test setup multiplexer."""
    loop = asyncio.get_running_loop()
    client = test_server[0]
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    valid = datetime.now(tz=UTC) + timedelta(days=1)

    peer = Peer(
        "localhost",
        valid,
        aes_key,
        aes_iv,
        snitun.PROTOCOL_VERSION,
        throttling=500,
    )
    crypto = CryptoTransport(aes_key, aes_iv)

    with pytest.raises(RuntimeError):
        await peer.wait_disconnect()

    init_task = loop.create_task(
        peer.init_multiplexer_challenge(test_client.reader, test_client.writer),
    )
    await asyncio.sleep(0.1)

    assert not init_task.done()
    assert not peer.is_ready
    assert not peer.is_connected

    token = await client.reader.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    client.writer.write(crypto.encrypt(token))
    await client.writer.drain()
    await asyncio.sleep(0.1)

    assert init_task.exception() is None
    assert init_task.done()
    assert peer.is_ready
    assert peer.is_connected
    assert peer.multiplexer._throttling == 0.002

    client.writer.close()
    client.close.set()

    await asyncio.sleep(0.1)
    assert not peer.multiplexer.is_connected
