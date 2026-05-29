"""EmuLoader - Cross-platform emulator memory access library."""

from .client import EmuLoaderClient
from .emulatorinfo import EmulatorInfo, attachWrapper, connect_to_emulator, load_emulator_configs
from .retroarch_udp import RetroArchNetworkInfo
from .process import ProcessMemory
from .ptrace import check_and_fix_ptrace_scope
from .n64_registry import (
    N64ValidationInfo,
    N64WorldMixin,
    ValidationFunc,
    build_offset_value_validator,
    discover_n64_worlds,
)

__all__ = [
    "EmuLoaderClient",
    "EmulatorInfo",
    "ProcessMemory",
    "connect_to_emulator",
    "attachWrapper",
    "load_emulator_configs",
    "RetroArchNetworkInfo",
    "check_and_fix_ptrace_scope",
    "N64ValidationInfo",
    "N64WorldMixin",
    "ValidationFunc",
    "build_offset_value_validator",
    "discover_n64_worlds",
]
