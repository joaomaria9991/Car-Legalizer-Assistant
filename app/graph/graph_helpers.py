# app/graph/dav_graph_helpers.py
from __future__ import annotations

import json
from typing import Any

from app.llms import llm
from app.storage.blob_client import BlobClient
from app.prompts.classification_prompts import CLASSIFY_DOC_PROMPT
from app.prompts.dav_prompts import DAV_EXPLAIN_FIELDS_SYSTEM_PROMPT, DAV_FILL_FIELDS_SYSTEM_PROMPT

from app.models.state import ProcessState

from app.graph.dav_flow_utils import (
    set_dav_field,
    _resolve_key,
    SET_DAV_FIELD_TOOL,
)

# =========================
# CONFIG / PROMPTS (globals)
# =========================

MODEL_VISION = "gpt-4o"
MODEL_TEXT = "gpt-4o"



# =========================
# STATE HELPERS
# =========================

def get_event(state: ProcessState) -> dict:
    return (state.flags or {}).get("last_event") or {}

def ensure_flags(state: ProcessState) -> None:
    state.flags = state.flags or {}

def set_ui(state: ProcessState, payload: dict) -> None:
    ensure_flags(state)
    state.flags["ui_out"] = payload

def clear_flag(state: ProcessState, key: str) -> None:
    if state.flags and key in state.flags:
        state.flags.pop(key, None)

# =========================
# LLM HELPERS
# =========================

def llm_json(*, model: str, messages: list[dict], max_tokens: int = 800) -> dict:
    resp = llm.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    content = (resp.choices[0].message.content or "").strip()
    return json.loads(content) if content else {}

# =========================
# INTAKE / CLASSIFICATION HELPERS
# =========================

def group_blobs_by_doc(all_blobs: list[dict]) -> dict[str, list[dict]]:
    """
    Agrupa blobs por documento lógico:
    - Se tiver _page_ -> agrupa pelo base_name
    - Caso contrário, fica sozinho.
    Ordena por name para estabilizar ordem de páginas.
    """
    groups: dict[str, list[dict]] = {}
    for blob in all_blobs:
        filename = blob["name"].split("/")[-1]
        if "_page_" in filename:
            base = filename.split("_page_")[0]
            groups.setdefault(base, []).append(blob)
        else:
            groups.setdefault(filename, []).append(blob)

    for k in groups:
        groups[k] = sorted(groups[k], key=lambda b: b["name"])
    return groups

async def classify_first_page(*, blob_client: BlobClient, page_blob_name: str) -> dict:
    image_base64 = await blob_client.get_blob_as_base64(page_blob_name)

    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": CLASSIFY_DOC_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
        ],
    }]
    return llm_json(model=MODEL_VISION, messages=messages, max_tokens=500)

# =========================
# DAV TOOL-CALLING HELPER
# =========================

async def dav_run_tool_calling_turn(
    *,
    state: ProcessState,
    pending_fields: list[str],
    user_msg: str,
) -> tuple[str, list[dict]]:
    """
    Encapsula o turn:
    - 1a chamada com tools
    - executa tool_calls (com guardrail: só pending_fields)
    - 2a chamada "closing" para UX
    """
    subset = {k: (state.dados_carro or {}).get(k) for k in pending_fields}

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": DAV_FILL_FIELDS_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"PENDING_FIELDS:\n{json.dumps(pending_fields, ensure_ascii=False)}\n\n"
            f"ESTADO_SUBSET:\n{json.dumps(subset, ensure_ascii=False)}\n\n"
            f"RESPOSTA_USER:\n{user_msg}"
        )},
    ]

    resp = llm.chat.completions.create(
        model=MODEL_TEXT,
        messages=messages,
        tools=[SET_DAV_FIELD_TOOL],
        tool_choice="auto",
        max_tokens=400,
    )

    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None) or []

    messages.append({
        "role": "assistant",
        "content": msg.content,
        "tool_calls": [tc.model_dump() if hasattr(tc, "model_dump") else tc for tc in tool_calls] if tool_calls else None
    })

    applied: list[dict] = []

    for tc in tool_calls:
        fn = tc.function.name
        args = json.loads(tc.function.arguments or "{}")

        if fn == "set_dav_field":
            field = args.get("field")
            if field:
                resolved = _resolve_key(state.dados_carro or {}, field)
                if resolved not in pending_fields:
                    result = {"ok": False, "error": f"Campo fora de PENDING_FIELDS: {resolved}"}
                else:
                    result = set_dav_field(
                        state,
                        field=field,
                        value=args.get("value"),
                        clear=bool(args.get("clear", False)),
                    )
            else:
                result = {"ok": False, "error": "field em falta"}
        else:
            result = {"ok": False, "error": f"Tool desconhecida: {fn}"}

        applied.append(result)

        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result, ensure_ascii=False),
        })

    resp2 = llm.chat.completions.create(
        model=MODEL_TEXT,
        messages=messages,
        max_tokens=250,
    )
    final_text = resp2.choices[0].message.content or ""
    return final_text, applied
