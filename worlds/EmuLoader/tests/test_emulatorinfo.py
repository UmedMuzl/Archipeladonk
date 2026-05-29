"""Unit tests for emu_loader.emulatorinfo."""

import json
from unittest.mock import MagicMock, patch

import pytest

from emu_loader.emulatorinfo import EmulatorInfo, _parse_emulator_configs, connect_to_emulator, load_emulator_configs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_emu(**kwargs) -> EmulatorInfo:
    """Return a minimal EmulatorInfo with sensible defaults."""
    defaults = dict(
        id="TestEmu",
        readable_emulator_name="Test Emulator",
        process_name="test_emu",
        find_dll=False,
        dll_name=None,
        additional_lookup=False,
        lower_offset_range=0,
        upper_offset_range=0x100,
    )
    defaults.update(kwargs)
    return EmulatorInfo(**defaults)


def _connected_emu() -> EmulatorInfo:
    """Return an EmulatorInfo wired up with a mock ProcessMemory."""
    emu = _make_emu()
    mock_pm = MagicMock()
    emu.connected_process = mock_pm
    emu.connected_offset = 0x1000_0000
    return emu


# ---------------------------------------------------------------------------
# _parse_emulator_configs
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = [
    {
        "id": "TestEmu",
        "readable_emulator_name": "Test Emulator",
        "process_name": "test.exe",
        "find_dll": False,
        "dll_name": None,
        "additional_lookup": False,
        "lower_offset_range": "0x0",
        "upper_offset_range": "0x100",
    }
]


class TestParseEmulatorConfigs:
    def test_returns_dict_keyed_by_id(self):
        configs = _parse_emulator_configs(SAMPLE_CONFIG)
        assert "TestEmu" in configs

    def test_fields_populated(self):
        configs = _parse_emulator_configs(SAMPLE_CONFIG)
        emu = configs["TestEmu"]
        assert emu.readable_emulator_name == "Test Emulator"
        assert emu.process_name == "test.exe"
        assert emu.find_dll is False
        assert emu.lower_offset_range == 0
        assert emu.upper_offset_range == 0x100

    def test_optional_fields_default(self):
        configs = _parse_emulator_configs(SAMPLE_CONFIG)
        emu = configs["TestEmu"]
        assert emu.range_step == 0x10
        assert emu.extra_offset == 0
        assert emu.linux_dll_name is None

    def test_empty_list(self):
        assert _parse_emulator_configs([]) == {}

    def test_multiple_entries(self):
        data = SAMPLE_CONFIG + [
            {
                **SAMPLE_CONFIG[0],
                "id": "OtherEmu",
                "readable_emulator_name": "Other Emulator",
            }
        ]
        configs = _parse_emulator_configs(data)
        assert len(configs) == 2
        assert "OtherEmu" in configs


# ---------------------------------------------------------------------------
# load_emulator_configs
# ---------------------------------------------------------------------------


class TestLoadEmulatorConfigs:
    def test_loads_from_local_file_when_web_disabled(self):
        configs = load_emulator_configs(pull_from_web=False)
        assert len(configs) > 0

    def test_returns_emulator_info_objects(self):
        configs = load_emulator_configs(pull_from_web=False)
        for emu in configs.values():
            assert isinstance(emu, EmulatorInfo)

    def test_web_failure_falls_back_to_local(self):
        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            configs = load_emulator_configs(pull_from_web=True)
        assert len(configs) > 0

    def test_known_emulator_present(self):
        configs = load_emulator_configs(pull_from_web=False)
        assert "Project64" in configs or "BizHawk" in configs


# ---------------------------------------------------------------------------
# EmulatorInfo — not connected guard
# ---------------------------------------------------------------------------


class TestEmulatorInfoNotConnected:
    def test_readBytes_raises_when_not_connected(self):
        emu = _make_emu()
        with pytest.raises(Exception, match="Not connected"):
            emu.readBytes(0x80000000, 4)

    def test_writeBytes_raises_when_not_connected(self):
        emu = _make_emu()
        with pytest.raises(Exception, match="Not connected"):
            emu.writeBytes(0x80000000, 4, 0xDEADBEEF)

    def test_runtime_error_set_after_failed_read(self):
        emu = _make_emu()
        try:
            emu.readBytes(0x80000000, 4)
        except Exception:
            pass
        assert emu.runtime_error is not None


# ---------------------------------------------------------------------------
# EmulatorInfo — address fixing (byte swapping)
# ---------------------------------------------------------------------------


class TestEmulatorInfoAddressFixing:
    """Verify that readBytes correctly adjusts addresses for endian byte-swap."""

    def _read_address_capture(self, address: int, size: int) -> int:
        """Return the physical address passed to read_bytes for the given N64 address/size."""
        emu = _connected_emu()
        captured = {}

        def fake_read_bytes(mem_addr, sz):
            captured["addr"] = mem_addr
            return (0).to_bytes(sz, "little")

        emu.connected_process.read_bytes = fake_read_bytes
        emu.readBytes(address, size)
        return captured["addr"] - emu.connected_offset

    # --- u8 swapping ---
    def test_u8_remainder0_adds3(self):
        # address % 4 == 0  → address + 3
        assert self._read_address_capture(0x80000000, 1) == 3

    def test_u8_remainder1_adds1(self):
        # address % 4 == 1  → address + 1
        assert self._read_address_capture(0x80000001, 1) == 2

    def test_u8_remainder2_subs1(self):
        # address % 4 == 2  → address - 1
        assert self._read_address_capture(0x80000002, 1) == 1

    def test_u8_remainder3_subs3(self):
        # address % 4 == 3  → address - 3
        assert self._read_address_capture(0x80000003, 1) == 0

    # --- u16 swapping ---
    def test_u16_remainder0_adds2(self):
        assert self._read_address_capture(0x80000000, 2) == 2

    def test_u16_remainder1_adds2(self):
        assert self._read_address_capture(0x80000001, 2) == 3

    def test_u16_remainder2_subs2(self):
        assert self._read_address_capture(0x80000002, 2) == 0

    def test_u16_remainder3_subs2(self):
        assert self._read_address_capture(0x80000003, 2) == 1

    # --- u32: no swapping ---
    def test_u32_no_adjustment(self):
        assert self._read_address_capture(0x80000004, 4) == 4

    # --- high bit stripped ---
    def test_high_bit_stripped_for_u32(self):
        # 0x80000300 → 0x00000300
        raw_addr = self._read_address_capture(0x80000300, 4)
        assert raw_addr == 0x300


