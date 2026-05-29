"""EmuLoader Archipelago client package.

This subpackage holds the Archipelago-coupled client (Kivy GUI + server connection + emulator
watcher). The heavyweight imports live in :mod:`.context`, which is imported lazily so that
``import worlds.EmuLoader.emu_loader`` stays usable without Archipelago/Kivy installed.

Worlds do **not** import anything from here. They expose their client logic as a duck-typed
``n64_client_handler`` attribute on their ``World`` class; the client discovers and runs it. The
:class:`EmuLoaderClientHandler` Protocol below documents the expected shape for typing only --
worlds may subclass it, copy it, or simply provide a matching object.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .context import EmuLoaderClientContext


@runtime_checkable
class EmuLoaderClientHandler(Protocol):
    """The duck-typed contract a world's ``n64_client_handler`` should satisfy.

    Only :meth:`game_watcher` is required. Memory access is done through ``ctx`` (``ctx.read_u8``,
    ``ctx.write_u8``, ``ctx.read_bytestring``, ...), so a handler needs no EmuLoader import.
    """

    #: Archipelago items_handling flags sent on connect (defaults to 0b001 if omitted).
    items_handling: int

    async def game_watcher(self, ctx: "EmuLoaderClientContext") -> None:
        """Run one tick of per-game logic: read state, check locations, give items, set goal.

        Called repeatedly (roughly every ``ctx.watcher_timeout`` seconds) once the correct ROM is
        confirmed loaded and the emulator is connected.
        """
        ...

    # Optional hooks (all may be omitted):
    # async def validate_rom(self, ctx) -> bool: ...   # extra in-RAM readiness check
    # async def set_auth(self, ctx) -> None: ...       # set ctx.auth from ROM if stored there
    # def on_package(self, ctx, cmd, args) -> None: ... # react to server packets


def launch(*args: str) -> None:
    """Launch the EmuLoader client. Lazily imports the AP/Kivy-coupled context module."""
    from .context import launch as _launch
    _launch(*args)


__all__ = ["EmuLoaderClientHandler", "launch"]
