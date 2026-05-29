"""Unit tests for emu_loader.retroarch_udp.RetroArchNetworkInfo."""

import socket
from unittest.mock import MagicMock, patch

import pytest

from emu_loader.retroarch_udp import N64_KSEG1_BASE, RetroArchNetworkInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ra() -> RetroArchNetworkInfo:
    """Return a RetroArchNetworkInfo with a mock socket already attached."""
    ra = RetroArchNetworkInfo()
    ra.socket = MagicMock()
    return ra


def _with_response(ra: RetroArchNetworkInfo, response: str):
    """Configure the mock socket to return the given UDP response string."""
    ra.socket.recv.return_value = response.encode("ascii")


def _word_response(address: int, value: int) -> str:
    """Build a fake READ_CORE_MEMORY response for a 32-bit word."""
    data = value.to_bytes(4, "little")
    hex_bytes = " ".join(f"{b:02X}" for b in data)
    return f"READ_CORE_MEMORY {address:08X} {hex_bytes}"


def _write_response(address: int, written: int = 4) -> str:
    return f"WRITE_CORE_MEMORY {address:08X} {written}"


# ---------------------------------------------------------------------------
# _normalize_rdram_address
# ---------------------------------------------------------------------------


class TestNormalizeRdramAddress:
    def setup_method(self):
        self.ra = RetroArchNetworkInfo()

    def test_kseg0_range(self):
        assert self.ra._normalize_rdram_address(0x80000100) == 0x100

    def test_kseg1_range(self):
        assert self.ra._normalize_rdram_address(0xA0000200) == 0x200

    def test_high_bit_set_generic(self):
        assert self.ra._normalize_rdram_address(0x90000300) == 0x10000300

    def test_bare_rdram_address_unchanged(self):
        assert self.ra._normalize_rdram_address(0x00000400) == 0x400

    def test_kseg0_upper_boundary(self):
        assert self.ra._normalize_rdram_address(0x807FFFFF) == 0x7FFFFF

    def test_kseg1_upper_boundary(self):
        assert self.ra._normalize_rdram_address(0xA07FFFFF) == 0x7FFFFF


# ---------------------------------------------------------------------------
# _to_retroarch_address
# ---------------------------------------------------------------------------


class TestToRetroarchAddress:
    def test_bare_address(self):
        ra = RetroArchNetworkInfo()
        assert ra._to_retroarch_address(0x300) == N64_KSEG1_BASE + 0x300

    def test_kseg0_address(self):
        ra = RetroArchNetworkInfo()
        assert ra._to_retroarch_address(0x80000300) == N64_KSEG1_BASE + 0x300


# ---------------------------------------------------------------------------
# _send_command
# ---------------------------------------------------------------------------


class TestSendCommand:
    def test_raises_when_no_socket(self):
        ra = RetroArchNetworkInfo()
        with pytest.raises(Exception, match="not connected"):
            ra._send_command("READ_CORE_MEMORY A0000000 4")

    def test_sends_and_receives(self):
        ra = _make_ra()
        _with_response(ra, "READ_CORE_MEMORY A0000000 01 02 03 04")
        result = ra._send_command("READ_CORE_MEMORY A0000000 4")
        ra.socket.send.assert_called_once_with(b"READ_CORE_MEMORY A0000000 4")
        assert "READ_CORE_MEMORY" in result


# ---------------------------------------------------------------------------
# _read_word
# ---------------------------------------------------------------------------


class TestReadWord:
    def test_reads_correct_value(self):
        ra = _make_ra()
        addr = N64_KSEG1_BASE + 0x300
        _with_response(ra, _word_response(addr, 0xDEADBEEF))
        result = ra._read_word(0x300)
        assert result == 0xDEADBEEF

    def test_raises_on_bad_response_prefix(self):
        ra = _make_ra()
        _with_response(ra, "UNKNOWN_CMD A0000300 01 02 03 04")
        with pytest.raises(Exception, match="Unexpected"):
            ra._read_word(0x300)

    def test_raises_on_error_response(self):
        ra = _make_ra()
        addr = N64_KSEG1_BASE + 0x300
        _with_response(ra, f"READ_CORE_MEMORY {addr:08X} -1 no memory map")
        with pytest.raises(Exception, match="read failed"):
            ra._read_word(0x300)

    def test_raises_on_wrong_byte_count(self):
        ra = _make_ra()
        addr = N64_KSEG1_BASE + 0x300
        _with_response(ra, f"READ_CORE_MEMORY {addr:08X} 01 02")
        with pytest.raises(Exception, match="2 bytes"):
            ra._read_word(0x300)


