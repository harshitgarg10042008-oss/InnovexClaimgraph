import re

from pydantic import BaseModel
from rapidfuzz import fuzz

from app.ingest.read import WordBox


class ProvenanceLocation(BaseModel):
    page_no: int = 1
    bbox: list[float] | None = None  # [x0, y0, x1, y1] normalized (0 to 1)
    match_score: float = 0.0  # 0.0 to 1.0
    found: bool = False
    reason: str | None = None


def normalize_token(t: str) -> str:
    return re.sub(r"[^\w\.-]", "", t).lower()


def locate_source_text(
    source_text: str | None,
    pages_words: dict[int, list[WordBox]],
) -> ProvenanceLocation:
    """Locates the verbatim snippet in the document pages using exact matching first,

    falling back to fuzzy sliding-window matching with rapidfuzz.
    """
    if not source_text or not source_text.strip():
        return ProvenanceLocation(
            page_no=1, bbox=None, match_score=0.0, found=False, reason="source not found"
        )

    target_tokens = [normalize_token(w) for w in source_text.split() if normalize_token(w)]
    if not target_tokens:
        return ProvenanceLocation(
            page_no=1, bbox=None, match_score=0.0, found=False, reason="source not found"
        )

    target_len = len(target_tokens)
    target_str = " ".join(target_tokens)

    best_match: ProvenanceLocation | None = None
    best_score = 0.0

    # 1. Exact sequence matching across each page
    for page_no, words in pages_words.items():
        if not words:
            continue
        page_norm_tokens = [normalize_token(w.text) for w in words]

        # Scan for exact token sequence
        for i in range(len(page_norm_tokens) - target_len + 1):
            window = page_norm_tokens[i : i + target_len]
            if window == target_tokens:
                matched_boxes = words[i : i + target_len]
                union_bbox = [
                    min(wb.bbox[0] for wb in matched_boxes),
                    min(wb.bbox[1] for wb in matched_boxes),
                    max(wb.bbox[2] for wb in matched_boxes),
                    max(wb.bbox[3] for wb in matched_boxes),
                ]
                return ProvenanceLocation(
                    page_no=page_no,
                    bbox=union_bbox,
                    match_score=1.0,
                    found=True,
                    reason=None,
                )

        # Also check substring match within single word (e.g. invoice number embedded in text)
        for i, wb in enumerate(words):
            token = page_norm_tokens[i]
            if target_str in token or token in target_str:
                if len(target_str) >= 3 and len(token) >= 3:
                    score = fuzz.ratio(token, target_str) / 100.0
                    if score > best_score:
                        best_score = score
                        best_match = ProvenanceLocation(
                            page_no=page_no,
                            bbox=wb.bbox,
                            match_score=round(score, 4),
                            found=score >= 0.75,
                            reason=None if score >= 0.75 else "low similarity score",
                        )

    # 2. Fuzzy sliding-window matching using rapidfuzz
    for page_no, words in pages_words.items():
        if not words:
            continue
        page_norm_tokens = [normalize_token(w.text) for w in words]
        n_words = len(page_norm_tokens)

        # Allow window size to vary by +/- 2 tokens
        for win_len in range(max(1, target_len - 1), min(n_words + 1, target_len + 3)):
            for i in range(n_words - win_len + 1):
                window_tokens = page_norm_tokens[i : i + win_len]
                window_str = " ".join(window_tokens)

                # Compute token similarity
                sim = fuzz.partial_ratio(target_str, window_str) / 100.0
                if sim > best_score:
                    best_score = sim
                    matched_boxes = words[i : i + win_len]
                    union_bbox = [
                        min(wb.bbox[0] for wb in matched_boxes),
                        min(wb.bbox[1] for wb in matched_boxes),
                        max(wb.bbox[2] for wb in matched_boxes),
                        max(wb.bbox[3] for wb in matched_boxes),
                    ]
                    best_match = ProvenanceLocation(
                        page_no=page_no,
                        bbox=union_bbox,
                        match_score=round(sim, 4),
                        found=sim >= 0.70,
                        reason=None if sim >= 0.70 else "source not found",
                    )

    if best_match and best_match.found:
        return best_match

    return ProvenanceLocation(
        page_no=1,
        bbox=None,
        match_score=round(best_score, 4),
        found=False,
        reason="source not found",
    )
