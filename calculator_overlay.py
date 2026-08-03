"""
Always-on-top corner overlay for Lunix's AI Trade Assistant.

Usage:
  python calculator_overlay.py
  python calculator_overlay.py --corner top-right
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "trade_calculator.html"


def screen_size() -> tuple[int, int]:
    user32 = ctypes.windll.user32
    return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))


def corner_pos(
    corner: str, width: int, height: int, margin: int = 16
) -> tuple[int, int]:
    sw, sh = screen_size()
    # Leave room for the Windows taskbar on the bottom edge
    taskbar = 48
    positions = {
        "bottom-right": (sw - width - margin, sh - height - margin - taskbar),
        "bottom-left": (margin, sh - height - margin - taskbar),
        "top-right": (sw - width - margin, margin),
        "top-left": (margin, margin),
    }
    return positions.get(corner, positions["bottom-right"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lunix's AI Trade Assistant screen overlay"
    )
    parser.add_argument(
        "--corner",
        choices=("bottom-right", "bottom-left", "top-right", "top-left"),
        default="bottom-right",
    )
    parser.add_argument("--width", type=int, default=460)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    if not HTML.exists():
        print(f"Missing {HTML}. Run: python build_trade_calculator.py")
        return 1

    try:
        import webview
    except ImportError:
        print("Installing pywebview...")
        import subprocess

        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pywebview"],
            stdout=subprocess.DEVNULL,
        )
        import webview

    x, y = corner_pos(args.corner, args.width, args.height)
    webview.create_window(
        "Lunix's AI Trade Assistant",
        HTML.resolve().as_uri(),
        width=args.width,
        height=args.height,
        x=x,
        y=y,
        on_top=True,
        resizable=True,
        background_color="#07060c",
    )
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