# ---------------------------------------------------------------------------
# _write_word
# ---------------------------------------------------------------------------


class TestWriteWord:
    def test_writes_correct_command(self):
        ra = _make_ra()
        addr = N64_KSEG1_BASE + 0x400
        _with_response(ra, _write_response(addr, 4))
        ra._write_word(0x400, 0x12345678)
        sent = ra.socket.send.call_args[0][0].decode()
        assert sent.startswith("WRITE_CORE_MEMORY")
        # value 0x12345678 little-endian → 78 56 34 12
        assert "78 56 34 12" in sent

    def test_raises_on_bad_response(self):
        ra = _make_ra()
        addr = N64_KSEG1_BASE + 0x400
        _with_response(ra, "GARBAGE")
        with pytest.raises(Exception, match="Unexpected"):
            ra._write_word(0x400, 0xABCD)

    def test_raises_on_error_flag(self):
        ra = _make_ra()
        addr = N64_KSEG1_BASE + 0x400
        _with_response(ra, f"WRITE_CORE_MEMORY {addr:08X} -1 write error")
        with pytest.raises(Exception, match="write failed"):
            ra._write_word(0x400, 0xABCD)

    def test_raises_on_wrong_write_count(self):
        ra = _make_ra()
        addr = N64_KSEG1_BASE + 0x400
        _with_response(ra, f"WRITE_CORE_MEMORY {addr:08X} 2")
        with pytest.raises(Exception, match="wrote 2 bytes"):
            ra._write_word(0x400, 0xABCD)


# ---------------------------------------------------------------------------
# read_u8 / read_u16 / read_u32 — big-endian N64 word unpacking
# ---------------------------------------------------------------------------


class TestReadMethods:
    """
    N64 memory is big-endian. RetroArch returns words in little-endian host order.
    The read methods unpack individual bytes from the 32-bit word correctly.
    """

    def _ra_with_word(self, rdram_address: int, value: int) -> RetroArchNetworkInfo:
        ra = _make_ra()
        cmd_addr = N64_KSEG1_BASE + rdram_address
        _with_response(ra, _word_response(cmd_addr, value))
        return ra

    # read_u32 at an aligned address
    def test_read_u32_aligned(self):
        # word at 0x300 = 0xDEADBEEF
        ra = self._ra_with_word(0x300, 0xDEADBEEF)
        assert ra.read_u32(0x300) == 0xDEADBEEF

    # read_u8 byte extraction (big-endian within word)
    def test_read_u8_byte0(self):
        # byte 0 of big-endian word 0xAABBCCDD → 0xAA
        ra = self._ra_with_word(0x300, 0xAABBCCDD)
        assert ra.read_u8(0x300) == 0xAA

    def test_read_u8_byte1(self):
        ra = self._ra_with_word(0x300, 0xAABBCCDD)
        assert ra.read_u8(0x301) == 0xBB

    def test_read_u8_byte2(self):
        ra = self._ra_with_word(0x300, 0xAABBCCDD)
        assert ra.read_u8(0x302) == 0xCC

    def test_read_u8_byte3(self):
        ra = self._ra_with_word(0x300, 0xAABBCCDD)
        assert ra.read_u8(0x303) == 0xDD

    # read_u16
    def test_read_u16_aligned(self):
        # upper halfword of 0xAABBCCDD → 0xAABB
        ra = self._ra_with_word(0x300, 0xAABBCCDD)
        assert ra.read_u16(0x300) == 0xAABB

    def test_read_u16_lower_half(self):
        ra = self._ra_with_word(0x300, 0xAABBCCDD)
        assert ra.read_u16(0x302) == 0xCCDD

    # kseg0 address normalisation passes through correctly
    def test_read_u32_kseg0_address(self):
        ra = self._ra_with_word(0x300, 0x12345678)
        assert ra.read_u32(0x80000300) == 0x12345678


# ---------------------------------------------------------------------------
# write_u8 / write_u16 / write_u32
# ---------------------------------------------------------------------------


