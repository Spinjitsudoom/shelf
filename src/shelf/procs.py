"""Running helper programs (ffmpeg, Shelf's own measuring helpers) the same way on Linux,
macOS and Windows."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

WINDOWS = os.name == "nt"


def low_priority(nice: int = 10) -> dict:
    """subprocess arguments that run a helper at low priority, so measuring the library in
    the background never gets in the way of playing music. On Windows the helper also gets
    no window of its own."""
    if WINDOWS:
        return {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW}
    return {"preexec_fn": lambda: os.nice(nice)}


def no_window() -> dict:
    """subprocess arguments that keep a helper from flashing a console window on Windows."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}


def python_module(module: str, *args: str) -> list[str]:
    """The command that runs one of Shelf's modules as a helper: `python -m module`, or, in
    the packaged Windows app (a single program with no Python of its own), the program
    itself with `--module`."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--module", module, *args]
    return [sys.executable, "-m", module, *args]


def analysis_engine() -> str:
    """What measures tempo, key and "sounds like": Essentia where it's installed, otherwise
    Shelf's own numpy engine (shelf.dsp), e.g. on Windows. SHELF_ANALYSIS_ENGINE=dsp|essentia
    chooses (Essentia only if it's there)."""
    want = os.environ.get("SHELF_ANALYSIS_ENGINE", "").lower()
    if want == "dsp":
        return "dsp"
    return "essentia" if has_essentia() else "dsp"


def has_essentia() -> bool:
    """Whether the audio analysis library (tempo, key, "sounds like") is installed. It has no
    Windows version, so a Windows server goes without those measurements."""
    return importlib.util.find_spec("essentia") is not None
