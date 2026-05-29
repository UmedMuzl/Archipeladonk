"""Unit tests for the EmuLoader Archipelago client discovery layer.

These tests exercise :mod:`emu_loader.ap_client.discovery`, which is importable without
Archipelago/Kivy (the only Archipelago import it needs -- ``worlds.AutoWorld`` -- is deferred to
call time and faked here). The Kivy/CommonClient-coupled pieces (``context``, the launcher
component) are only checked when Archipelago happens to be importable.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest

from emu_loader.ap_client.discovery import (
    DiscoveredHandler,
    connect_and_identify,
    discover_handlers,
    revalidate,
)
from emu_loader.n64_registry import N64ValidationInfo


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeHandler:
    items_handling = 0b001

    async def game_watcher(self, ctx):  # pragma: no cover - never run here
        pass


def _make_world(*, offset=None, value=None, handler=None):
    """Build a throwaway World-like class exposing duck-typed N64 context."""
    return type("FakeWorld", (), {
        "n64_validation_offset": offset,
        "n64_validation_value": value,
        "n64_client_handler": handler,
    })


@pytest.fixture
def fake_world_registry(monkeypatch):
    """Inject a fake ``worlds.AutoWorld`` so discovery can read ``world_types`` offline."""
    registry = types.SimpleNamespace(world_types={})

    auto_world = types.ModuleType("worlds.AutoWorld")
    auto_world.AutoWorldRegister = registry

    worlds_pkg = sys.modules.get("worlds")
    if worlds_pkg is None:
        worlds_pkg = types.ModuleType("worlds")
        worlds_pkg.__path__ = []  # mark as a package
        monkeypatch.setitem(sys.modules, "worlds", worlds_pkg)
    monkeypatch.setattr(worlds_pkg, "AutoWorld", auto_world, raising=False)
    monkeypatch.setitem(sys.modules, "worlds.AutoWorld", auto_world)

    return registry


# ---------------------------------------------------------------------------
# discover_handlers
# ---------------------------------------------------------------------------


class TestDiscoverHandlers:
    def test_picks_up_world_with_validation_and_handler(self, fake_world_registry):
        fake_world_registry.world_types = {
            "Game A": _make_world(offset=0x3B, value=b"\x4E", handler=_FakeHandler),
        }
        result = discover_handlers()
        assert set(result) == {"Game A"}
        assert isinstance(result["Game A"], DiscoveredHandler)
        # A class is instantiated exactly once.
        assert isinstance(result["Game A"].handler, _FakeHandler)

    def test_uses_handler_instance_as_is(self, fake_world_registry):
        instance = _FakeHandler()
        fake_world_registry.world_types = {
            "Game B": _make_world(offset=0x10, value=b"\x01", handler=instance),
        }
        result = discover_handlers()
        assert result["Game B"].handler is instance

    def test_skips_world_without_handler(self, fake_world_registry):
        fake_world_registry.world_types = {
            "No Handler": _make_world(offset=0x3B, value=b"\x4E", handler=None),
        }
        assert discover_handlers() == {}

    def test_skips_world_without_validation(self, fake_world_registry):
        fake_world_registry.world_types = {
            "No Validation": _make_world(offset=None, value=None, handler=_FakeHandler),
        }
        assert discover_handlers() == {}


# ---------------------------------------------------------------------------
# connect_and_identify
# ---------------------------------------------------------------------------


def _discovered(game: str) -> DiscoveredHandler:
    validation = N64ValidationInfo(game_name=game, validation_offset=0x0, validation_value=b"\x00")
    return DiscoveredHandler(game, validation, _FakeHandler())


class TestConnectAndIdentify:
    def test_returns_none_when_no_handlers(self):
        assert connect_and_identify({}, pull_from_web=False) is None

    def test_returns_match_when_emulator_attaches(self, monkeypatch):
        emu = MagicMock()
        emu.readable_emulator_name = "Fake Emu"
        emu.attach_to_emulator.return_value = True

        monkeypatch.setattr(
            "emu_loader.ap_client.discovery.load_emulator_configs",
            lambda pull_from_web=True: {"Fake": emu},
        )

        discovered = _discovered("Game A")
        result = connect_and_identify({"Game A": discovered}, pull_from_web=False)

        assert result is not None
        returned_emu, returned_handler = result
        assert returned_emu is emu
        assert returned_handler is discovered
        # The game's validator was wired into the emulator config before attaching.
        assert callable(emu.validation_func)

    def test_returns_none_when_nothing_attaches(self, monkeypatch):
        emu = MagicMock()
        emu.attach_to_emulator.return_value = False
        monkeypatch.setattr(
            "emu_loader.ap_client.discovery.load_emulator_configs",
            lambda pull_from_web=True: {"Fake": emu},
        )
        assert connect_and_identify({"Game A": _discovered("Game A")}, pull_from_web=False) is None

    def test_returns_none_when_no_configs(self, monkeypatch):
        monkeypatch.setattr(
            "emu_loader.ap_client.discovery.load_emulator_configs",
            lambda pull_from_web=True: {},
        )
        assert connect_and_identify({"Game A": _discovered("Game A")}, pull_from_web=False) is None


# ---------------------------------------------------------------------------
# revalidate
# ---------------------------------------------------------------------------


class TestRevalidate:
    def test_false_when_not_connected(self):
        emu = MagicMock()
        emu.connected_process = None
        emu.connected_offset = None
        assert revalidate(emu, N64ValidationInfo(game_name="G", validation_offset=0, validation_value=b"\x00")) is False

    def test_true_when_validator_matches(self):
        emu = MagicMock()
        emu.connected_process = MagicMock()
        emu.connected_process.read_bytes.return_value = b"\x00"
        emu.connected_offset = 0x1000
        validation = N64ValidationInfo(game_name="G", validation_offset=0, validation_value=b"\x00")
        assert revalidate(emu, validation) is True

    def test_false_when_read_raises(self):
        emu = MagicMock()
        emu.connected_process = MagicMock()
        emu.connected_process.read_bytes.side_effect = OSError("process gone")
        emu.connected_offset = 0x1000
        validation = N64ValidationInfo(game_name="G", validation_offset=0, validation_value=b"\x00")
        assert revalidate(emu, validation) is False


# ---------------------------------------------------------------------------
# Generation-safety / launcher component (only when Archipelago is importable)
# ---------------------------------------------------------------------------


class TestLauncherComponentRegistration:
    def test_importing_world_package_registers_component_without_kivy(self):
        pytest.importorskip("worlds.LauncherComponents")
        import importlib

        sys.modules.pop("kvui", None)
        components_mod = importlib.import_module("worlds.LauncherComponents")
        importlib.import_module("worlds.EmuLoader")

        assert any(c.display_name == "EmuLoader Client" for c in components_mod.components)
        # Registering the component must not have dragged in the Kivy UI.
        assert "kvui" not in sys.modules
