# app/main.py

import os
import json
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv

from app.storage.blob_client import BlobClient  
from app.models.events import Event, SimpleResponse             # Event + EventType
from app.models.state import ProcessState
from app.graph.workflow import build_graph


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
graph = build_graph()



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



@app.post("/processes/{process_id}/events")
async def handle_event(
    process_id: str,
    event_json: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    # 1) ler estado atual do Blob
    state_dict = await blob_client.get_state(process_id)

    # 2) validar que tem process_id
    state_dict.setdefault("process_id", process_id)

    state_obj = ProcessState(**state_dict)

    # 3) parse do evento
    try:
        event = json.loads(event_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="event_json inválido")

    # 4) upload de ficheiro se existir
    if file is not None:
        blob_path = f"processes/{process_id}/docs/{file.filename}"
        await blob_client.upload_file(blob_path, file)
        event.setdefault("data", {})
        event["data"]["blob_path"] = blob_path
        event["data"]["filename"] = file.filename

    # 5) eventos globais (advance_phase) continuam aqui se quiseres
    if event.get("type") == "advance_phase":
        data = event.get("data", {})
        state_obj.fase_atual = data.get("nova_fase", state_obj.fase_atual)
        state_obj.sub_fase = data.get("sub_fase", state_obj.sub_fase)
        state_obj.historico.append(f"Fase alterada manualmente para {state_obj.fase_atual}")
        new_state = state_obj
    else:
        # 6) meter evento no state.flags para os nodes lerem
        state_obj.flags = state_obj.flags or {}
        state_obj.flags["last_event"] = event

        # 7) correr o grafo (um passo)
        graph_out = await graph.ainvoke(state_obj)

        # ✅ Normaliza: se vier dict, converte; se vier ProcessState, usa.
        if isinstance(graph_out, ProcessState):
            new_state = graph_out
        elif isinstance(graph_out, dict):
            new_state = ProcessState(**graph_out)
        else:
            raise HTTPException(status_code=500, detail=f"Graph devolveu tipo inesperado: {type(graph_out)}")


    # 8) guardar no Blob
    await blob_client.save_state(process_id, new_state.model_dump())

    return {
        "success": True,
        "fase_atual": new_state.fase_atual,
        "sub_fase": new_state.sub_fase,
        "state": new_state.model_dump(),
    }





if __name__ == "__main__":
    import uvicorn


    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
