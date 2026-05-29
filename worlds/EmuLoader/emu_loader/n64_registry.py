"""N64 game-identification registry for emu_loader.

Provides a standardised contract for APWorlds to advertise their
game-identification data, and a discovery function to collect all
registered validators at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Dict, Optional, Union

if TYPE_CHECKING:
    from .process import ProcessMemory

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

ValidationFunc = Callable[["ProcessMemory", int], bool]
"""A callable ``(ProcessMemory, rdram_base: int) -> bool`` that confirms the
correct ROM is loaded in emulator memory."""


# ---------------------------------------------------------------------------
# Validator factory
# ---------------------------------------------------------------------------


def build_offset_value_validator(
    offset: int,
    expected: Union[bytes, int],
) -> ValidationFunc:
    """Return a :data:`ValidationFunc` that reads *length* bytes at
    ``rdram_base + offset`` and compares them to *expected*.

    Args:
        offset: Byte offset from ``rdram_base`` to read.
        expected: Expected value as :class:`bytes` or a single :class:`int`
            byte (encoded big-endian).

    Returns:
        A :data:`ValidationFunc` that returns ``True`` when the memory at
        the given offset matches *expected*.
    """
    if isinstance(expected, int):
        expected_bytes = expected.to_bytes(1, "big")
    else:
        expected_bytes = bytes(expected)
    length = len(expected_bytes)

    def _validator(pm: "ProcessMemory", rdram_base: int) -> bool:
        try:
            return pm.read_bytes(rdram_base + offset, length) == expected_bytes
        except Exception:
            return False

    return _validator


# ---------------------------------------------------------------------------
# N64ValidationInfo dataclass
# ---------------------------------------------------------------------------


@dataclass
class N64ValidationInfo:
    """Holds everything needed to identify one N64 game in emulator memory.

    Two identification strategies are supported — only one needs to be
    provided:

    * **Custom function** — a full :data:`ValidationFunc` callable (e.g. for
      pointer-chasing logic).
    * **Offset + value** — a simple byte comparison against a fixed offset
      from ``rdram_base``.  A :data:`ValidationFunc` is built automatically
      by :func:`build_offset_value_validator`.

    Use :meth:`effective_validator` to obtain a ready-to-call
    :data:`ValidationFunc` regardless of which strategy was used.
    """

    game_name: str
    """Human-readable name of the game (should match the APWorld ``game``
    attribute)."""

    validation_function: Optional[ValidationFunc] = field(default=None, repr=False)
    """Optional explicit validator.  Takes priority over offset+value."""

    validation_offset: Optional[int] = None
    """Byte offset from ``rdram_base`` used by the auto-built validator."""

    validation_value: Optional[Union[bytes, int]] = None
    """Expected bytes (or single byte as :class:`int`) at *validation_offset*."""

    def effective_validator(self) -> Optional[ValidationFunc]:
        """Return the best available :data:`ValidationFunc`.

        Priority order:

        1. :attr:`validation_function` if set.
        2. Auto-built validator from :attr:`validation_offset` +
           :attr:`validation_value` if both are set.
        3. ``None`` if no valid strategy is available.
        """
        if self.validation_function is not None:
            return self.validation_function
        if self.validation_offset is not None and self.validation_value is not None:
            return build_offset_value_validator(self.validation_offset, self.validation_value)
        return None

    def is_valid(self) -> bool:
        """Return ``True`` if :meth:`effective_validator` would return a
        callable (i.e. enough information has been provided to identify the
        game)."""
        return self.effective_validator() is not None


# ---------------------------------------------------------------------------
# N64WorldMixin
# ---------------------------------------------------------------------------


class N64WorldMixin:
    """Mixin that APWorlds subclass to advertise N64 game-identification data.

    Designed to be safe to import in environments where ``emu_loader`` is
    *not* installed (e.g. during Archipelago world generation), because no
    EmuLoader internals are referenced at class-definition time.

    Subclass example — simple ROM-header byte check::

        class MN64World(N64WorldMixin, World):
            game = "Mystical Ninja Starring Goemon"
            n64_validation_offset = 0x3B
            n64_validation_value  = b"\\x4E"

    Subclass example — custom pointer-chasing logic::

        class BanjoTooieWorld(N64WorldMixin, World):
            game = "Banjo-Tooie"
            n64_validation_function = staticmethod(validate_bt_signature)
    """

    n64_validation_function: Optional[ValidationFunc] = None
    n64_validation_offset: Optional[int] = None
    n64_validation_value: Optional[Union[bytes, int]] = None

    @classmethod
    def get_n64_validation_info(cls) -> Optional[N64ValidationInfo]:
        """Build and return an :class:`N64ValidationInfo` for this world.

        The ``game_name`` is taken from the class ``game`` attribute when
        present, falling back to the class name.

        Returns:
            An :class:`N64ValidationInfo` instance if sufficient
            identification data has been provided, otherwise ``None``.
        """
        game_name: str = getattr(cls, "game", cls.__name__)
        info = N64ValidationInfo(
            game_name=game_name,
            validation_function=cls.n64_validation_function,
            validation_offset=cls.n64_validation_offset,
            validation_value=cls.n64_validation_value,
        )
        return info if info.is_valid() else None


# ---------------------------------------------------------------------------
# Discovery function
# ---------------------------------------------------------------------------


def discover_n64_worlds() -> Dict[str, N64ValidationInfo]:
    """Discover all installed APWorlds that expose N64 validation data.

    Must be called *after* all worlds have been imported so that
    ``AutoWorldRegister`` is fully populated.  Supports two discovery
    strategies:

    1. **Formal mixin** — world class is a subclass of :class:`N64WorldMixin`.
    2. **Duck typing** — world class exposes ``n64_validation_function``
       and/or (``n64_validation_offset`` + ``n64_validation_value``) without
       inheriting the mixin.

    Returns:
        A dict mapping game name → :class:`N64ValidationInfo` for every
        discovered world whose :meth:`~N64ValidationInfo.is_valid` returns
        ``True``.
    """
    from worlds.AutoWorld import AutoWorldRegister  # type: ignore[import]

    results: Dict[str, N64ValidationInfo] = {}

    for game_name, world_cls in AutoWorldRegister.world_types.items():
        if not isinstance(world_cls, type):
            continue

        # Strategy 1: formal mixin subclass
        if issubclass(world_cls, N64WorldMixin):
            info = world_cls.get_n64_validation_info()
            if info is not None:
                results[game_name] = info
            continue

        # Strategy 2: duck typing
        has_func = callable(getattr(world_cls, "n64_validation_function", None))
        has_offset_value = (
            getattr(world_cls, "n64_validation_offset", None) is not None
            and getattr(world_cls, "n64_validation_value", None) is not None
        )
        if has_func or has_offset_value:
            info = N64ValidationInfo(
                game_name=game_name,
                validation_function=getattr(world_cls, "n64_validation_function", None),
                validation_offset=getattr(world_cls, "n64_validation_offset", None),
                validation_value=getattr(world_cls, "n64_validation_value", None),
            )
            if info.is_valid():
                results[game_name] = info

    return results
