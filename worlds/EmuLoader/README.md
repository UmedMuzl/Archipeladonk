# EmuLoader

Cross-platform emulator memory access library for N64 emulators. Supports Windows, Linux, and macOS (via RetroArch UDP), with built-in detection for common emulators including Project64, BizHawk, Rosalie's Mupen GUI, simple64, Parallel Launcher, RetroArch, Gopher64, and ares.

> **Note on emulator config loading:** The emulator definitions bundled with this package come from [`emu_loader/emulators.json`](emu_loader/emulators.json) in this repository. However, when `pull_from_web=True` is passed by the implementor (which is the default), EmuLoader will first attempt to fetch the latest config directly from [https://killklli.github.io/EmuLoader/emulators.json](https://killklli.github.io/EmuLoader/emulators.json) — which always reflects the `emulators.json` on the `main` branch. This means emulator support can be updated or corrected without requiring end users to upgrade the package. If the remote fetch fails, EmuLoader falls back to the bundled local copy automatically. To opt out of remote fetching entirely, pass `pull_from_web=False` when connecting.

## Archipelago Client

When EmuLoader is dropped into an Archipelago install at `worlds/EmuLoader/`, it ships a **self-contained Archipelago client** — a Kivy GUI with an AP server connection and an emulator watcher. It registers an **"EmuLoader Client"** button in the Archipelago Launcher (no game install required) via [`worlds/EmuLoader/__init__.py`](__init__.py).

Crucially, **N64 worlds do not depend on EmuLoader as a package.** A world advertises its client logic as *global context* on its `World` class, and the client discovers it at runtime through `AutoWorldRegister` (the same mechanism as [`discover_n64_worlds()`](emu_loader/n64_registry.py)). This means no `requirements.txt` pin and no import coupling — the world just sets plain class attributes:

```python
# In your apworld's __init__.py — note: NO import from emu_loader is needed.
class SomeN64World(World):                 # optionally also (N64WorldMixin, World)
    game = "Some N64 Game"

    # ROM identification (existing N64WorldMixin contract):
    n64_validation_offset = 0x3B
    n64_validation_value  = b"\x4E"
    # ...or a custom pointer-chasing validator:
    # n64_validation_function = staticmethod(my_validator)

    # NEW: the per-game client logic the EmuLoader client runs once the ROM is detected.
    n64_client_handler = SomeN64Handler
```

`n64_client_handler` may be a class (instantiated once) or an instance. It is duck-typed for:

| Member | Required | Purpose |
|---|:---:|---|
| `async def game_watcher(self, ctx)` | ✅ | Per-tick loop: read state, check locations, give items, set goal. Runs ~every `ctx.watcher_timeout` s while connected. |
| `items_handling: int` | | AP `items_handling` flags sent on connect (defaults to `0b001`). |
| `async def validate_rom(self, ctx) -> bool` | | Extra in-RAM readiness check; may set `ctx.game`. |
| `async def set_auth(self, ctx)` | | Set `ctx.auth` from the ROM if the slot name is stored there. |
| `def on_package(self, ctx, cmd, args)` | | React to server packets. |

The handler reads and writes emulator memory **through `ctx`** — `ctx.read_u8/read_u16/read_u32`, `ctx.write_u8/write_u16/write_u32`, `ctx.read_bytestring`, `ctx.write_bytestring` — so it never imports anything from EmuLoader. An optional `EmuLoaderClientHandler` `Protocol` lives in [`emu_loader/ap_client/__init__.py`](emu_loader/ap_client/__init__.py) purely for typing/documentation; you may reference it under `TYPE_CHECKING` or ignore it entirely.

Example handler skeleton (defined in *your* world's package):

```python
class SomeN64Handler:
    items_handling = 0b001

    async def validate_rom(self, ctx) -> bool:
        return ctx.read_u8(0x80000000) != 0   # ROM/AP ready flag

    async def game_watcher(self, ctx) -> None:
        from NetUtils import ClientStatus
        # check a location
        if ctx.read_u8(LOCATION_FLAG_ADDR):
            await ctx.check_locations([BASE_ID + 0])
        # give received items
        for item in ctx.items_received:
            ctx.write_u8(ITEM_ADDR, item.item & 0xFF)
        # report goal
        if ctx.read_u8(GAME_COMPLETE_ADDR) and not ctx.finished_game:
            await ctx.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])
            ctx.finished_game = True
```

## Linux Notes

On Linux, memory access uses `/proc/<pid>/mem`. If ptrace restrictions are enabled (`/proc/sys/kernel/yama/ptrace_scope` > 0), the library will attempt to relax them automatically using `sudo`. You may be prompted for your password.

## Supported Emulators

| Emulator | Key | Windows | Linux | macOS |
|---|---|:---:|:---:|:---:|
| Project64 | `"Project64"` | ✅ | ❌ | ❌ |
| Project64 4.0+ | `"Project64_v4"` | ✅ | ❌ | ❌ |
| Project64 (scan) | `"Project64Scan"` | ✅ | ❌ | ❌ |
| Project64 3.0.1 (EM) | `"Project64_EM"` | ✅ | ❌ | ❌ |
| BizHawk | `"BizHawk"` | ✅ | ✅ | ❌ |
| Rosalie's Mupen GUI | `"RMG"` | ✅ | ✅ | ❌ |
| Rosalie's Mupen GUI (Flatpak) | `"RMG_Flatpak"` | ❌ | ✅ | ❌ |
| simple64 | `"Simple64"` | ✅ | ✅ | ❌ |
| Parallel Launcher | `"ParallelLauncher"` | ✅ | ✅ | ❌ |
| Parallel Launcher 9.0.3+ | `"ParallelLauncher903"` | ✅ | ✅ | ❌ |
| RetroArch (mupen64plus_next) | `"RetroArch"` | ✅ | ✅ | ✅ (UDP) |
| Gopher64 | `"Gopher64"` | ✅ | ✅ | ❌ |
| ares | `"Ares"` | ✅ | ✅ | ❌ |

> **macOS note:** Direct process-memory access is not supported on macOS. RetroArch with Network Commands (UDP) enabled is the only supported connection method on that platform.

## Adding Emulators

New emulators can be added by appending an entry to `emu_loader/emulators.json`. Each entry is a JSON object with the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | ✅ | Unique identifier used when referencing the emulator in code (e.g. `"MyEmu"`). |
| `readable_emulator_name` | string | ✅ | Human-friendly display name (e.g. `"My Emulator 2.0"`). |
| `process_name` | string | ✅ | The executable name (without `.exe`) that EmuLoader searches for in the process list. |
| `find_dll` | bool | ✅ | If `true`, EmuLoader locates the emulator's memory via a loaded DLL rather than the main process. |
| `dll_name` | string\|null | ✅ | Windows DLL filename to search for (e.g. `"mupen64plus.dll"`). Set to `null` when `find_dll` is `false` or Windows is unsupported. |
| `linux_dll_name` | string\|null | ✅ | Linux shared-library filename (e.g. `"libmupen64plus.so"`). Set to `null` when Linux is unsupported. |
| `additional_lookup` | bool | ✅ | If `true`, an additional pointer/offset lookup is performed after the initial base address is found. |
| `lower_offset_range` | string | ✅ | Hex string lower bound of the memory scan range (e.g. `"0x5A000"`). Set to `"0x0"` when using `scan_memory_for_signature`. |
| `upper_offset_range` | string | ✅ | Hex string upper bound of the memory scan range (e.g. `"0x5658DF"`). Set to `"0x0"` when using `scan_memory_for_signature`. |
| `range_step` | string | ✅ | Hex step size used when iterating through the scan range (e.g. `"0x10"`). |
| `extra_offset` | string | ✅ | Additional hex offset added to the located base address (e.g. `"0x80000000"`). Use `"0x0"` if no adjustment is needed. |
| `scan_memory_for_signature` | bool | ❌ | If `true`, the scan range is ignored and EmuLoader instead searches process memory for a known N64 RAM signature. Useful for emulators with dynamic memory layouts. |
| `signature_alignment` | string | ❌ | Hex alignment boundary used during signature scanning (e.g. `"0x1000"`). Only relevant when `scan_memory_for_signature` is `true`. |

### Example entry

```json
{
    "id": "MyEmulator",
    "readable_emulator_name": "My Emulator 2.0",
    "process_name": "myemulator",
    "find_dll": true,
    "dll_name": "myemulator_core.dll",
    "linux_dll_name": "libmyemulator_core.so",
    "additional_lookup": false,
    "lower_offset_range": "0x100000",
    "upper_offset_range": "0x500000",
    "range_step": "0x10",
    "extra_offset": "0x0"
}
```

After adding the entry, the new `id` can be passed anywhere EmuLoader accepts an emulator key.

### Archipelago World Installation

EmuLoader is shipped as a bundled Archipelago client folder (`worlds/EmuLoader/`); it is **no longer consumed as a pip dependency by worlds.** A world adds EmuLoader support purely by exposing the global context described in [Archipelago Client](#archipelago-client) above — `n64_validation_*` and `n64_client_handler` class attributes — with **no `requirements.txt` entry and no `import emu_loader`**. The client discovers worlds at runtime via `AutoWorldRegister`.

> The `pip install` instructions below remain valid for using EmuLoader as a standalone memory-access library outside of Archipelago.

## Usage

The simplest way to create a client is to pass the address and expected value that uniquely identify your ROM in RDRAM. EmuLoader will automatically scan emulator memory for a location where that value is found at that offset:

```python
from emu_loader import EmuLoaderClient

# DK64 example — 0x759290 holds the magic value 0x52414D42 ("RAMB") in the correct ROM
client = EmuLoaderClient(signature_offset=0x759290, signature_value=0x52414D42)

if client.is_connected():
    print("Connected to emulator!")

    value = client.read_u32(0x807ED000)
    client.write_u8(0x807ED100, 0x01)

    client.disconnect()
```

For games whose RDRAM marker cannot be expressed as a single fixed-value equality check, pass a `validation_func` instead:

```python
from emu_loader import EmuLoaderClient
from emu_loader.process import ProcessMemory

MY_ROM_MAGIC_ADDRESS = 0x80123456
MY_ROM_MAGIC_VALUE   = 0xDEADBEEF

def validate_base(mem: ProcessMemory, base: int) -> bool:
    """Called during emulator attachment — return True if the correct ROM is at this base."""
    try:
        value = mem.read_int(base + (MY_ROM_MAGIC_ADDRESS & 0x7FFFFFFF))
        return value == MY_ROM_MAGIC_VALUE
    except Exception:
        return False

client = EmuLoaderClient(validation_func=validate_base)

if client.is_connected():
    value = client.read_u32(MY_ROM_MAGIC_ADDRESS)
    print(f"ROM value: {value:#010x}")
    client.disconnect()
```

> **Note:** You must supply **either** `(signature_offset, signature_value)` **or** `validation_func`. Omitting both will raise a `ValueError`.

## Async Game Loop Integration

`wait_for_emulator` is designed to be called **at the very start of your async game logic loop** before any memory reads or writes. It blocks until an emulator is detected and — optionally — until your ROM validation passes. Once it returns you can safely proceed with game logic knowing the connection is ready.

The `validate` callback receives the **connected `EmuLoaderClient` instance** so you can use the full memory-read API to confirm game state:

```python
import asyncio
from emu_loader import EmuLoaderClient

MY_ROM_MAGIC_ADDRESS = 0x80123456
MY_ROM_MAGIC_VALUE   = 0xDEADBEEF

def rom_is_ready(client: EmuLoaderClient) -> bool:
    """Return True only when the correct ROM is loaded and ready."""
    try:
        return client.read_u32(MY_ROM_MAGIC_ADDRESS) == MY_ROM_MAGIC_VALUE
    except Exception:
        return False

async def game_loop():
    # Create the client once — pass the signature that identifies your ROM in RDRAM.
    client = EmuLoaderClient(signature_offset=0x759290, signature_value=0x52414D42)

    # Always call this first — it will retry until an emulator is found and the
    # optional validate callback returns True.
    await client.wait_for_emulator(validate=rom_is_ready)

    # From here the emulator is connected and the ROM is confirmed valid.
    while True:
        try:
            value = client.read_u32(0x807ED000)
            # ... your per-tick game logic ...
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Connection lost: {e}")
            # Re-enter the wait loop if the connection drops.
            await client.wait_for_emulator(validate=rom_is_ready)

asyncio.run(game_loop())
```

### DK64 Randomizer example

This is how the [DK64 Randomizer Archipelago client](https://github.com/2dos/DK64-Randomizer/pull/3318) uses EmuLoader:

```python
from emu_loader import EmuLoaderClient

def rom_ap_ready(n64_client: EmuLoaderClient) -> bool:
    """Return True once the ROM signals Archipelago is ready."""
    return (
        n64_client.read_u8(DK64MemoryMap.rom_flags)
        & DK64MemoryMap.rom_flag_ap_status
        == DK64MemoryMap.rom_flag_ap_status
    )

# Instantiate with the DK64 ROM signature — no validation_func needed for base detection.
self.n64_client = EmuLoaderClient(signature_offset=0x759290, signature_value=0x52414D42)

# Wait for an emulator AND for the ROM to signal it is AP-ready.
await self.n64_client.wait_for_emulator(validate=rom_ap_ready)
```

If you don't need ROM validation — for example you just want to wait until *any* emulator is running — omit the `validate` argument:

```python
await client.wait_for_emulator()
```

## ROM Validation

See [Usage](#usage) above for how to supply a ROM identity check via `signature_offset`/`signature_value` or `validation_func` — these are used during RDRAM base detection when the client first attaches to an emulator.

The `validate` callback on `wait_for_emulator` serves a different purpose: it receives the **already-connected `EmuLoaderClient`** and lets you confirm in-game state (e.g. an AP-status flag) before your game loop proceeds. Adapt the address and expected value to whatever sentinel your ROM exposes.

## Memory Access

All addresses should be N64 virtual addresses (e.g. `0x80xxxxxx`). The library strips the high bit and applies byte-swap corrections automatically.

| Method | Description |
|---|---|
| `read_u8(address)` | Read 8-bit unsigned int |
| `read_u16(address)` | Read 16-bit unsigned int |
| `read_u32(address)` | Read 32-bit unsigned int |
| `write_u8(address, value)` | Write 8-bit unsigned int |
| `write_u16(address, value)` | Write 16-bit unsigned int |
| `write_u32(address, value)` | Write 32-bit unsigned int |
| `read_bytestring(address, length)` | Read a string from memory |
| `write_bytestring(address, data)` | Write a sanitized string to memory |

## Local Installation

```bash
pip install emu-loader
```

Install a specific tagged release directly from GitHub:

```bash
pip install git+https://github.com/Killklli/EmuLoader.git@v1.0.0
```

Or always track the latest commit on `main`:

```bash
pip install git+https://github.com/Killklli/EmuLoader.git@main
```

Or install from a local clone:

```bash
pip install .
```
