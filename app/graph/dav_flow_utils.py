import re
from typing import Any, Dict, Optional, Annotated
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from app.models.state import ProcessState
import json
from typing import Any, Dict, List, Tuple
from app.llms import llm  # teu AzureOpenAI
from app.prompts.intent_prompt import INTENT_ROUTER_SYSTEM

SET_DAV_FIELD_TOOL = {
    "type": "function",
    "function": {
        "name": "set_dav_field",
        "description": "Atualiza um campo da DAV (state.dados_carro). Usa código (ex: '61') ou key completa.",
        "parameters": {
            "type": "object",
            "properties": {
                "field": {"type": "string", "description": "Ex: '61' ou '61:' ou '61:Número da matrícula definitiva'"},
                "value": {"description": "Valor a colocar (ignorado se clear=true)"},
                "clear": {"type": "boolean", "description": "Se true, mete None", "default": False},
            },
            "required": ["field"]
        }
    }
}




def _resolve_key(dados_carro: Dict[str, Any], field: str) -> str:
    # aceita "61", "61:", "61:Descrição completa"
    if field in dados_carro:
        return field

    f = field.strip()
    if re.fullmatch(r"\d{2,3}", f):
        f = f + ":"

    for k in dados_carro.keys():
        if k.startswith(f):
            return k

    # fallback: mantém normalizado
    return f


def set_dav_field(state, field: str, value: Optional[Any] = None, clear: bool = False) -> Dict[str, Any]:
    state.dados_carro = state.dados_carro or {}
    key = _resolve_key(state.dados_carro, field)

    old = state.dados_carro.get(key)
    new = None if clear else value
    state.dados_carro[key] = new

    return {"ok": True, "field_resolved": key, "old": old, "new": new}


def _is_missing(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")

def find_missing_fields(dados_carro: Dict[str, Any]) -> List[str]:
    """Devolve lista de keys que estão em falta (None/empty)."""
    if not dados_carro:
        return []
    return [k for k, v in dados_carro.items() if _is_missing(v)]

def pick_questions(missing: List[str], max_q: int = 6) -> List[str]:
    """
    Heurística simples: pergunta primeiro códigos “core” da DAV.
    Se não existirem no missing, completa com o resto.
    """
    priority_prefixes = [
        "01:", "02:", "05:", "06:", "14:", "17:",
        "33:", "58:", "61:", "66a:", "67:",
        "69:", "70:", "78:", "79:",
        "DC03:", "DC07:", "DC09:", "DC12:", "DC16:", "DC21:", "DC26:", "DC27:",
    ]

    chosen = []
    # 1) pega prioridades
    for p in priority_prefixes:
        for k in missing:
            if k.startswith(p) and k not in chosen:
                chosen.append(k)
                if len(chosen) >= max_q:
                    return chosen

    # 2) completa
    for k in missing:
        if k not in chosen:
            chosen.append(k)
            if len(chosen) >= max_q:
                break
    return chosen



async def llm_route_intent(user_msg: str) -> dict:
    resp = llm.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": INTENT_ROUTER_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=120,
        response_format={"type": "json_object"},
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return {"intent": "answer_fields", "confidence": 0.0, "reason": "invalid_json_fallback"}
    return out