class TestWriteMethods:
    def _ra_with_read_write(self, rdram_address: int, initial_word: int) -> RetroArchNetworkInfo:
        """Return an RA whose socket emits a read response then a write response."""
        ra = _make_ra()
        cmd_addr = N64_KSEG1_BASE + (rdram_address & ~3)
        read_resp = _word_response(cmd_addr, initial_word).encode("ascii")
        write_resp = _write_response(cmd_addr, 4).encode("ascii")
        ra.socket.recv.side_effect = [read_resp, write_resp]
        return ra

    def _last_written_word(self, ra: RetroArchNetworkInfo) -> int:
        """Extract the 32-bit value from the last WRITE_CORE_MEMORY command sent."""
        last_send = ra.socket.send.call_args_list[-1][0][0].decode()
        hex_bytes = last_send.split()[2:]
        data = bytes(int(b, 16) for b in hex_bytes)
        return int.from_bytes(data, "little")

    def test_write_u32_aligned(self):
        ra = _make_ra()
        cmd_addr = N64_KSEG1_BASE + 0x300
        _with_response(ra, _write_response(cmd_addr, 4))
        ra.write_u32(0x300, 0xCAFEBABE)
        assert self._last_written_word(ra) == 0xCAFEBABE

    def test_write_u8_modifies_correct_byte(self):
        # Byte 0 of big-endian word 0x00000000 should become 0xFF → word = 0xFF000000
        ra = self._ra_with_read_write(0x300, 0x00000000)
        ra.write_u8(0x300, 0xFF)
        assert self._last_written_word(ra) == 0xFF000000

    def test_write_u8_byte3(self):
        # Byte 3 of big-endian word 0x00000000 should become 0xFF → word = 0x000000FF
        ra = self._ra_with_read_write(0x303, 0x00000000)
        ra.write_u8(0x303, 0xFF)
        assert self._last_written_word(ra) == 0x000000FF

    def test_write_u16_upper_half(self):
        ra = self._ra_with_read_write(0x300, 0x00000000)
        ra.write_u16(0x300, 0xBEEF)
        assert self._last_written_word(ra) == 0xBEEF0000

    def test_write_u16_lower_half(self):
        ra = self._ra_with_read_write(0x302, 0x00000000)
        ra.write_u16(0x302, 0xBEEF)
        assert self._last_written_word(ra) == 0x0000BEEF


# ---------------------------------------------------------------------------
# attach_to_emulator
# ---------------------------------------------------------------------------


class TestAttachToEmulator:
    def test_returns_self_on_success(self):
        ra = RetroArchNetworkInfo()
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value = mock_sock
            cmd_addr = N64_KSEG1_BASE
            mock_sock.recv.return_value = _word_response(cmd_addr, 0).encode("ascii")
            result = ra.attach_to_emulator()
        assert result is ra
        assert ra.socket is mock_sock

    def test_sets_error_on_timeout(self):
        ra = RetroArchNetworkInfo()
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value = mock_sock
            mock_sock.recv.side_effect = socket.timeout()
            result = ra.attach_to_emulator()
        assert result is None
        assert ra.connection_error is not None
        assert "did not respond" in ra.connection_error

    def test_sets_error_on_oserror(self):
        ra = RetroArchNetworkInfo()
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value = mock_sock
            mock_sock.connect.side_effect = OSError("refused")
            result = ra.attach_to_emulator()
        assert result is None
        assert ra.connection_error is not None
        assert "unavailable" in ra.connection_error

    def test_socket_closed_on_failure(self):
        ra = RetroArchNetworkInfo()
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value = mock_sock
            mock_sock.recv.side_effect = socket.timeout()
            ra.attach_to_emulator()
        mock_sock.close.assert_called()


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    def test_clears_socket(self):
        ra = _make_ra()
        ra.disconnect()
        assert ra.socket is None

    def test_close_called(self):
        ra = _make_ra()
        mock_sock = ra.socket
        ra.disconnect()
        mock_sock.close.assert_called_once()

    def test_disconnect_tolerates_oserror(self):
        ra = _make_ra()
        ra.socket.close.side_effect = OSError("already closed")
        ra.disconnect()  # should not raise
        assert ra.socket is None

    def test_disconnect_when_already_none(self):
        ra = RetroArchNetworkInfo()
        ra.disconnect()  # should not raise
