from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from datetime import datetime



class CarData(BaseModel):
    vin: Optional[str] = None
    marca: Optional[str] = None
    modelo: Optional[str] = None
    ano: Optional[int] = None


class ProcessState(BaseModel):
    process_id: str
    fase_atual: str = "INTAKE_DOCS"
    sub_fase: str = "AGUARDAR_UPLOAD"
    dados_carro: Dict[str, Any] = {}
    dados_fiscal: Dict[str, Any] = {}
    docs: Dict[str, Any] = {}
    flags: Dict[str, Any] = {}
    prazos: Dict[str, Any] = {}
    docs: Dict[str, Any] = {}  # ← É ISTO
    historico: List[str] = []


