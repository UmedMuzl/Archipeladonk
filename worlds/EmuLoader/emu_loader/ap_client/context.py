"""Context, GUI, watcher loop and launcher entry point for the EmuLoader Archipelago client.

This module is imported lazily (only when the client is actually launched), so it is free to
pull in Kivy/CommonClient. It adapts the structure of Archipelago's ``worlds/_bizhawk`` host
client, but instead of a Lua connector it uses EmuLoader's direct-memory ``EmulatorInfo`` and
discovers per-game logic from worlds at runtime (see :mod:`.discovery`).
"""

from __future__ import annotations

import asyncio
import enum
from typing import Any, Optional

import Utils
from CommonClient import (
    ClientCommandProcessor,
    CommonContext,
    get_base_parser,
    gui_enabled,
    logger,
    server_loop,
)

from ..emulatorinfo import EmulatorInfo
from .discovery import DiscoveredHandler, connect_and_identify, discover_handlers, revalidate


class AuthStatus(enum.IntEnum):
    NOT_AUTHENTICATED = 0
    NEED_INFO = 1
    PENDING = 2
    AUTHENTICATED = 3


class EmuLoaderCommandProcessor(ClientCommandProcessor):
    def _cmd_emu(self):
        """Show the current emulator connection status."""
        assert isinstance(self.ctx, EmuLoaderClientContext)
        if self.ctx.emulator_info is None:
            logger.info("Emulator Status: Not Connected")
        else:
            game = self.ctx.current_game or "unknown game"
            logger.info(f"Emulator Status: Connected to {self.ctx.emulator_info.readable_emulator_name} ({game})")


class EmuLoaderClientContext(CommonContext):
    command_processor = EmuLoaderCommandProcessor
    items_handling = None  # set by the discovered handler on connection

    emulator_info: Optional[EmulatorInfo]
    client_handler: Optional[object]
    current_game: Optional[str]
    auth_status: AuthStatus
    password_requested: bool
    slot_data: Optional[dict[str, Any]]
    watcher_timeout: float
    pull_from_web: bool

    def __init__(self, server_address: Optional[str], password: Optional[str],
                 pull_from_web: bool = True) -> None:
        super().__init__(server_address, password)
        self.emulator_info = None
        self.client_handler = None
        self.current_game = None
        self.active_validation = None
        self.auth_status = AuthStatus.NOT_AUTHENTICATED
        self.password_requested = False
        self.slot_data = None
        self.watcher_timeout = 0.5
        self.pull_from_web = pull_from_web
        self._not_connected_logged = False

    # ------------------------------------------------------------------ #
    # Memory access exposed to handlers (delegates to the connected emulator)
    # ------------------------------------------------------------------ #
    def _emu_ready(self) -> bool:
        if self.emulator_info is None:
            if not self._not_connected_logged:
                logger.warning("Not connected to emulator.")
                self._not_connected_logged = True
            return False
        return True

    def read_u8(self, address: int) -> int:
        return self.emulator_info.read_u8(address) if self._emu_ready() else 0

    def read_u16(self, address: int) -> int:
        return self.emulator_info.read_u16(address) if self._emu_ready() else 0

    def read_u32(self, address: int) -> int:
        return self.emulator_info.read_u32(address) if self._emu_ready() else 0

    def write_u8(self, address: int, value: int) -> None:
        if self._emu_ready():
            self.emulator_info.write_u8(address, value)

    def write_u16(self, address: int, value: int) -> None:
        if self._emu_ready():
            self.emulator_info.write_u16(address, value)

    def write_u32(self, address: int, value: int) -> None:
        if self._emu_ready():
            self.emulator_info.write_u32(address, value)

    def read_bytestring(self, address: int, length: int) -> str:
        return self.emulator_info.read_bytestring(address, length) if self._emu_ready() else ""

    def write_bytestring(self, address: int, data: str) -> None:
        if self._emu_ready():
            self.emulator_info.write_bytestring(address, data)

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #
    def _reset_emulator(self) -> None:
        if self.emulator_info is not None:
            self.emulator_info.disconnect()
        self.emulator_info = None
        self.client_handler = None
        self.current_game = None
        self.active_validation = None
        self._not_connected_logged = False

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = "Archipelago EmuLoader Client"
        return ui

    def on_package(self, cmd: str, args: dict) -> None:
        if cmd == "Connected":
            self.slot_data = args.get("slot_data", None)
            self.auth_status = AuthStatus.AUTHENTICATED

        handler = self.client_handler
        on_package = getattr(handler, "on_package", None)
        if callable(on_package):
            on_package(self, cmd, args)

    async def server_auth(self, password_requested: bool = False) -> None:
        self.password_requested = password_requested

        if self.client_handler is None:
            logger.info("Awaiting connection to an emulator before authenticating.")
            return

        if self.auth is None:
            self.auth_status = AuthStatus.NEED_INFO
            set_auth = getattr(self.client_handler, "set_auth", None)
            if callable(set_auth):
                await set_auth(self)
            if self.auth is None:
                await self.get_username()

        if password_requested and not self.password:
            self.auth_status = AuthStatus.NEED_INFO
            await super().server_auth(password_requested)

        await self.send_connect()
        self.auth_status = AuthStatus.PENDING

    async def disconnect(self, allow_autoreconnect: bool = False) -> None:
        self.auth_status = AuthStatus.NOT_AUTHENTICATED
        await super().disconnect(allow_autoreconnect)


