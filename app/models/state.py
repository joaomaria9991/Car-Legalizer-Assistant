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
    fase_atual: str
    sub_fase: str
    dados_carro: CarData
    docs: Dict[str, Any]
    flags: Dict[str, bool]
    prazos: Dict[str, str]
    historico: List[str]