# ---------------------------------------------------------------------------
# EmulatorInfo — read_u8 / read_u16 / read_u32 delegate to readBytes
# ---------------------------------------------------------------------------


class TestEmulatorInfoReadMethods:
    def _make_connected(self, return_value: int) -> EmulatorInfo:
        emu = _connected_emu()
        emu.connected_process.read_bytes.return_value = return_value.to_bytes(4, "little")
        return emu

    def test_read_u32_returns_value(self):
        emu = self._make_connected(0xDEADBEEF)
        assert emu.read_u32(0x80000004) == 0xDEADBEEF

    def test_read_u8_calls_readBytes_size1(self):
        emu = _connected_emu()
        emu.connected_process.read_bytes.return_value = b"\xab"
        val = emu.read_u8(0x80000000)
        assert val == 0xAB

    def test_read_u16_calls_readBytes_size2(self):
        emu = _connected_emu()
        emu.connected_process.read_bytes.return_value = b"\x34\x12"
        val = emu.read_u16(0x80000000)
        assert val == 0x1234


# ---------------------------------------------------------------------------
# EmulatorInfo — write methods
# ---------------------------------------------------------------------------


class TestEmulatorInfoWriteMethods:
    def test_write_u32_passes_correct_bytes(self):
        emu = _connected_emu()
        emu.write_u32(0x80000004, 0x12345678)
        emu.connected_process.write_bytes.assert_called_once()
        _, data, _ = emu.connected_process.write_bytes.call_args[0]
        assert data == (0x12345678).to_bytes(4, "little")

    def test_write_u8_passes_single_byte(self):
        emu = _connected_emu()
        emu.write_u8(0x80000000, 0xFF)
        _, data, _ = emu.connected_process.write_bytes.call_args[0]
        assert data == b"\xff"


# ---------------------------------------------------------------------------
# EmulatorInfo — read_bytestring / write_bytestring
# ---------------------------------------------------------------------------


class TestEmulatorInfoByteString:
    def test_read_bytestring_stops_at_null(self):
        emu = _connected_emu()
        # Simulate reading 'A', 'B', '\0'
        side_effects = [b"\x41", b"\x42", b"\x00"]

        def fake_read(addr, size):
            return side_effects.pop(0)

        emu.connected_process.read_bytes = fake_read
        result = emu.read_bytestring(0x80000000, 10)
        assert result == "AB"

    def test_write_bytestring_writes_chars_then_null(self):
        emu = _connected_emu()
        calls = []

        def fake_write(addr, data, size):
            calls.append((addr, data))

        emu.connected_process.write_bytes = fake_write
        emu.write_bytestring(0x80000000, "HI")
        # Last call should write a null terminator (0x00)
        last_data = calls[-1][1]
        assert last_data == b"\x00"

    def test_write_bytestring_sanitizes_input(self):
        emu = _connected_emu()
        written_chars = []

        def fake_write(addr, data, size):
            written_chars.append(data)

        emu.connected_process.write_bytes = fake_write
        emu.write_bytestring(0x80000000, "don't")
        # "don't" → sanitized to "DONT" → 4 chars + 1 null = 5 writes
        assert len(written_chars) == 5


# ---------------------------------------------------------------------------
# EmulatorInfo — disconnect
# ---------------------------------------------------------------------------


class TestEmulatorInfoDisconnect:
    def test_disconnect_clears_state(self):
        emu = _connected_emu()
        emu.disconnect()
        assert emu.connected_process is None
        assert emu.connected_offset is None

    def test_disconnect_calls_close_on_process(self):
        emu = _connected_emu()
        mock_pm = emu.connected_process
        emu.disconnect()
        mock_pm.close.assert_called_once()


# ---------------------------------------------------------------------------
# connect_to_emulator
# ---------------------------------------------------------------------------


class TestConnectToEmulator:
    def test_returns_none_when_no_emulators_attach(self):
        emu = _make_emu()
        emu.attach_to_emulator = MagicMock(return_value=None)
        result = connect_to_emulator({"TestEmu": emu})
        assert result is None

    def test_returns_emulator_on_success(self):
        emu = _connected_emu()
        mock_pm = emu.connected_process
        emu.attach_to_emulator = MagicMock(return_value=(mock_pm, emu.connected_offset))
        result = connect_to_emulator({"TestEmu": emu})
        assert result is emu

    def test_skips_failing_emulators(self):
        emu_bad = _make_emu(id="Bad")
        emu_bad.attach_to_emulator = MagicMock(side_effect=RuntimeError("crash"))

        emu_good = _connected_emu()
        emu_good.id = "Good"
        mock_pm = emu_good.connected_process
        emu_good.attach_to_emulator = MagicMock(return_value=(mock_pm, emu_good.connected_offset))

        result = connect_to_emulator({"Bad": emu_bad, "Good": emu_good})
        assert result is emu_good
