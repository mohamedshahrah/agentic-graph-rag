from graphrag.config.settings import OCRCfg, Secrets
from graphrag.core.errors import ConfigError
from graphrag.ocr.base import OCREngine


def build_ocr(cfg: OCRCfg, secrets: Secrets) -> OCREngine:
    if cfg.engine == "vision_llm":
        from graphrag.ocr.vision_llm import VisionLLMOCR

        return VisionLLMOCR(cfg, secrets)
    if cfg.engine == "tesseract":
        from graphrag.ocr.tesseract import TesseractOCR

        return TesseractOCR(cfg)
    raise ConfigError(f"Unknown OCR engine: {cfg.engine}")


__all__ = ["OCREngine", "build_ocr"]
