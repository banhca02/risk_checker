from __future__ import annotations

from enum import Enum
from typing import Optional, Generic, TypeVar
from pydantic import BaseModel, Field, ConfigDict


class DocumentType(str, Enum):
    COMMERCIAL_INVOICE = "commercial_invoice"
    PACKING_LIST = "packing_list"
    BILL_OF_LADING = "bill_of_lading"
    UNKNOWN = "unknown"


class Evidence(BaseModel):
    """Evidence supporting one extracted value."""
    page: Optional[int] = Field(default=None, description="1-based page number")
    quote: Optional[str] = Field(default=None, description="Exact or near-exact source text")
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


T = TypeVar('T')


class ExtractedField(BaseModel, Generic[T]):
    """Value + provenance. Missing/unknown values must remain None."""
    value: Optional[T] = None
    evidence: list[Evidence] = Field(default_factory=list)


class CommonDocumentData(BaseModel):
    """Truly shared part of every shipment document type.

    Deliberately slim: CI/PL/BL differ structurally (pricing lines, container
    summary, containers) and even the party field names differ per document
    (seller/buyer vs shipper/consignee) as required by FIELD_MAPPING in the
    validation matrix — so only infrastructure lives here.
    """
    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType
    # Provenance map: field name -> evidence entries
    field_evidence: dict[str, list[Evidence]] = Field(default_factory=dict)
    extraction_notes: list[str] = Field(default_factory=list)


class LineItemCI(BaseModel):
    """One goods line on a Commercial Invoice."""
    line_no: Optional[int] = None
    product_description: Optional[str] = None
    batch_no: Optional[str] = None
    quantity: Optional[float] = None
    package_unit: Optional[str] = None
    net_weight: Optional[float] = None
    # The sample CI has no per-line gross column; keep it optional.
    gross_weight: Optional[float] = None
    unit_price: Optional[float] = None
    # e.g. "USD/KG" — tells R15 whether price applies per weight or per unit.
    price_basis: Optional[str] = None
    line_amount: Optional[float] = None


class LineItemPL(BaseModel):
    """One goods line on a Packing List."""
    line_no: Optional[int] = None
    product_description: Optional[str] = None
    batch_no: Optional[str] = None
    container_no: Optional[str] = None
    seal_no: Optional[str] = None
    quantity: Optional[float] = None
    package_unit: Optional[str] = None
    net_weight: Optional[float] = None
    gross_weight: Optional[float] = None


class ContainerSummaryPL(BaseModel):
    """Container Summary block (Packing List page 2)."""
    container_no: Optional[str] = None
    seal_no: Optional[str] = None
    container_type: Optional[str] = None
    quantity: Optional[float] = None
    package_unit: Optional[str] = None
    net_weight: Optional[float] = None
    gross_weight: Optional[float] = None
    measurement_cbm: Optional[float] = None


class ContainerBL(BaseModel):
    """One container row on a Bill of Lading."""
    container_no: Optional[str] = None
    seal_no: Optional[str] = None
    quantity: Optional[float] = None
    package_unit: Optional[str] = None
    gross_weight: Optional[float] = None
    measurement_cbm: Optional[float] = None
    # Not on the sample BL; optional for other layouts.
    net_weight: Optional[float] = None
    description: Optional[str] = None


class CommercialInvoiceData(CommonDocumentData):
    document_type: DocumentType = DocumentType.COMMERCIAL_INVOICE

    invoice_no: Optional[str] = None
    invoice_date: Optional[str] = Field(default=None, description="ISO date YYYY-MM-DD when unambiguous")
    contract_no: Optional[str] = None
    currency: Optional[str] = None

    seller_name: Optional[str] = None
    seller_address: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_address: Optional[str] = None

    trade_term: Optional[str] = None
    port_of_loading: Optional[str] = None
    port_of_discharge: Optional[str] = None
    country_of_origin: Optional[str] = None
    shipping_marks: Optional[str] = None

    total_quantity: Optional[float] = None
    total_package_unit: Optional[str] = None
    total_net_weight: Optional[float] = None
    total_gross_weight: Optional[float] = None
    total_amount: Optional[float] = None

    payment_terms: Optional[str] = None
    items: list[LineItemCI] = Field(default_factory=list)


class PackingListData(CommonDocumentData):
    document_type: DocumentType = DocumentType.PACKING_LIST

    invoice_reference_no: Optional[str] = None
    reference_date: Optional[str] = Field(default=None, description="ISO date YYYY-MM-DD when unambiguous")

    seller_name: Optional[str] = None
    seller_address: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_address: Optional[str] = None

    shipping_marks: Optional[str] = None
    total_packages: Optional[float] = None
    total_package_unit: Optional[str] = None
    total_net_weight: Optional[float] = None
    total_gross_weight: Optional[float] = None
    measurement_cbm: Optional[float] = None

    items: list[LineItemPL] = Field(default_factory=list)
    container_summary: list[ContainerSummaryPL] = Field(default_factory=list)


class BillOfLadingData(CommonDocumentData):
    document_type: DocumentType = DocumentType.BILL_OF_LADING

    bl_no: Optional[str] = None
    booking_no: Optional[str] = None
    shipped_on_board_date: Optional[str] = Field(default=None, description="ISO date YYYY-MM-DD when unambiguous")
    issue_date: Optional[str] = Field(default=None, description="ISO date YYYY-MM-DD when unambiguous")

    shipper_name: Optional[str] = None
    shipper_address: Optional[str] = None
    consignee_name: Optional[str] = None
    consignee_address: Optional[str] = None

    notify_party: Optional[str] = None
    freight_term: Optional[str] = None
    pre_carriage: Optional[str] = None
    vessel_voyage: Optional[str] = None
    port_of_loading: Optional[str] = None
    port_of_discharge: Optional[str] = None
    place_of_delivery: Optional[str] = None

    total_packages: Optional[float] = None
    total_package_unit: Optional[str] = None
    total_gross_weight: Optional[float] = None
    total_measurement_cbm: Optional[float] = None

    containers: list[ContainerBL] = Field(default_factory=list)


