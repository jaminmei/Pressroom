"""
OCR Engine Wrapper - Using RapidOCR (ONNX-based)

RapidOCR is a lightweight OCR library that uses ONNX Runtime.
It's compatible with PaddleOCR models but more portable across different CPUs.
"""

import base64
import logging
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from rapidocr_onnxruntime import RapidOCR

logger = logging.getLogger(__name__)

# Lock for thread-safe engine creation
_engine_lock = threading.Lock()


class OCREngine:
    """
    OCR engine wrapper using RapidOCR (ONNX-based).

    This class provides a unified interface for OCR processing,
    supporting both file paths and base64 encoded images.
    """

    def __init__(
        self,
        model_name: str = "ppocrv5",
        lang: str = "ch",
        use_gpu: bool = False,
        use_angle_cls: bool = True,
        show_log: bool = False,
    ):
        """
        Initialize the OCR engine.

        Args:
            model_name: Name of the OCR model (for logging purposes)
            lang: Language for OCR ('ch', 'en', 'chinese_cht', 'korean', 'japan')
            use_gpu: Whether to use GPU acceleration (not supported in ONNX CPU mode)
            use_angle_cls: Whether to use angle classification
            show_log: Whether to show OCR logs
        """
        self.model_name = model_name
        self.lang = lang
        self.use_gpu = use_gpu
        self.use_angle_cls = use_angle_cls

        logger.info("Initializing RapidOCR angle_cls=%s", use_angle_cls)

        try:
            # Initialize RapidOCR with language parameter
            self.ocr = RapidOCR(
                lang=lang,
                use_angle_cls=use_angle_cls,
                print_verbose=show_log,
            )

            logger.info("RapidOCR initialized successfully")

        except Exception as err:
            logger.error("RapidOCR initialization failed error_type=%s", type(err).__name__)
            raise RuntimeError(
                f"RapidOCR initialization failed: {str(err)}. "
                "Please check that all dependencies are installed correctly."
            ) from err

    def process_image(self, image_path: str, config: Optional[dict] = None) -> List[Any]:
        """
        Process an image file and return OCR results.

        Args:
            image_path: Path to the image file
            config: Optional configuration with:
                - det_thresh: text detection threshold (0.1-0.9)
                - det_box_thresh: box confidence threshold (0.1-0.9)

        Returns:
            List of OCR results: [[box, text, confidence], ...]
            where box is a list of 4 corner coordinates
        """
        logger.debug("Processing image from file reference")

        # Validate file exists
        if not Path(image_path).exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        # Build kwargs for RapidOCR call
        call_kwargs = self._build_call_kwargs(config)

        # Run OCR with RapidOCR
        result, elapse_list = self.ocr(image_path, **call_kwargs)

        # Handle empty results
        if result is None or len(result) == 0:
            logger.warning("No text detected in image")
            return []

        # Calculate total elapsed time
        total_elapse = sum(elapse_list) if isinstance(elapse_list, (list, tuple)) else elapse_list

        # Convert to PaddleOCR-like format for compatibility
        ocr_results = []
        for item in result:
            box, text, confidence = item
            normalized_box = box.tolist() if hasattr(box, "tolist") else list(box)
            ocr_results.append([normalized_box, (text, float(confidence))])

        logger.debug(f"Detected {len(ocr_results)} text blocks in {total_elapse:.2f}ms")
        return ocr_results

    def process_base64(self, base64_data: str, config: Optional[dict] = None) -> List[Any]:
        """
        Process a base64 encoded image.

        Args:
            base64_data: Base64 encoded image string
            config: Optional configuration

        Returns:
            List of OCR results: [[box, (text, confidence)], ...]
        """
        logger.debug("Processing base64 encoded image")

        try:
            image_data = base64.b64decode(base64_data)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(image_data)
                temp_path = f.name

            try:
                return self.process_image(temp_path, config)
            finally:
                Path(temp_path).unlink(missing_ok=True)

        except Exception as err:
            logger.error("Base64 image processing failed error_type=%s", type(err).__name__)
            raise ValueError(f"Invalid base64 image data: {str(err)}") from err

    def is_gpu_available(self) -> bool:
        """Check if GPU is available for inference."""
        return False

    def get_model_info(self) -> dict:
        """Get information about the loaded model."""
        return {
            "model_name": self.model_name,
            "engine": "RapidOCR (ONNX Runtime)",
            "language": self.lang,
            "use_angle_cls": self.use_angle_cls,
            "gpu_available": self.is_gpu_available(),
        }

    @staticmethod
    def _build_call_kwargs(config: Optional[dict]) -> dict:
        """Build kwargs for RapidOCR.__call__() from config dict."""
        if not config:
            return {}
        kwargs: dict[str, float] = {}
        # RapidOCR __call__ accepts box_thresh and text_score
        det_box_thresh = config.get("det_box_thresh")
        if det_box_thresh is not None:
            kwargs["box_thresh"] = float(det_box_thresh)
        det_thresh = config.get("det_thresh")
        if det_thresh is not None:
            kwargs["text_score"] = float(det_thresh)
        return kwargs


class OCREngineManager:
    """Manages per-language OCR engine instances with thread-safe caching."""

    def __init__(self) -> None:
        self._engines: Dict[str, OCREngine] = {}
        self._lock = threading.Lock()

    def get_engine(
        self,
        lang: str = "ch",
        use_angle_cls: bool = True,
    ) -> OCREngine:
        """Get or create an OCR engine for the given language.

        Thread-safe: concurrent calls for the same language will only
        create one engine instance.
        """
        cache_key = f"{lang}:{use_angle_cls}"

        # Fast path: already cached
        engine = self._engines.get(cache_key)
        if engine is not None:
            return engine

        # Slow path: acquire lock and create
        with self._lock:
            # Double-check after acquiring lock
            engine = self._engines.get(cache_key)
            if engine is not None:
                return engine

            engine = OCREngine(
                model_name="ppocrv5",
                lang=lang,
                use_gpu=False,
                use_angle_cls=use_angle_cls,
                show_log=False,
            )
            self._engines[cache_key] = engine
            return engine
