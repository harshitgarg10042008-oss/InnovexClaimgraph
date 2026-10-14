import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import fitz  # PyMuPDF
import numpy as np
import pytesseract
from PIL import Image
from pydantic import BaseModel
from pytesseract import Output

logger = logging.getLogger("claimgraph.ingest.read")


class WordBox(BaseModel):
    text: str
    bbox: list[float]  # [x0, y0, x1, y1] normalized (0.0 to 1.0)
    confidence: float  # 0.0 to 1.0


class PageReadResult(BaseModel):
    page_no: int
    text: str
    words: list[WordBox]
    image_rel_path: str
    ocr_engine: str


def preprocess_image_for_ocr(
    img_bgr_or_rgb: np.ndarray,
    upscale: bool = True,
) -> tuple[np.ndarray, float]:
    """Applies grayscale, contrast enhancement (CLAHE), Hough deskew, 2x upscale, and adaptive threshold.

    Returns the processed binary image and the detected skew angle in degrees.
    """
    if len(img_bgr_or_rgb.shape) == 3:
        gray = cv2.cvtColor(img_bgr_or_rgb, cv2.COLOR_BGR2GRAY)
    else:
        gray = img_bgr_or_rgb.copy()

    # 1. Contrast enhancement via CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrast = clahe.apply(gray)

    # 2. Deskew detection using Canny + HoughLines
    edges = cv2.Canny(contrast, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
    angles: list[float] = []
    if lines is not None:
        for line in lines:
            rho, theta = line[0]
            angle = (theta * 180.0 / np.pi) - 90.0
            if -15.0 < angle < 15.0 and abs(angle) > 0.1:
                angles.append(float(angle))

    detected_angle = float(np.median(angles)) if angles else 0.0

    (h, w) = gray.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, detected_angle, 1.0)
    deskewed = cv2.warpAffine(
        contrast, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )

    if upscale:
        deskewed = cv2.resize(deskewed, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

    # 3. Adaptive thresholding for crisp OCR binarization
    thresh = cv2.adaptiveThreshold(
        deskewed, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 10
    )

    return thresh, detected_angle


class OcrEngine(ABC):
    @abstractmethod
    def read(self, image: Image.Image | np.ndarray) -> tuple[str, list[WordBox]]:
        """Extracts text and word boxes with normalized coordinates."""
        pass


class TesseractOcrEngine(OcrEngine):
    def __init__(self, psm: int = 6):
        self.psm = psm

    def read(self, image: Image.Image | np.ndarray) -> tuple[str, list[WordBox]]:
        if isinstance(image, Image.Image):
            np_img = np.array(image.convert("RGB"))
        else:
            np_img = image

        processed_img, _ = preprocess_image_for_ocr(np_img)
        h, w = processed_img.shape[:2]

        data = pytesseract.image_to_data(
            processed_img,
            config=f"--psm {self.psm}",
            output_type=Output.DICT,
        )

        word_boxes: list[WordBox] = []
        words_text: list[str] = []

        for i in range(len(data["text"])):
            w_text = str(data["text"][i]).strip()
            raw_conf = data["conf"][i]
            try:
                conf_val = float(raw_conf)
            except (ValueError, TypeError):
                conf_val = -1.0

            if w_text and conf_val >= 0:
                left = float(data["left"][i])
                top = float(data["top"][i])
                width = float(data["width"][i])
                height = float(data["height"][i])

                norm_box = [
                    round(left / w, 4),
                    round(top / h, 4),
                    round(min(1.0, (left + width) / w), 4),
                    round(min(1.0, (top + height) / h), 4),
                ]
                norm_conf = round(conf_val / 100.0, 4)

                word_boxes.append(
                    WordBox(text=w_text, bbox=norm_box, confidence=norm_conf)
                )
                words_text.append(w_text)

        full_text = " ".join(words_text)
        return full_text, word_boxes


default_ocr_engine = TesseractOcrEngine()


def read_document_pages(
    file_path: Path,
    document_id: str,
    storage_base: Path,
    ocr_engine: OcrEngine | None = None,
) -> list[PageReadResult]:
    """Reads all pages of a PDF or image file.

    Generates page PNGs (150 DPI), extracts text + word boxes, and stores page word boxes as JSON.
    """
    engine = ocr_engine or default_ocr_engine
    pages_dir = storage_base / "pages" / document_id
    pages_dir.mkdir(parents=True, exist_ok=True)

    suffix = file_path.suffix.lower()
    results: list[PageReadResult] = []

    if suffix == ".pdf":
        doc = fitz.open(file_path)
        for page_idx in range(len(doc)):
            page_no = page_idx + 1
            page = doc[page_idx]

            # Render page to PNG at 150 DPI
            pixmap = page.get_pixmap(dpi=150)
            img_rel_path = f"pages/{document_id}/page_{page_no}.png"
            img_full_path = storage_base / img_rel_path
            pixmap.save(img_full_path)

            raw_text = page.get_text("text").strip()

            # If page text layer has fewer than 40 characters, fallback to OCR
            if len(raw_text) < 40:
                logger.info(
                    f"Page {page_no} of {file_path.name} has only {len(raw_text)} chars. Falling back to OCR."
                )
                pil_img = Image.open(img_full_path)
                ocr_text, word_boxes = engine.read(pil_img)
                used_engine = "tesseract"
                effective_text = ocr_text
            else:
                pw, ph = page.rect.width, page.rect.height
                raw_words = page.get_text("words")
                word_boxes = []
                for w_tuple in raw_words:
                    x0, y0, x1, y1, word_str = (
                        w_tuple[0],
                        w_tuple[1],
                        w_tuple[2],
                        w_tuple[3],
                        w_tuple[4],
                    )
                    word_boxes.append(
                        WordBox(
                            text=word_str,
                            bbox=[
                                round(x0 / pw, 4),
                                round(y0 / ph, 4),
                                round(min(1.0, x1 / pw), 4),
                                round(min(1.0, y1 / ph), 4),
                            ],
                            confidence=1.0,
                        )
                    )
                used_engine = "pymupdf"
                effective_text = raw_text

            # Save word boxes to JSON
            boxes_rel_path = f"pages/{document_id}/page_{page_no}_boxes.json"
            boxes_full_path = storage_base / boxes_rel_path
            with open(boxes_full_path, "w", encoding="utf-8") as f:
                json.dump([wb.model_dump() for wb in word_boxes], f, indent=2)

            results.append(
                PageReadResult(
                    page_no=page_no,
                    text=effective_text,
                    words=word_boxes,
                    image_rel_path=img_rel_path,
                    ocr_engine=used_engine,
                )
            )

    elif suffix in (".jpg", ".jpeg", ".png"):
        page_no = 1
        pil_img = Image.open(file_path).convert("RGB")
        img_rel_path = f"pages/{document_id}/page_{page_no}.png"
        img_full_path = storage_base / img_rel_path
        pil_img.save(img_full_path, format="PNG")

        ocr_text, word_boxes = engine.read(pil_img)
        boxes_rel_path = f"pages/{document_id}/page_{page_no}_boxes.json"
        boxes_full_path = storage_base / boxes_rel_path
        with open(boxes_full_path, "w", encoding="utf-8") as f:
            json.dump([wb.model_dump() for wb in word_boxes], f, indent=2)

        results.append(
            PageReadResult(
                page_no=page_no,
                text=ocr_text,
                words=word_boxes,
                image_rel_path=img_rel_path,
                ocr_engine="tesseract",
            )
        )
    else:
        raise ValueError(f"Unsupported file format: {suffix}")

    return results
