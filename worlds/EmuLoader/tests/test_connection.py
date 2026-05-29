"""
Integration smoke-test — requires a running emulator with a ROM loaded.

This is intentionally kept separate from the unit tests so CI can skip it.
Run manually with:

    python tests/test_connection.py

To run the full unit-test suite instead use:

    python -m pytest tests/
"""

from emu_loader import EmuLoaderClient


def _validation(pm, offset) -> bool:
    """Accept any candidate offset during the smoke test."""
    return True


def main():
    client = EmuLoaderClient(_validation)

    print("Attempting to connect to emulator...")
    if client.is_connected():
        print("✓ Connected successfully!")

        try:
            val = client.read_u32(0x80000300)
            print(f"✓ Memory read OK - 0x80000300 = 0x{val:08X}")
        except Exception as e:
            print(f"✗ Memory read failed: {e}")

        client.disconnect()
        print("✓ Disconnected cleanly.")
    else:
        print("✗ Could not connect to any emulator. Make sure one is running with a ROM loaded.")


if __name__ == "__main__":
    main()
