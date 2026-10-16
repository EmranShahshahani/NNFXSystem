"""Data layer: raw feeds -> normalised UTC OHLCV bars (doc 02 §3.1).

The session-close convention is applied here (``session.resample_to_daily``)
and nowhere else. Downstream code never re-times a bar.
"""

from nnfx.data.bars import BarFrame, BarFrameError, VolumeKind

__all__ = ["BarFrame", "BarFrameError", "VolumeKind"]