def _adopt_handler(ctx: EmuLoaderClientContext, emu: EmulatorInfo, discovered: DiscoveredHandler) -> None:
    """Wire a freshly identified emulator + handler into the context."""
    ctx.emulator_info = emu
    ctx.client_handler = discovered.handler
    ctx.current_game = discovered.game
    ctx.active_validation = discovered.validation
    ctx.game = discovered.game
    ctx.items_handling = getattr(discovered.handler, "items_handling", 0b001)
    ctx._not_connected_logged = False


async def _game_watcher(ctx: EmuLoaderClientContext) -> None:
    showed_connecting_message = False
    showed_no_handler_message = False
    loop = asyncio.get_event_loop()

    while not ctx.exit_event.is_set():
        try:
            await asyncio.wait_for(ctx.watcher_event.wait(), ctx.watcher_timeout)
        except asyncio.TimeoutError:
            pass
        ctx.watcher_event.clear()

        try:
            if ctx.emulator_info is None:
                handlers = discover_handlers()
                if not handlers:
                    if not showed_no_handler_message:
                        logger.info("No EmuLoader-compatible worlds are installed. Install a supported "
                                    "N64 apworld, then restart the client.")
                        showed_no_handler_message = True
                    continue
                showed_no_handler_message = False

                if not showed_connecting_message:
                    logger.info("Waiting to connect to a supported emulator...")
                    showed_connecting_message = True

                # connect_and_identify is blocking (scans process memory); run it off the event
                # loop and let exit cancel the wait.
                connect_task = loop.run_in_executor(
                    None, connect_and_identify, handlers, ctx.pull_from_web)
                exit_task = asyncio.create_task(ctx.exit_event.wait(), name="ExitWait")
                await asyncio.wait({connect_task, exit_task}, return_when=asyncio.FIRST_COMPLETED)

                if exit_task.done():
                    return
                exit_task.cancel()

                result = connect_task.result()
                if result is None:
                    continue

                emu, discovered = result
                _adopt_handler(ctx, emu, discovered)
                showed_connecting_message = False
                logger.info(f"Running handler for {discovered.game}")

                validate_rom = getattr(discovered.handler, "validate_rom", None)
                if callable(validate_rom):
                    if not await validate_rom(ctx):
                        logger.info(f"{discovered.game} is not ready yet; waiting...")
                        ctx._reset_emulator()
                        continue
            else:
                # Already connected: make sure the right ROM is still loaded / emulator is alive.
                if not await loop.run_in_executor(None, revalidate, ctx.emulator_info, ctx.active_validation):
                    logger.info("Lost connection to emulator (closed or ROM changed). Reconnecting...")
                    ctx._reset_emulator()
                    if ctx.server is not None and not ctx.server.socket.closed:
                        ctx.auth = None
                        ctx.username = None
                        ctx.finished_game = False
                        await ctx.disconnect(False)
                    continue
        except Exception as exc:  # noqa: BLE001 - never let the watcher die
            logger.exception(exc)
            ctx._reset_emulator()
            continue

        # Server auth once an emulator/handler is known.
        if ctx.server is not None and not ctx.server.socket.closed:
            if ctx.auth_status == AuthStatus.NOT_AUTHENTICATED:
                Utils.async_start(ctx.server_auth(ctx.password_requested))
        else:
            ctx.auth_status = AuthStatus.NOT_AUTHENTICATED

        try:
            await ctx.client_handler.game_watcher(ctx)
        except Exception as exc:  # noqa: BLE001 - a handler error shouldn't kill the client
            logger.exception(exc)
            ctx._reset_emulator()


def launch(*launch_args: str) -> None:
    async def main():
        parser = get_base_parser()
        parser.add_argument("--no-pull-from-web", action="store_true",
                            help="Use only the bundled emulator config instead of fetching the latest from the web.")
        args = parser.parse_args(launch_args)

        ctx = EmuLoaderClientContext(args.connect, args.password, pull_from_web=not args.no_pull_from_web)
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="ServerLoop")

        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()

        watcher_task = asyncio.create_task(_game_watcher(ctx), name="GameWatcher")
        try:
            await watcher_task
        except Exception as exc:  # noqa: BLE001
            logger.exception(exc)

        await ctx.exit_event.wait()
        await ctx.shutdown()

    Utils.init_logging("EmuLoaderClient", exception_logger="Client")
    import colorama

    colorama.just_fix_windows_console()
    asyncio.run(main())
    colorama.deinit()
