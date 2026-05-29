"""Runtime discovery of N64 worlds and emulator identification for the EmuLoader client.

Worlds expose their client logic as *global context* on their ``World`` class -- a duck-typed
``n64_client_handler`` attribute alongside the existing ``N64WorldMixin`` validation data. This
module collects those at runtime (no world ever imports EmuLoader) and identifies which game is
loaded in a running emulator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, NamedTuple, Optional, Tuple

from ..emulatorinfo import EmulatorInfo, load_emulator_configs
from ..n64_registry import N64ValidationInfo, discover_n64_worlds

try:
    from CommonClient import logger
except ImportError:  # pragma: no cover - exercised only outside Archipelago
    import logging

    logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .context import EmuLoaderClientContext


class DiscoveredHandler(NamedTuple):
    """A game's validation data paired with its duck-typed client handler instance."""

    game: str
    validation: N64ValidationInfo
    handler: object


def discover_handlers() -> Dict[str, DiscoveredHandler]:
    """Return ``game_name -> DiscoveredHandler`` for every installed world that exposes both
    N64 validation data (via :class:`N64WorldMixin` / duck typing) and an ``n64_client_handler``.

    Must be called *after* all worlds have been imported so that ``AutoWorldRegister`` is fully
    populated -- which is always the case by the time the client is launched.
    """
    from worlds.AutoWorld import AutoWorldRegister  # type: ignore[import]

    validations = discover_n64_worlds()
    results: Dict[str, DiscoveredHandler] = {}

    for game, world_cls in AutoWorldRegister.world_types.items():
        if game not in validations:
            continue
        handler = getattr(world_cls, "n64_client_handler", None)
        if handler is None:
            continue
        # A class is instantiated once; an already-built instance is used as-is.
        handler_instance = handler() if isinstance(handler, type) else handler
        results[game] = DiscoveredHandler(game, validations[game], handler_instance)

    return results


def connect_and_identify(
    handlers: Dict[str, DiscoveredHandler],
    pull_from_web: bool = True,
) -> Optional[Tuple[EmulatorInfo, DiscoveredHandler]]:
    """Scan running emulators and identify which discovered game is loaded.

    Unlike :class:`~..client.EmuLoaderClient` (which scans for a single known signature), this
    tries every discovered world's validator against every supported emulator. The emulator
    config's ``validation_func`` is reused so :meth:`EmulatorInfo.attach_to_emulator` performs
    the RDRAM-base scan-and-validate in one pass -- no core changes required.

    Args:
        handlers: The mapping returned by :func:`discover_handlers`.
        pull_from_web: Forwarded to :func:`load_emulator_configs`.

    Returns:
        ``(connected EmulatorInfo, DiscoveredHandler)`` for the first match, or ``None``.
    """
    if not handlers:
        return None

    configs = load_emulator_configs(pull_from_web=pull_from_web)
    if not configs:
        return None

    for emu in configs.values():
        for discovered in handlers.values():
            validator = discovered.validation.effective_validator()
            if validator is None:
                continue
            # Drive base detection with this game's validator.
            emu.signature_offset = 0
            emu.signature_value = 0
            emu.validation_func = validator
            try:
                if emu.attach_to_emulator():
                    logger.info(f"Detected {discovered.game} in {emu.readable_emulator_name}")
                    return emu, discovered
            except Exception as exc:  # noqa: BLE001 - keep scanning other candidates
                logger.debug(f"Attach attempt failed for {emu.readable_emulator_name}: {exc}")
                emu.disconnect()

    return None


def revalidate(emu: EmulatorInfo, validation: N64ValidationInfo) -> bool:
    """Return ``True`` if the connected emulator still holds the expected ROM.

    Used by the watcher loop to notice a ROM change or a closed emulator (memory reads raise once
    the process is gone).
    """
    if emu.connected_process is None or emu.connected_offset is None:
        return False
    validator = validation.effective_validator()
    if validator is None:
        return False
    try:
        return validator(emu.connected_process, emu.connected_offset)
    except Exception:  # noqa: BLE001 - any failure means we are no longer validly connected
        return False
