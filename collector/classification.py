"""Video classification vocabulary for STAXIS measurement quality."""

from enum import Enum


class VideoClassification(str, Enum):
    LIVE = "LIVE"
    REGULAR_VIDEO = "REGULAR_VIDEO"
    SHORT = "SHORT"
    PREMIERE = "PREMIERE"
    REPLAY = "REPLAY"
    UNKNOWN = "UNKNOWN"