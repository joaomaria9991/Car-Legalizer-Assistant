# app/main.py

import os
import json
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv

from app.storage.blob_client import BlobClient  # vamos criar/ajustar depois
from app.models.events import Event, SimpleResponse             # Event + EventType
from app.handlers.handlers import handle_dav_collect_fiscal, handle_extract_validate, handle_dav_collect_fiscal, handle_intake_docs,handle_dav_draft_generation


# mais tarde: from app.graph.nodes import process_event

load_dotenv()

app = FastAPI(title="Car Legalização API", version="0.1.0")

# CORS básico para desenvolvimento
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # em prod restringes
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

blob_client = BlobClient()




@app.get("/health", response_model=SimpleResponse)
async def health_check():
    return SimpleResponse(success=True, message="OK")


@app.get("/processes/{process_id}")
async def get_process_state(process_id: str):
    """
    Devolve o state.json (ou estado inicial se ainda não existir).
    """
    state = await blob_client.get_state(process_id)
    return state


# app/main.py (ou app/graph/router.py no futuro)

def route_event(state: dict, event: dict) -> dict:
    # EVENTOS GLOBAIS (válidos em qualquer fase)
    if event.get("type") == "advance_phase":
        data = event.get("data", {})
        state["fase_atual"] = data.get("nova_fase", state.get("fase_atual"))
        state["sub_fase"] = data.get("sub_fase", state.get("sub_fase"))
        state.setdefault("historico", []).append(f"Fase alterada manualmente para {state['fase_atual']}")
        return state
    
    # Routing por fase
    fase_atual = state.get("fase_atual", "INTAKE_DOCS")
    
    if fase_atual == "INTAKE_DOCS":
        return handle_intake_docs(state, event)
    elif fase_atual == "EXTRACT_VALIDATE":
        return handle_extract_validate(state, event)
    elif fase_atual == "DAV_FLOW":
        return handle_dav_collect_fiscal(state, event)
    elif fase_atual == "DAV_DRAFT_READY":  # ← NOVO
        return handle_dav_draft_generation(state, event)
    else:
        state.setdefault("historico", []).append(
            f"Evento ignorado na fase {fase_atual}: {event.get('type')}"
        )
        return state




@app.post("/processes/{process_id}/events")
async def handle_event(
    process_id: str,
    event_json: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    state = await blob_client.get_state(process_id)

    try:
        event = json.loads(event_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="event_json inválido")

    if file is not None:
        blob_path = f"processes/{process_id}/docs/{file.filename}"
        await blob_client.upload_file(blob_path, file)
        event.setdefault("data", {})
        event["data"]["blob_path"] = blob_path
        event["data"]["filename"] = file.filename

    new_state = route_event(state, event)

    await blob_client.save_state(process_id, new_state)

    return {
        "success": True,
        "fase_atual": new_state["fase_atual"],
        "sub_fase": new_state.get("sub_fase"),
        "state": new_state,
    }




if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
