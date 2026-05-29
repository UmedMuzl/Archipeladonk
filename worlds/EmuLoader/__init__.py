"""Archipelago integration for EmuLoader.

This package is *not* a playable world -- it defines no :class:`World` subclass, so nothing is
added to ``AutoWorldRegister.world_types``.  Its sole job at import time is to register the
"EmuLoader Client" launcher component so the button appears in the Archipelago Launcher without
any installed game needing to import EmuLoader.

Because the world scanner imports this module during generation as well as at launch, the module
top level must stay lightweight: it touches only ``worlds.LauncherComponents`` (already loaded by
then) and defers every Kivy/CommonClient/emu_loader import into :func:`launch_client`.
"""

from worlds.LauncherComponents import (
    Component,
    SuffixIdentifier,
    Type,
    components,
    launch as launch_component,
)


def launch_client(*args) -> None:
    """Launch the EmuLoader Archipelago client (lazy import keeps generation lightweight)."""
    from .emu_loader.ap_client.context import launch
    launch_component(launch, name="EmuLoaderClient", args=args)


components.append(Component(
    "EmuLoader Client",
    func=launch_client,
    component_type=Type.CLIENT,
    file_identifier=SuffixIdentifier(),
    description="Connect to an N64 emulator via EmuLoader to play a supported game.",
))
