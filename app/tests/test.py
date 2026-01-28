import json
import requests
from typing import Any, Dict


def print_separator(title: str):
    print("\n" + "=" * 20, title, "=" * 20)


def pretty_json(data: Any):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def print_response(r: requests.Response):
    print(f"HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        print("Resposta não é JSON:")
        print(r.text)
        return

    # Caso típico: erro de validação FastAPI
    if isinstance(data, dict) and "detail" in data:
        detail = data["detail"]
        print("Erro / detail:")
        pretty_json(detail)
        return

    # Caso de sucesso genérico
    pretty_json(data)


BASE_URL = "http://127.0.0.1:8000"
PROCESS_ID = "proc_test_1"

def test_answer_fiscal_questions():
    print_separator("EVENT: answer_fiscal_questions (NIF)")
    
    event = {
        "type": "answer_fiscal_questions",
        "data": {
            "nif": "123456789",
            "data_entrada_pt": "2026-01-15",
            "modo_entrada": "conduzir"
        }
    }
    
    files = {
        "event_json": (None, json.dumps(event), "application/json"),
    }
    
    r = requests.post(f"{BASE_URL}/processes/{PROCESS_ID}/events", files=files)
    print_response(r)

def test_get_process_full_state():
    print_separator("ESTADO FINAL")
    r = requests.get(f"{BASE_URL}/processes/{PROCESS_ID}")
    print_response(r)

def test_health():
    print_separator("HEALTH")
    r = requests.get(f"{BASE_URL}/health")
    print_response(r)


def test_get_process():
    print_separator("GET PROCESS")
    r = requests.get(f"{BASE_URL}/processes/{PROCESS_ID}")
    print_response(r)


def test_event_upload_doc(doc_type: str):
    print_separator(f"EVENT: upload_doc ({doc_type})")

    event = {
        "type": "upload_doc",
        "data": {
            "doc_type": doc_type,
            # se o teu backend ainda não exige blob_path de verdade:
            "blob_path": f"processes/{PROCESS_ID}/docs/{doc_type}.pdf",
            "filename": f"{doc_type}.pdf",
        },
    }

    # Se o teu endpoint ainda está a receber event_json via Form:
    files = {
        "event_json": (None, json.dumps(event), "application/json"),
    }

    r = requests.post(
        f"{BASE_URL}/processes/{PROCESS_ID}/events",
        files=files,
    )
    print_response(r)


def test_start_extract():
    print_separator("EVENT: start_extract")
    event = {"type": "start_extract", "data": {}}
    files = {
        "event_json": (None, json.dumps(event), "application/json"),
    }
    r = requests.post(f"{BASE_URL}/processes/{PROCESS_ID}/events", files=files)
    print_response(r)
def test_advance_to_dav_flow():
    print_separator("AVANÇAR PARA DAV_FLOW")
    event = {
        "type": "advance_phase", 
        "data": {
            "nova_fase": "DAV_FLOW",
            "sub_fase": "COLETAR_DADOS_FISCAIS"
        }
    }
    files = {
        "event_json": (None, json.dumps(event), "application/json"),
    }
    r = requests.post(f"{BASE_URL}/processes/{PROCESS_ID}/events", files=files)
    print_response(r)

def test_generate_dav_draft():
    print_separator("GERAR DAV DRAFT")
    event = {"type": "generate_dav_draft", "data": {}}
    files = {
        "event_json": (None, json.dumps(event), "application/json"),
    }
    r = requests.post(f"{BASE_URL}/processes/{PROCESS_ID}/events", files=files)
    print_response(r)



if __name__ == "__main__":
    # test_health()
    # test_get_process()

    # # 1º evento: fatura
    # test_event_upload_doc("fatura")
    # test_get_process()

    # # 2º evento: dua
    # test_event_upload_doc("dua")
    # test_get_process()
    # test_start_extract()

    # # No __main__, depois do start_extract:
    # test_advance_to_dav_flow()
    # test_answer_fiscal_questions()
    # test_get_process_full_state()
    test_generate_dav_draft()