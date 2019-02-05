"""Tests for peer listener & manager."""
import asyncio
from datetime import datetime, timedelta
import hashlib
import os

from snitun.multiplexer.crypto import CryptoTransport
from snitun.server.listener_peer import PeerListener

from .const_fernet import create_peer_config


async def test_init_listener(peer_manager):
    """Create a PeerListener instance and start/stop it."""
    listener = PeerListener(peer_manager, "127.0.0.1", "8893")
    await listener.start()

    await asyncio.sleep(0.1)

    yield listener
    await listener.stop()


async def test_peer_listener(peer_manager, peer_listener, test_client_peer):
    """Run a full flow of with a peer."""
    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key,
                                      aes_iv)

    crypto = CryptoTransport(aes_key, aes_iv)

    test_client_peer.writer.write(fernet_token)
    await test_client_peer.writer.drain()

    token = await test_client_peer.reader.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    test_client_peer.writer.write(crypto.encrypt(token))

    await test_client_peer.writer.drain()
    await asyncio.sleep(0.1)

    assert peer_manager.peer_available(hostname)


async def test_peer_listener_disconnect(peer_manager, peer_listener,
                                        test_client_peer):
    """Run a full flow of with a peer after that disconnect."""
    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key,
                                      aes_iv)

    crypto = CryptoTransport(aes_key, aes_iv)

    test_client_peer.writer.write(fernet_token)
    await test_client_peer.writer.drain()

    token = await test_client_peer.reader.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    test_client_peer.writer.write(crypto.encrypt(token))

    await test_client_peer.writer.drain()
    await asyncio.sleep(0.1)

    assert peer_manager.peer_available(hostname)

    test_client_peer.writer.close()
    await asyncio.sleep(0.1)

    assert not peer_manager.peer_available(hostname)