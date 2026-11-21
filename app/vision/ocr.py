"""OCR 引擎封装：默认 RapidOCR（ONNX，轻量、无需 GPU / PyTorch / Paddle）。"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class OCRHit:
    text: str
    score: float
    box: Any = None


class OCREngine(ABC):
    name = "base"

    @abstractmethod
    def recognize(self, frame: Any) -> list[OCRHit]:
        ...


class RapidOCREngine(OCREngine):
    name = "rapidocr"

    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR  # 延迟导入，首次加载模型较慢
        self._engine = RapidOCR()

    def recognize(self, frame: Any) -> list[OCRHit]:
        result, _ = self._engine(frame)
        hits: list[OCRHit] = []
        for item in result or []:
            try:
                box, text, score = item[0], item[1], item[2]
                hits.append(OCRHit(str(text).strip(), float(score), box))
            except (IndexError, TypeError, ValueError):
                continue
        return hits


class NullOCREngine(OCREngine):
    """依赖不可用时的降级实现，保证主链路（数据层）不受影响。"""

    name = "none"

    def __init__(self, reason: str = ""):
        self.reason = reason

    def recognize(self, frame: Any) -> list[OCRHit]:
        return []


def create_engine(backend: str = "rapidocr") -> OCREngine:
    backend = (backend or "rapidocr").lower()
    if backend in ("rapidocr", "auto", ""):
        try:
            return RapidOCREngine()
        except Exception as exc:  # noqa: BLE001
            log.warning("RapidOCR 初始化失败，画面模块降级: %s", exc)
            return NullOCREngine(f"{type(exc).__name__}: {exc}")
    if backend == "none":
        return NullOCREngine("配置关闭")
    return NullOCREngine(f"未知后端: {backend}")
