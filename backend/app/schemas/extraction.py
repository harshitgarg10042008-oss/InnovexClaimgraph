from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Extracted(StrictBaseModel, Generic[T]):
    value: T | None = Field(default=None, description="The extracted value")
    source_text: str | None = Field(
        default=None, description="Exact verbatim text snippet from the document page"
    )


# --- PO ---
class POLine(StrictBaseModel):
    item_code: Extracted[str] = Field(default_factory=Extracted)
    description: Extracted[str] = Field(default_factory=Extracted)
    hsn: Extracted[str] = Field(default_factory=Extracted)
    qty: Extracted[str] = Field(default_factory=Extracted)
    unit: Extracted[str] = Field(default_factory=Extracted)
    rate: Extracted[str] = Field(default_factory=Extracted)


class POExtraction(StrictBaseModel):
    po_no: Extracted[str] = Field(default_factory=Extracted)
    po_date: Extracted[str] = Field(default_factory=Extracted)
    buyer_name: Extracted[str] = Field(default_factory=Extracted)
    supplier_name: Extracted[str] = Field(default_factory=Extracted)
    buyer_gstin: Extracted[str] = Field(default_factory=Extracted)
    supplier_gstin: Extracted[str] = Field(default_factory=Extracted)
    payment_terms_text: Extracted[str] = Field(default_factory=Extracted)
    credit_days: Extracted[int] = Field(default_factory=Extracted)
    lines: list[POLine] = Field(default_factory=list)
    gst_rate_pct: Extracted[str] = Field(default_factory=Extracted)
    taxable_total: Extracted[str] = Field(default_factory=Extracted)
    grand_total: Extracted[str] = Field(default_factory=Extracted)


# --- CHALLAN ---
class ChallanLine(StrictBaseModel):
    item_description: Extracted[str] = Field(default_factory=Extracted)
    dispatched_qty: Extracted[str] = Field(default_factory=Extracted)
    accepted_qty: Extracted[str] = Field(default_factory=Extracted)
    rejected_qty: Extracted[str] = Field(default_factory=Extracted)
    unit: Extracted[str] = Field(default_factory=Extracted)


class ChallanExtraction(StrictBaseModel):
    challan_no: Extracted[str] = Field(default_factory=Extracted)
    challan_date: Extracted[str] = Field(default_factory=Extracted)
    po_ref: Extracted[str] = Field(default_factory=Extracted)
    supplier_name: Extracted[str] = Field(default_factory=Extracted)
    buyer_name: Extracted[str] = Field(default_factory=Extracted)
    lines: list[ChallanLine] = Field(default_factory=list)
    stamp_text: Extracted[str] = Field(default_factory=Extracted)
    stamp_date: Extracted[str] = Field(default_factory=Extracted)
    received_by: Extracted[str] = Field(default_factory=Extracted)
    rejection_reason: Extracted[str] = Field(default_factory=Extracted)
    remarks: Extracted[str] = Field(default_factory=Extracted)


# --- INVOICE ---
class InvoiceLine(StrictBaseModel):
    description: Extracted[str] = Field(default_factory=Extracted)
    hsn: Extracted[str] = Field(default_factory=Extracted)
    qty: Extracted[str] = Field(default_factory=Extracted)
    rate: Extracted[str] = Field(default_factory=Extracted)
    amount: Extracted[str] = Field(default_factory=Extracted)


class InvoiceExtraction(StrictBaseModel):
    invoice_no: Extracted[str] = Field(default_factory=Extracted)
    invoice_date: Extracted[str] = Field(default_factory=Extracted)
    po_ref: Extracted[str] = Field(default_factory=Extracted)
    challan_ref: Extracted[str] = Field(default_factory=Extracted)
    supplier_name: Extracted[str] = Field(default_factory=Extracted)
    buyer_name: Extracted[str] = Field(default_factory=Extracted)
    supplier_gstin: Extracted[str] = Field(default_factory=Extracted)
    buyer_gstin: Extracted[str] = Field(default_factory=Extracted)
    lines: list[InvoiceLine] = Field(default_factory=list)
    taxable_total: Extracted[str] = Field(default_factory=Extracted)
    gst_amount: Extracted[str] = Field(default_factory=Extracted)
    grand_total: Extracted[str] = Field(default_factory=Extracted)


# --- BANK_STATEMENT ---
class BankTransaction(StrictBaseModel):
    date: Extracted[str] = Field(default_factory=Extracted)
    narration: Extracted[str] = Field(default_factory=Extracted)
    credit: Extracted[str] = Field(default_factory=Extracted)
    debit: Extracted[str] = Field(default_factory=Extracted)
    utr: Extracted[str] = Field(default_factory=Extracted)


class BankStatementExtraction(StrictBaseModel):
    account_holder: Extracted[str] = Field(default_factory=Extracted)
    period_from: Extracted[str] = Field(default_factory=Extracted)
    period_to: Extracted[str] = Field(default_factory=Extracted)
    transactions: list[BankTransaction] = Field(default_factory=list)


# --- REMITTANCE ---
class RemittanceExtraction(StrictBaseModel):
    remittance_date: Extracted[str] = Field(default_factory=Extracted)
    invoice_refs: list[Extracted[str]] = Field(default_factory=list)
    gross_amount: Extracted[str] = Field(default_factory=Extracted)
    tds_amount: Extracted[str] = Field(default_factory=Extracted)
    net_amount: Extracted[str] = Field(default_factory=Extracted)
    utr: Extracted[str] = Field(default_factory=Extracted)


# --- EMAIL ---
class EmailMessage(StrictBaseModel):
    date: Extracted[str] = Field(default_factory=Extracted)
    sender: Extracted[str] = Field(default_factory=Extracted)
    text_snippet: Extracted[str] = Field(default_factory=Extracted)


CommunicationKind = Literal[
    "acceptance",
    "objection",
    "backorder",
    "promise_to_pay",
    "acknowledgment",
    "other",
]


class EmailCommunication(StrictBaseModel):
    kind: Extracted[CommunicationKind] = Field(default_factory=Extracted)
    message_date: Extracted[str] = Field(default_factory=Extracted)
    quote: Extracted[str] = Field(default_factory=Extracted)


class EmailExtraction(StrictBaseModel):
    messages: list[EmailMessage] = Field(default_factory=list)
    communications: list[EmailCommunication] = Field(default_factory=list)


# --- UDYAM_CERT ---
class UdyamCertExtraction(StrictBaseModel):
    udyam_no: Extracted[str] = Field(default_factory=Extracted)
    enterprise_name: Extracted[str] = Field(default_factory=Extracted)
    enterprise_type: Extracted[str] = Field(default_factory=Extracted)
    activity: Extracted[str] = Field(default_factory=Extracted)
    registration_date: Extracted[str] = Field(default_factory=Extracted)


# --- CLASSIFICATION ---
class ClassificationResult(BaseModel):
    kind: str
    confidence: float
    evidence_quote: str | None = None
    method: str = "regex"  # "regex" or "llm"
