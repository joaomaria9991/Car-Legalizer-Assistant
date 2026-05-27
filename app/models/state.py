from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CarData(BaseModel):
    vin: Optional[str] = None
    marca: Optional[str] = None
    modelo: Optional[str] = None
    ano: Optional[int] = None


class DocInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    category: Optional[str] = None
    pages: List[str] = Field(default_factory=list)
    filename: Optional[str] = None
    confidence: Optional[float] = None
    status: Optional[str] = None


class UiOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Optional[str] = None
    message: Optional[str] = None
    fields: List[Any] = Field(default_factory=list)
    assistant_message: Optional[str] = None
    applied: List[Dict[str, Any]] = Field(default_factory=list)


class DavFieldMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    origin: Literal["extracted", "induced", "user", "missing", "conflict", "not_applicable"] = "missing"
    status: Literal["filled", "missing", "needs_review", "conflict", "not_applicable"] = "missing"
    reason: Optional[str] = None
    source: Optional[str] = None
    source_doc: Optional[str] = None
    source_page: Optional[str] = None
    confidence: Optional[float] = None
    value: Any = None
    alternatives: List[Dict[str, Any]] = Field(default_factory=list)


class ProcessState(BaseModel):
    process_id: str
    fase_atual: str = "INTAKE_DOCS"
    sub_fase: str = "AGUARDAR_UPLOAD"
    dados_carro: Dict[str, Any] = Field(default_factory=dict)
    dados_fiscal: Dict[str, Any] = Field(default_factory=dict)
    docs: Dict[str, Any] = Field(default_factory=dict)
    flags: Dict[str, Any] = Field(default_factory=dict)
    prazos: Dict[str, Any] = Field(default_factory=dict)
    historico: List[str] = Field(default_factory=list)
