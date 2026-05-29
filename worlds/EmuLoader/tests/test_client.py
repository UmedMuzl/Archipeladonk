"""Unit tests for emu_loader.client.EmuLoaderClient."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from emu_loader.client import EmuLoaderClient
from emu_loader.emulatorinfo import EmulatorInfo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dummy_validation(pm, offset) -> bool:
    return True


def _make_client(connected: bool = False) -> EmuLoaderClient:
    """Return an EmuLoaderClient whose __init__ side effects are fully mocked."""
    with (
        patch("emu_loader.client.load_emulator_configs", return_value={}),
        patch("emu_loader.client.connect_to_emulator", return_value=None),
    ):
        client = EmuLoaderClient(_dummy_validation, pull_from_web=False)

    if connected:
        mock_emu = MagicMock(spec=EmulatorInfo)
        client.emulator_info = mock_emu
        client.connected = True

    return client


# ---------------------------------------------------------------------------
# Construction & connection state
# ---------------------------------------------------------------------------


class TestEmuLoaderClientInit:
    def test_not_connected_by_default_when_no_emulator_found(self):
        client = _make_client(connected=False)
        assert client.is_connected() is False

    def test_connected_flag_set_when_emulator_found(self):
        client = _make_client(connected=True)
        assert client.is_connected() is True

    def test_connect_returns_true_on_success(self):
        mock_emu = MagicMock(spec=EmulatorInfo)
        client = _make_client()
        with patch("emu_loader.client.connect_to_emulator", return_value=mock_emu):
            result = client.connect()
        assert result is True
        assert client.connected is True

    def test_connect_returns_false_when_no_emulator(self):
        client = _make_client()
        with patch("emu_loader.client.connect_to_emulator", return_value=None):
            result = client.connect()
        assert result is False

    def test_disconnect_clears_connection(self):
        client = _make_client(connected=True)
        client.disconnect()
        assert client.connected is False
        assert client.emulator_info is None

    def test_disconnect_when_not_connected_is_safe(self):
        client = _make_client(connected=False)
        client.disconnect()  # should not raise
        assert client.connected is False


# ---------------------------------------------------------------------------
# _check_not_connected — logs only once
# ---------------------------------------------------------------------------


class TestCheckNotConnected:
    def test_returns_true_when_not_connected(self):
        client = _make_client(connected=False)
        assert client._check_not_connected() is True

    def test_returns_false_when_connected(self):
        client = _make_client(connected=True)
        assert client._check_not_connected() is False

    def test_warning_logged_only_once(self):
        client = _make_client(connected=False)
        with patch("emu_loader.client.logger") as mock_logger:
            client._check_not_connected()
            client._check_not_connected()
            client._check_not_connected()
        assert mock_logger.warning.call_count == 1


# ---------------------------------------------------------------------------
# Read methods — not connected returns zero / empty
# ---------------------------------------------------------------------------


class TestReadMethodsNotConnected:
    def setup_method(self):
        self.client = _make_client(connected=False)

    def test_read_u8_returns_0(self):
        assert self.client.read_u8(0x80000000) == 0

    def test_read_u16_returns_0(self):
        assert self.client.read_u16(0x80000000) == 0

    def test_read_u32_returns_0(self):
        assert self.client.read_u32(0x80000000) == 0

    def test_read_bytestring_returns_empty(self):
        assert self.client.read_bytestring(0x80000000, 10) == ""


# ---------------------------------------------------------------------------
# Write methods — not connected is a no-op
# ---------------------------------------------------------------------------


class TestWriteMethodsNotConnected:
    def setup_method(self):
        self.client = _make_client(connected=False)

    def test_write_u8_no_exception(self):
        self.client.write_u8(0x80000000, 0xFF)  # should not raise

    def test_write_u16_no_exception(self):
        self.client.write_u16(0x80000000, 0x1234)

    def test_write_u32_no_exception(self):
        self.client.write_u32(0x80000000, 0xDEADBEEF)

    def test_write_bytestring_no_exception(self):
        self.client.write_bytestring(0x80000000, "hello")


# ---------------------------------------------------------------------------
# Read methods — connected, delegates to emulator_info
# ---------------------------------------------------------------------------


class TestReadMethodsConnected:
    def setup_method(self):
        self.client = _make_client(connected=True)
        self.mock_emu = self.client.emulator_info

    def test_read_u8_delegates(self):
        self.mock_emu.read_u8.return_value = 0xAB
        assert self.client.read_u8(0x80000001) == 0xAB
        self.mock_emu.read_u8.assert_called_once_with(0x80000001)

    def test_read_u16_delegates(self):
        self.mock_emu.read_u16.return_value = 0x1234
        assert self.client.read_u16(0x80000002) == 0x1234
        self.mock_emu.read_u16.assert_called_once_with(0x80000002)

    def test_read_u32_delegates(self):
        self.mock_emu.read_u32.return_value = 0xDEADBEEF
        assert self.client.read_u32(0x80000004) == 0xDEADBEEF
        self.mock_emu.read_u32.assert_called_once_with(0x80000004)

    def test_read_bytestring_delegates(self):
        self.mock_emu.read_bytestring.return_value = "HELLO"
        assert self.client.read_bytestring(0x80000000, 5) == "HELLO"
        self.mock_emu.read_bytestring.assert_called_once_with(0x80000000, 5)


# ---------------------------------------------------------------------------
# Write methods — connected, delegates to emulator_info
# ---------------------------------------------------------------------------


class TestWriteMethodsConnected:
    def setup_method(self):
        self.client = _make_client(connected=True)
        self.mock_emu = self.client.emulator_info

    def test_write_u8_delegates(self):
        self.client.write_u8(0x80000001, 0xFF)
        self.mock_emu.write_u8.assert_called_once_with(0x80000001, 0xFF)

    def test_write_u16_delegates(self):
        self.client.write_u16(0x80000002, 0x1234)
        self.mock_emu.write_u16.assert_called_once_with(0x80000002, 0x1234)

    def test_write_u32_delegates(self):
        self.client.write_u32(0x80000004, 0xDEADBEEF)
        self.mock_emu.write_u32.assert_called_once_with(0x80000004, 0xDEADBEEF)

    def test_write_bytestring_delegates(self):
        self.client.write_bytestring(0x80000000, "WORLD")
        self.mock_emu.write_bytestring.assert_called_once_with(0x80000000, "WORLD")


# ---------------------------------------------------------------------------
# wait_for_emulator (async)
# ---------------------------------------------------------------------------


class TestWaitForEmulator:
    def test_wait_for_emulator_exits_when_already_connected(self):
        client = _make_client(connected=True)

        async def run():
            await client.wait_for_emulator(validate=None)

        asyncio.run(run())
        assert client.is_connected()

    def test_wait_for_emulator_connects_then_exits(self):
        """After one failed poll the emulator becomes available."""
        mock_emu = MagicMock(spec=EmulatorInfo)
        call_count = {"n": 0}

        client = _make_client(connected=False)

        original_connect = client.connect

        def side_effect_connect():
            call_count["n"] += 1
            if call_count["n"] >= 2:
                client.emulator_info = mock_emu
                client.connected = True
                return True
            return False

        client.connect = side_effect_connect

        async def run():
            await client.wait_for_emulator(validate=None)

        asyncio.run(run())
        assert client.is_connected()
