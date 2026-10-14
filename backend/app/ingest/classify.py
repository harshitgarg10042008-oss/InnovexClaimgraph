import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings
from app.llm.client import llm_client
from app.llm.prompts import CLASSIFY_SYSTEM_PROMPT
from app.schemas.extraction import ClassificationResult

logger = logging.getLogger("claimgraph.ingest.classify")

DocKind = Literal[
    "PO",
    "CHALLAN",
    "INVOICE",
    "BANK_STATEMENT",
    "REMITTANCE",
    "EMAIL",
    "UDYAM_CERT",
    "OTHER",
]

PATTERNS: dict[str, list[tuple[str, int]]] = {
    "PO": [
        (r"\bpurchase\s+order\b", 16),
        (r"\bwork\s+order\b", 12),
        (r"\bvendor\s*/\s*supplier\b", 6),
        (r"\bbuyer\s*/\s*delivery\b", 6),
        (r"\bpo\s*no\b", 6),
        (r"\bpo\s*date\b", 6),
        (r"\bpayment\s+terms\b", 4),
        (r"\bvendor\s+code\b", 3),
        (r"\bpo\s+ref\b", -4),  # PO Ref appears in Challan/Invoice, deduct
    ],
    "CHALLAN": [
        (r"\bdelivery\s+challan\b", 12),
        (r"\bdelivery\s+note\b", 12),
        (r"(?<!delivery\s)\bchallan\b", 6),
        (r"\bchallan\s+no\b", 8),
        (r"\bdispatched\s+qty\b", 6),
        (r"\baccepted\s+qty\b", 6),
        (r"\bgoods\s+inward\b", 5),
        (r"\breceived\s+by\b", 4),
        (r"\bgate\s+2\b", 4),
        (r"\bpurchase\s+order\b", -6),
    ],
    "INVOICE": [
        (r"\btax\s+invoice\b", 12),
        (r"\bcommercial\s+invoice\b", 12),
        (r"\binvoice\s+no\b", 8),
        (r"\btaxable\s+value\b", 5),
        (r"\bgst\s+amount\b", 5),
        (r"\bgrand\s+total\b", 4),
        (r"\bcgst\b", 3),
        (r"\bsgst\b", 3),
    ],
    "BANK_STATEMENT": [
        (r"\bstatement\s+of\s+account\b", 12),
        (r"\bbank\s+statement\b", 12),
        (r"\baccount\s+statement\b", 12),
        (r"\bclosing\s+balance\b", 6),
        (r"\bopening\s+balance\b", 6),
        (r"\btransaction\s+details\b", 5),
        (r"\bwithdrawal\b", 4),
        (r"\bdeposit\b", 4),
    ],
    "REMITTANCE": [
        (r"\bremittance\s+advice\b", 12),
        (r"\bpayment\s+remittance\b", 12),
        (r"\bpayment\s+advice\b", 12),
        (r"\btds\s+deducted\b", 6),
        (r"\bgross\s+passed\b", 6),
        (r"\bnet\s+payable\b", 6),
        (r"\bpayment\s+mode\b", 4),
    ],
    "EMAIL": [
        (r"\bfrom:\s*[\w\.-]+@", 12),
        (r"\bsubject:", 8),
        (r"\bto:\s*[\w\.-]+@", 8),
        (r"\bwrote:\b", 6),
        (r"\bbackorder\b", 5),
        (r"\bregards,\b", 4),
    ],
    "UDYAM_CERT": [
        (r"\budyam\s+registration\s+certificate\b", 14),
        (r"\budyam\b", 8),
        (r"\bministry\s+of\s+micro\b", 8),
        (r"\bmsme\b", 5),
        (r"\btype\s+of\s+enterprise\b", 6),
    ],
}


class LLMClassificationResponse(BaseModel):
    kind: str = Field(description="One of PO, CHALLAN, INVOICE, BANK_STATEMENT, REMITTANCE, EMAIL, UDYAM_CERT, OTHER")
    confidence: float = Field(default=0.9, description="Confidence score from 0.0 to 1.0")
    evidence_quote: str = Field(description="Exact snippet from document supporting the classification")


def classify_document(text: str, doc_hash: str | None = None) -> ClassificationResult:
    """Classifies document text using weighted regex rules first, falling back to LLM only if ambiguous."""
    clean_text = text.lower()

    scores: dict[str, int] = {}
    matched_quotes: dict[str, str] = {}

    for kind, rule_list in PATTERNS.items():
        kind_score = 0
        first_match_quote = ""
        for pat, weight in rule_list:
            m = re.search(pat, clean_text)
            if m:
                kind_score += weight
                if not first_match_quote:
                    start = max(0, m.start() - 20)
                    end = min(len(text), m.end() + 20)
                    first_match_quote = text[start:end].strip()
        scores[kind] = max(0, kind_score)
        matched_quotes[kind] = first_match_quote

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_kind, top_score = sorted_scores[0]
    second_kind, second_score = sorted_scores[1]

    # Deterministic clear match: high top score and decisive margin
    if top_score >= 8 and (top_score - second_score) >= 3:
        logger.info(f"Classified document as {top_kind} via regex (score={top_score}, margin={top_score - second_score})")
        return ClassificationResult(
            kind=top_kind,
            confidence=0.95,
            evidence_quote=matched_quotes.get(top_kind),
            method="regex",
        )

    # Ambiguous: call LLM
    logger.info(
        f"Regex classification ambiguous (top={top_kind}:{top_score}, second={second_kind}:{second_score}). Calling LLM..."
    )
    user_prompt = f"Please classify the following document text:\n\n---\n{text[:3000]}\n---"
    try:
        llm_resp = llm_client.complete_json(
            system=CLASSIFY_SYSTEM_PROMPT,
            user=user_prompt,
            pydantic_model=LLMClassificationResponse,
            model=settings.LLM_CLASSIFY_MODEL,
            doc_hash=doc_hash,
            page_range="1",
        )
        if llm_resp and llm_resp.kind in PATTERNS:
            return ClassificationResult(
                kind=llm_resp.kind,
                confidence=round(llm_resp.confidence, 2),
                evidence_quote=llm_resp.evidence_quote,
                method="llm",
            )
    except Exception as e:
        logger.warning(f"LLM classification failed: {e}. Falling back to best regex score.")

    # Fallback to top regex kind if score > 0, else OTHER
    final_kind = top_kind if top_score > 0 else "OTHER"
    return ClassificationResult(
        kind=final_kind,
        confidence=0.6 if top_score > 0 else 0.3,
        evidence_quote=matched_quotes.get(top_kind) or None,
        method="regex",
    )
