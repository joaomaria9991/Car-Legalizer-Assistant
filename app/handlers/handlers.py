from fastapi import HTTPException
import json

from app.llms import llm
# from app.prompts.dav_prompts import EXTRACT_DADOS_CARRO





def handle_intake_docs(state: dict, event: dict) -> dict:
    """
    Fase INTAKE_DOCS:
    - Regista documentos
    - Quando tiver pelo menos fatura + DUA, avança para EXTRACT_VALIDATE
    """
    docs = state.setdefault("docs", {})
    historico = state.setdefault("historico", [])

    if event.get("type") == "upload_doc":
        data = event.get("data", {})
        doc_type = data.get("doc_type")
        blob_path = data.get("blob_path")
        filename = data.get("filename")

        if not doc_type:
            raise HTTPException(status_code=400, detail="doc_type em falta no evento")

        docs[doc_type] = {
            "blob_path": blob_path,
            "filename": filename,
            "parsed": False,
        }
        historico.append(f"Documento '{doc_type}' carregado.")

    # Regra: se já tem fatura + DUA, avança de fase
    if "fatura" in docs and "dua" in docs:
        state["fase_atual"] = "EXTRACT_VALIDATE"
        state["sub_fase"] = "EXTRAINDO"
        historico.append("Transição para EXTRACT_VALIDATE.")

    return state




def handle_dav_collect_fiscal(state: dict, event: dict) -> dict:
    """
    Novo handler para recolher dados fiscais da DAV.
    """
    historico = state.setdefault("historico", [])
    
    # Só reage a answer_fiscal_questions por agora
    if event.get("type") == "answer_fiscal_questions":
        data = event.get("data", {})
        
        # Inicializa dados_fiscal se ainda não existir
        state.setdefault("dados_fiscal", {
            "declarante": {"nif": None, "nome": None, "morada_fiscal": None},
            "entrada_pt": {"data": None, "modo": None},
            "regime_isv": None,
            "dav_draft": None,
            "isv_estimado": None
        })
        
        # Preenche os campos que vieram
        fiscal = state["dados_fiscal"]
        if "nif" in data:
            fiscal["declarante"]["nif"] = data["nif"]
        if "data_entrada_pt" in data:
            fiscal["entrada_pt"]["data"] = data["data_entrada_pt"]
        if "modo_entrada" in data:
            fiscal["entrada_pt"]["modo"] = data["modo_entrada"]
        
        historico.append(f"Dados fiscais atualizados: {list(data.keys())}")
        
        # TODO: quando tiver dados mínimos, muda fase
        # if todos_campos_obrigatorios_preenchidos():
        #     state["fase_atual"] = "DAV_DRAFT_READY"
    
    elif event.get("type") == "generate_dav_draft":
        # ← ADICIONA ISTO
        carro = state.get("dados_carro", {})
        fiscal = state.get("dados_fiscal", {})
        
        dav_draft = {
            "declarante": {
                "nif": fiscal.get("declarante", {}).get("nif", ""),
                "nome": "João Silva",
                "morada_fiscal": ""
            },
            "veiculo": {
                "marca": carro.get("marca", ""),
                "modelo": carro.get("modelo", ""),
                "ano": carro.get("ano"),
                "co2": 120
            },
            "circunstancias": {
                "data_entrada_pt": fiscal.get("entrada_pt", {}).get("data", ""),
                "modo_entrada": fiscal.get("entrada_pt", {}).get("modo", ""),
                "valor_compra": 22500
            }
        }
        
        state["dados_fiscal"]["dav_draft"] = dav_draft
        state["dados_fiscal"]["isv_estimado"] = "€2.100"
        state["sub_fase"] = "DAV_DRAFT_READY"
        historico.append("DAV draft gerado!")

    return state



def handle_extract_validate(state: dict, event: dict) -> dict:
    """
    Fase EXTRACT_VALIDATE:
    - Evento 'start_extract' → marca docs como parseados e preenche dados_carro dummy
    - Futuramente aqui entra OCR + LLM.
    """
    historico = state.setdefault("historico", [])
    docs = state.setdefault("docs", {})
    dados_carro = state.setdefault("dados_carro", {})

    event_type = event.get("type")

    if event_type == "start_extract":
        # 1) Marcar docs como parseados
        for doc_type, info in docs.items():
            info["parsed"] = True
        historico.append("Documentos marcados como parseados em EXTRACT_VALIDATE.")

        # 2) Preencher alguns campos dummy (para testar o fluxo)
        dados_carro.setdefault("marca", "DESCONHECIDA")
        dados_carro.setdefault("modelo", "DESCONHECIDO")
        dados_carro.setdefault("ano", None)

        # 3) Avançar sub_fase
        state["sub_fase"] = "A_CONFIRMAR"
        historico.append("Transição de EXTRAINDO para A_CONFIRMAR.")

    else:
        historico.append(f"Evento ignorado em EXTRACT_VALIDATE: {event_type}")

    return state



def handle_dav_draft_generation(state: dict, event: dict) -> dict:
    if event.get("type") == "generate_dav_draft":
        # 1) Extrai dados do carro e fiscal
        carro = state.get("dados_carro", {})
        fiscal = state.get("dados_fiscal", {})
        
        # 2) Cria estrutura DAV (campos reais do portal)
        dav_draft = {
            "declarante": {
                "nif": fiscal.get("declarante", {}).get("nif"),
                "nome": "João Silva",  # por agora hardcoded
                "morada": "Rua Exemplo 123, Lisboa"
            },
            "veiculo": {
                "vin": "WVWZZZ1KZ0W123456",  # depois vem do OCR
                "marca": carro.get("marca"),
                "modelo": carro.get("modelo"),
                "co2": 120  # depois do OCR real
            },
            "circunstancias": {
                "data_entrada_pt": fiscal.get("entrada_pt", {}).get("data"),
                "modo_entrada": fiscal.get("entrada_pt", {}).get("modo"),
                "valor_compra": 22500  # do OCR da fatura
            }
        }
        
        state["dados_fiscal"]["dav_draft"] = dav_draft
        state["sub_fase"] = "DAV_DRAFT_READY"
        state.setdefault("historico", []).append("DAV draft gerado com sucesso!")
        
    return state


