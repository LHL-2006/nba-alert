"""画面识别包：抓帧 / OCR / 在场判定 / 工作线程。"""
from .ocr import OCRHit, OCREngine, RapidOCREngine, create_engine
from .presence import PresenceConfig, PresenceTracker
from .stream import Frame, FrameGrabber, probe_m3u8
from .worker import VisionWorker

__all__ = [
    "OCRHit", "OCREngine", "RapidOCREngine", "create_engine",
    "PresenceConfig", "PresenceTracker",
    "Frame", "FrameGrabber", "probe_m3u8", "VisionWorker",
]
