from pydantic import BaseModel
from enum import Enum
from typing import Optional, Dict, Any

class EventType(str, Enum):
    UPLOAD_DOC = "upload_doc"
    CONFIRMAR_DADOS = "confirmar_dados"
    USER_QUESTION = "user_question"

class Event(BaseModel):
    type: EventType
    data: Dict[str, Any]


class SimpleResponse(BaseModel):
    success: bool
    message: str
