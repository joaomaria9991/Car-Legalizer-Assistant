import copy
import asyncio
import io
import logging
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from app.graph.dav_autofill import apply_dav_autofill
from app.graph.dav_flow_utils import pick_questions
from app.graph.dav_decisions import apply_dav_decision_answer, build_dav_decisions
from app.graph.dav_metadata import (
    apply_dav_applicability,
    record_user_change,
    refresh_dav_field_metadata,
    review_field_keys,
)
from app.graph.graph_utils import extract_all_pages_parallel, process_single_page
from app.graph.progress import AGENT_PROGRESS_FLAG, MAX_PROGRESS_ENTRIES, add_progress
from app.graph.workflow import (
    _apply_dav_autofill_to_state,
    entry_router,
    extract_job_is_running,
    prepare_extract_job,
    run_extract_pipeline,
)
from app.main import (
    app,
    get_process_document_file,
    handle_event,
    list_process_documents,
    list_processes,
    summarize_process_state,
)
from app.auth import AuthenticatedUser
from app.models.state import ProcessState
from app.prompts.extraction_prompts import DEFAULT_DAV_TEMPLATE


def field(dados, code):
    for key, value in dados.items():
        if key.startswith(f"{code}:"):
            return value
    raise AssertionError(f"Missing code {code}")


class DavAutofillTests(unittest.TestCase):
    def make_dados(self, **values):
        dados = copy.deepcopy(DEFAULT_DAV_TEMPLATE)
        for code, value in values.items():
            for key in dados:
                if key.startswith(f"{code}:"):
                    dados[key] = value
                    break
            else:
                raise AssertionError(f"Missing code {code}")
        return dados

    def test_declarante_uses_comprador_before_loose_raw_identity(self):
        dados = self.make_dados(
            DC05="Ana Silva Demo",
            DC08="123456789",
            **{"06a": "ID1234567"},
        )
        raw = [{
            "category": "HOMOLOGACAO_TECNICA_IMT",
            "gpt_raw": '{"requerente":{"documento_identificacao":{"numero":"ID7654321"},"nif":"987654321"}}',
            "full_desc": "NIF do responsavel pelo centro: 987654320",
        }]

        apply_dav_autofill(dados, raw_insights=raw, today=date(2026, 5, 21))

        self.assertEqual(field(dados, "18"), "Ana Silva Demo")
        self.assertEqual(field(dados, "17a"), "123456789")
        self.assertEqual(field(dados, "17"), "NIF")
        self.assertEqual(field(dados, "14"), "Próprio")

    def test_plate_prefers_registration_certificate(self):
        dados = self.make_dados()
        raw = [
            {
                "category": "COMPROVATIVO_INSPECAO_TECNICA",
                "gpt_raw": '{"dados_do_veiculo":{"matricula":"1XE0455"}}',
                "full_desc": "",
            },
            {
                "category": "CERTIFICADO_MATRICULA",
                "gpt_raw": '{"informacoes_identificadoras":{"matricula_numero_inscricao":"AA00AA"}}',
                "full_desc": "",
            },
        ]

        apply_dav_autofill(dados, raw_insights=raw, today=date(2026, 5, 21))

        self.assertEqual(field(dados, "61"), "AA00AA")

    def test_transaction_and_entry_mirrors(self):
        dados = self.make_dados(
            DC05="Ana Silva",
            DC08="123456789",
            DC11="10/02/2024",
            DC13="15000.00",
            DC15="Transferencia bancaria",
            **{"57": "156000", "60": "06/12/2019", "66": "20/02/2024"},
        )

        apply_dav_autofill(dados, raw_insights=[], today=date(2026, 5, 21))

        self.assertEqual(field(dados, "75"), "10/02/2024")
        self.assertEqual(field(dados, "77"), "15000.00")
        self.assertEqual(field(dados, "84"), "Transferencia bancaria")
        self.assertEqual(field(dados, "DC25"), "20/02/2024")
        self.assertEqual(field(dados, "76"), "156000")
        self.assertEqual(field(dados, "55"), "Usado")
        self.assertEqual(field(dados, "02"), "Particular")
        self.assertEqual(field(dados, "DC07"), "Particular")

    def test_state_autofill_records_induced_field_metadata(self):
        dados = self.make_dados(DC05="Ana Silva", DC08="123456789")
        state = ProcessState(
            process_id="test",
            dados_carro=dados,
            flags={"raw_page_insights": []},
        )

        changes = _apply_dav_autofill_to_state(state)

        self.assertTrue(changes)
        meta = state.flags["dav_field_meta"]
        field_key = next(key for key in state.dados_carro if key.startswith("17a:"))
        self.assertEqual(meta[field_key]["origin"], "induced")
        self.assertEqual(meta[field_key]["status"], "filled")
        self.assertEqual(meta[field_key]["value"], "123456789")
        self.assertIn("comprador", meta[field_key]["reason"])
        progress = state.flags[AGENT_PROGRESS_FLAG]
        self.assertEqual(progress[-1]["stage"], "autofill")
        self.assertEqual(progress[-1]["status"], "done")
        self.assertEqual(progress[-1]["detail"]["count"], len(changes))

    def test_agent_progress_entries_are_appended_and_capped(self):
        state = ProcessState(process_id="test")

        entry = add_progress(
            state,
            "classify",
            "running",
            "Classifying documents",
            {"documents": 2},
        )

        self.assertEqual(entry["stage"], "classify")
        self.assertEqual(entry["status"], "running")
        self.assertEqual(entry["detail"]["documents"], 2)
        self.assertIn("ts", entry)
        self.assertEqual(state.flags[AGENT_PROGRESS_FLAG][-1], entry)

        for index in range(MAX_PROGRESS_ENTRIES + 5):
            add_progress(state, "extract", "done", f"page {index}")

        self.assertLessEqual(len(state.flags[AGENT_PROGRESS_FLAG]), MAX_PROGRESS_ENTRIES)
        self.assertEqual(state.flags[AGENT_PROGRESS_FLAG][-1]["message"], f"page {MAX_PROGRESS_ENTRIES + 4}")

    def test_process_state_defaults_are_not_shared(self):
        left = ProcessState(process_id="left")
        right = ProcessState(process_id="right")

        left.flags["x"] = 1
        left.docs["doc"] = {"category": "OUTROS"}
        left.historico.append("changed")

        self.assertEqual(right.flags, {})
        self.assertEqual(right.docs, {})
        self.assertEqual(right.historico, [])

    def test_refresh_metadata_marks_missing_fields(self):
        dados = self.make_dados(DC05="Ana Silva")
        state = ProcessState(process_id="test", dados_carro=dados)

        refresh_dav_field_metadata(state)

        plate_key = next(key for key in dados if key.startswith("61:"))
        buyer_key = next(key for key in dados if key.startswith("DC05:"))
        self.assertEqual(state.flags["dav_field_meta"][plate_key]["origin"], "missing")
        self.assertEqual(state.flags["dav_field_meta"][plate_key]["status"], "missing")
        self.assertEqual(state.flags["dav_field_meta"][buyer_key]["origin"], "extracted")
        self.assertEqual(state.flags["dav_field_meta"][buyer_key]["status"], "filled")

    def test_conflicting_plate_candidates_are_auto_resolved_with_audit(self):
        dados = self.make_dados(**{"61": "AA00AA"})
        state = ProcessState(process_id="test", dados_carro=dados)
        raw = [
            {
                "category": "COMPROVATIVO_INSPECAO_TECNICA",
                "gpt_raw": '{"dados_do_veiculo":{"matricula":"1XE0455"}}',
                "full_desc": "",
            },
            {
                "category": "CERTIFICADO_MATRICULA",
                "gpt_raw": '{"informacoes_identificadoras":{"matricula_numero_inscricao":"AA00AA"}}',
                "full_desc": "",
            },
        ]

        refresh_dav_field_metadata(state, raw)

        plate_key = next(key for key in dados if key.startswith("61:"))
        meta = state.flags["dav_field_meta"][plate_key]
        self.assertEqual(meta["origin"], "extracted")
        self.assertEqual(meta["status"], "filled")
        self.assertIn("Auto-resolved", meta["reason"])
        self.assertGreaterEqual(len(meta["alternatives"]), 2)

    def test_user_change_replaces_stale_induced_or_conflict_metadata(self):
        dados = self.make_dados(**{"61": "AA00AA"})
        field_key = next(key for key in dados if key.startswith("61:"))
        state = ProcessState(
            process_id="test",
            dados_carro=dados,
            flags={
                "dav_field_meta": {
                    field_key: {
                        "origin": "conflict",
                        "status": "conflict",
                        "value": "AA00AA",
                        "alternatives": [{"value": "1XE0455"}],
                    }
                }
            },
        )

        record_user_change(state, {"ok": True, "field_resolved": field_key, "new": "AA00AA"})

        meta = state.flags["dav_field_meta"][field_key]
        self.assertEqual(meta["origin"], "user")
        self.assertEqual(meta["status"], "filled")
        self.assertEqual(meta["alternatives"], [])

    def test_question_picker_skips_conflicts_and_prioritizes_review(self):
        conflict = "61:Numero da matricula definitiva"
        review = "DC05:Nome do comprador"
        missing = "01:Alfandega da criacao da DAV"
        fields = [missing, review, conflict]
        meta = {
            conflict: {"status": "conflict"},
            review: {"status": "needs_review"},
            missing: {"status": "missing"},
        }

        picked = pick_questions(fields, max_q=3, field_meta=meta)

        self.assertEqual(picked, [review, missing])

    def test_applicability_marks_intermediary_fields_not_applicable(self):
        dados = self.make_dados(DC16="Não")
        state = ProcessState(process_id="test", dados_carro=dados)

        refresh_dav_field_metadata(state)

        meta = state.flags["dav_field_meta"]
        for code in ("DC17", "DC18", "DC19", "DC20"):
            field_key = next(key for key in dados if key.startswith(f"{code}:"))
            self.assertEqual(meta[field_key]["origin"], "not_applicable")
            self.assertEqual(meta[field_key]["status"], "not_applicable")
            self.assertIn("DC16", meta[field_key]["reason"])
            self.assertNotIn(field_key, review_field_keys(state))

    def test_applicability_is_reversible_when_controller_changes(self):
        dados = self.make_dados(DC16="Não")
        state = ProcessState(process_id="test", dados_carro=dados)
        refresh_dav_field_metadata(state)

        dc16_key = next(key for key in dados if key.startswith("DC16:"))
        dc17_key = next(key for key in dados if key.startswith("DC17:"))
        state.dados_carro[dc16_key] = "Sim"
        apply_dav_applicability(state)
        refresh_dav_field_metadata(state)

        self.assertEqual(state.flags["dav_field_meta"][dc17_key]["status"], "missing")
        self.assertIn(dc17_key, review_field_keys(state))

    def test_question_picker_skips_not_applicable_fields(self):
        missing = "01:Alfandega da criacao da DAV"
        blocked = "DC17:Nome do intermediario"
        picked = pick_questions(
            [blocked, missing],
            max_q=3,
            field_meta={
                blocked: {"status": "not_applicable"},
                missing: {"status": "missing"},
            },
        )

        self.assertEqual(picked, [missing])

    def test_controller_decisions_do_not_include_conflicts(self):
        dados = self.make_dados(**{"61": "AA00AA"})
        state = ProcessState(process_id="test", dados_carro=dados)
        raw = [
            {"category": "DOC_A", "gpt_raw": '{"matricula":"1XE0455"}', "full_desc": ""},
            {"category": "DOC_B", "gpt_raw": '{"matricula":"AA00AA"}', "full_desc": ""},
        ]

        refresh_dav_field_metadata(state, raw)
        decisions = build_dav_decisions(state, max_decisions=3)

        self.assertTrue(decisions)
        self.assertEqual(decisions[0]["kind"], "applicability")
        self.assertEqual(decisions[0]["field"].split(":", 1)[0], "DC16")
        self.assertNotIn("conflict", {decision["kind"] for decision in decisions})

    def test_decision_answer_applies_controller_and_recalculates_applicability(self):
        dados = self.make_dados()
        state = ProcessState(process_id="test", dados_carro=dados)
        refresh_dav_field_metadata(state)
        dc16_key = next(key for key in dados if key.startswith("DC16:"))
        dc17_key = next(key for key in dados if key.startswith("DC17:"))

        applied = apply_dav_decision_answer(
            state,
            {"field": dc16_key, "value": "Não"},
        )
        refresh_dav_field_metadata(state)

        self.assertEqual(applied[0]["field_resolved"], dc16_key)
        self.assertEqual(state.flags["dav_field_meta"][dc17_key]["status"], "not_applicable")
        self.assertNotIn(dc17_key, review_field_keys(state))

    def test_conflict_candidates_do_not_create_decision_cards(self):
        dados = self.make_dados(**{"61": "AA00AA"})
        state = ProcessState(process_id="test", dados_carro=dados)
        raw = [
            {"category": "DOC_A", "gpt_raw": '{"matricula":"1XE0455"}', "full_desc": ""},
            {"category": "DOC_B", "gpt_raw": '{"matricula":"AA00AA"}', "full_desc": ""},
        ]
        refresh_dav_field_metadata(state, raw)
        plate_key = next(key for key in dados if key.startswith("61:"))
        decisions = build_dav_decisions(state, max_decisions=10)

        self.assertNotIn("conflict", {decision["kind"] for decision in decisions})
        self.assertEqual(state.flags["dav_field_meta"][plate_key]["origin"], "extracted")
        self.assertEqual(state.flags["dav_field_meta"][plate_key]["status"], "filled")

    def test_start_extract_routes_even_when_process_is_still_intake(self):
        state = ProcessState(
            process_id="test",
            fase_atual="INTAKE_DOCS",
            flags={"last_event": {"type": "start_extract"}},
        )

        route = entry_router(state)

        self.assertEqual(route, "EXTRACT_VALIDATE")
        self.assertEqual(state.fase_atual, "EXTRACT_VALIDATE")

    def test_process_summary_tolerates_minimal_old_state(self):
        summary = summarize_process_state(
            {
                "process_id": "old",
                "dados_carro": {
                    "61:Numero da matricula definitiva": "AA-00-AA",
                    "DC05:Nome do comprador": None,
                },
            },
            "2026-05-22T10:00:00+00:00",
        )

        self.assertEqual(summary["process_id"], "old")
        self.assertEqual(summary["fase_atual"], "INTAKE_DOCS")
        self.assertEqual(summary["docs_count"], 0)
        self.assertEqual(summary["filled_fields"], 1)
        self.assertEqual(summary["missing_fields"], 1)
        self.assertEqual(summary["conflict_fields"], 0)

    def test_list_processes_only_uses_state_json_blobs(self):
        class FakeBlobClient:
            async def list_blobs(self, prefix=None, include_metadata=False):
                return [
                    {"name": "processes/alpha/state.json", "last_modified": "2026-05-22T10:00:00+00:00"},
                    {"name": "processes/alpha/docs/page.jpg", "last_modified": "2026-05-22T10:01:00+00:00"},
                    {"name": "processes/beta/state.json", "last_modified": "2026-05-22T11:00:00+00:00"},
                    {"name": "scratch/state.json", "last_modified": "2026-05-22T12:00:00+00:00"},
                ]

            async def get_state(self, process_id):
                return {
                    "process_id": process_id,
                    "fase_atual": "DAV_FLOW" if process_id == "beta" else "INTAKE_DOCS",
                    "dados_carro": {"DC05:Nome do comprador": "Ana" if process_id == "beta" else None},
                    "docs": {"invoice.pdf": {}} if process_id == "beta" else {},
                    "flags": {},
                }

        async def call_endpoint():
            with patch("app.main.blob_client", FakeBlobClient()):
                return await list_processes()

        response = asyncio.run(call_endpoint())

        self.assertEqual([item["process_id"] for item in response["processes"]], ["beta", "alpha"])
        self.assertEqual(response["processes"][0]["docs_count"], 1)
        self.assertEqual(response["processes"][0]["filled_fields"], 1)

    def test_prepare_extract_job_marks_running_and_blocks_duplicate(self):
        state = ProcessState(
            process_id="test",
            fase_atual="INTAKE_DOCS",
            docs={
                "invoice.pdf": {
                    "category": "FATURA_COMPRA",
                    "pages": ["processes/test/docs/invoice_page_1.jpg", "processes/test/docs/invoice_page_2.jpg"],
                },
                "invoice.pdf_page_1": {
                    "category": "FATURA_COMPRA",
                    "pages": ["processes/test/docs/invoice_page_1.jpg"],
                },
            },
        )

        first = prepare_extract_job(state)
        second = prepare_extract_job(state)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertTrue(extract_job_is_running(state))
        job = state.flags["extract_job"]
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["pages_total"], 2)
        self.assertEqual(job["pages_done"], 0)
        self.assertEqual(state.fase_atual, "EXTRACT_VALIDATE")
        self.assertEqual(state.sub_fase, "EXTRACT_RUNNING")
        self.assertEqual(state.flags[AGENT_PROGRESS_FLAG][-1]["status"], "warning")

    def test_start_extract_endpoint_returns_running_job_without_running_pipeline(self):
        class FakeBlobClient:
            def __init__(self):
                self.saved = []

            async def get_state(self, process_id):
                return {
                    "process_id": process_id,
                    "fase_atual": "INTAKE_DOCS",
                    "docs": {
                        "invoice.pdf": {
                            "category": "FATURA_COMPRA",
                            "pages": ["processes/test/docs/invoice_page_1.jpg"],
                        }
                    },
                    "flags": {},
                }

            async def save_state(self, process_id, state):
                self.saved.append(copy.deepcopy(state))

        async def call_endpoint():
            fake_blob = FakeBlobClient()
            background_tasks = BackgroundTasks()
            with patch("app.main.blob_client", fake_blob), patch("app.main.running_extract_jobs", set()):
                response = await handle_event(
                    "test",
                    background_tasks,
                    event_json='{"type":"start_extract"}',
                    file=None,
                )
            return response, background_tasks, fake_blob

        response, background_tasks, fake_blob = asyncio.run(call_endpoint())

        job = response["state"]["flags"]["extract_job"]
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["pages_total"], 1)
        self.assertEqual(job["pages_done"], 0)
        self.assertEqual(response["fase_atual"], "EXTRACT_VALIDATE")
        self.assertEqual(response["sub_fase"], "EXTRACT_RUNNING")
        self.assertEqual(len(background_tasks.tasks), 1)
        self.assertEqual(fake_blob.saved[-1]["flags"]["extract_job"]["status"], "running")

    def test_duplicate_start_extract_endpoint_does_not_queue_second_job(self):
        class FakeBlobClient:
            async def get_state(self, process_id):
                return {
                    "process_id": process_id,
                    "fase_atual": "EXTRACT_VALIDATE",
                    "flags": {
                        "extract_job": {
                            "status": "running",
                            "started_at": "2026-05-22T00:00:00+00:00",
                            "finished_at": None,
                            "error": None,
                            "pages_total": 3,
                            "pages_done": 1,
                        }
                    },
                }

            async def save_state(self, process_id, state):
                self.saved_state = copy.deepcopy(state)

        async def call_endpoint():
            fake_blob = FakeBlobClient()
            background_tasks = BackgroundTasks()
            with patch("app.main.blob_client", fake_blob), patch("app.main.running_extract_jobs", {"test"}):
                response = await handle_event(
                    "test",
                    background_tasks,
                    event_json='{"type":"start_extract"}',
                    file=None,
                )
            return response, background_tasks, fake_blob

        response, background_tasks, fake_blob = asyncio.run(call_endpoint())

        self.assertEqual(len(background_tasks.tasks), 0)
        self.assertEqual(response["state"]["flags"]["extract_job"]["status"], "running")
        self.assertEqual(fake_blob.saved_state["flags"][AGENT_PROGRESS_FLAG][-1]["status"], "warning")

    def test_stale_running_extract_endpoint_requeues_after_restart(self):
        class FakeBlobClient:
            async def get_state(self, process_id):
                return {
                    "process_id": process_id,
                    "fase_atual": "EXTRACT_VALIDATE",
                    "docs": {
                        "invoice.pdf": {
                            "category": "FATURA_COMPRA",
                            "pages": ["processes/test/docs/invoice_page_1.jpg"],
                        }
                    },
                    "flags": {
                        "extract_job": {
                            "status": "running",
                            "started_at": "2026-05-22T00:00:00+00:00",
                            "finished_at": None,
                            "error": None,
                            "pages_total": 1,
                            "pages_done": 0,
                        }
                    },
                }

            async def save_state(self, process_id, state):
                self.saved_state = copy.deepcopy(state)

        async def call_endpoint():
            fake_blob = FakeBlobClient()
            background_tasks = BackgroundTasks()
            with patch("app.main.blob_client", fake_blob), patch("app.main.running_extract_jobs", set()):
                response = await handle_event(
                    "test",
                    background_tasks,
                    event_json='{"type":"start_extract"}',
                    file=None,
                )
            return response, background_tasks, fake_blob

        response, background_tasks, fake_blob = asyncio.run(call_endpoint())

        self.assertEqual(len(background_tasks.tasks), 1)
        self.assertEqual(response["state"]["flags"]["extract_job"]["status"], "running")
        self.assertEqual(fake_blob.saved_state["flags"]["extract_job"]["pages_total"], 1)

    def test_partial_extract_resume_processes_only_missing_pages(self):
        state = ProcessState(
            process_id="test",
            docs={
                "invoice.pdf": {
                    "category": "FATURA_COMPRA",
                    "pages": [
                        "processes/test/docs/page_1.jpg",
                        "processes/test/docs/page_2.jpg",
                    ],
                }
            },
            flags={
                "raw_page_insights": [
                    {
                        "doc_id": "invoice.pdf",
                        "category": "FATURA_COMPRA",
                        "page_blob": "processes/test/docs/page_1.jpg",
                        "gpt_raw": "{}",
                        "full_desc": "cached",
                    }
                ]
            },
        )
        captured_specs = []

        class FakeBlobClient:
            async def save_state(self, process_id, state_dict):
                self.last_state = copy.deepcopy(state_dict)

        async def fake_extract(state_arg, on_page_result=None, page_specs=None):
            captured_specs.extend(page_specs or [])
            insight = {
                "doc_id": "invoice.pdf",
                "category": "FATURA_COMPRA",
                "page_blob": "processes/test/docs/page_2.jpg",
                "gpt_raw": "{}",
                "full_desc": "new",
            }
            if on_page_result:
                await on_page_result(insight)
            return [insight]

        async def fake_harmonize(raw_insights):
            return self.make_dados(DC05="Ana Silva")

        with patch("app.graph.workflow.extract_all_pages_parallel", side_effect=fake_extract), patch(
            "app.graph.workflow.harmonize_all_data",
            side_effect=fake_harmonize,
        ):
            asyncio.run(run_extract_pipeline(state, FakeBlobClient()))

        self.assertEqual(captured_specs, [("processes/test/docs/page_2.jpg", "invoice.pdf", "FATURA_COMPRA")])
        self.assertEqual(state.flags["extract_job"]["status"], "done")
        self.assertEqual(state.flags["extract_job"]["pages_done"], 2)
        self.assertEqual(len(state.flags["raw_page_insights"]), 2)

    def test_document_endpoint_groups_state_docs(self):
        class FakeBlobClient:
            async def get_state(self, process_id):
                return {
                    "process_id": process_id,
                    "docs": {
                        "invoice.pdf": {
                            "category": "FATURA_COMPRA",
                            "status": "classified",
                            "confidence": 0.9,
                            "pages": ["processes/test/docs/page_1.jpg"],
                        },
                        "invoice.pdf_page_1": {
                            "pages": ["processes/test/docs/page_1.jpg"],
                        },
                    },
                    "flags": {},
                }

            async def save_state(self, process_id, state):
                self.saved_state = state

        async def call_endpoint():
            with patch("app.main.blob_client", FakeBlobClient()), patch("app.main.running_extract_jobs", set()):
                return await list_process_documents("test")

        response = asyncio.run(call_endpoint())

        self.assertEqual(response["process_id"], "test")
        self.assertEqual(len(response["documents"]), 1)
        self.assertEqual(response["documents"][0]["pages"][0]["blob_path"], "processes/test/docs/page_1.jpg")

    def test_document_download_rejects_outside_process_path(self):
        async def call_endpoint():
            return await get_process_document_file("test", "processes/other/docs/page_1.jpg")

        with self.assertRaises(HTTPException) as caught:
            asyncio.run(call_endpoint())

        self.assertEqual(caught.exception.status_code, 400)

    def test_auth_required_rejects_missing_token(self):
        async def reject(_request):
            raise HTTPException(status_code=401, detail="Missing bearer token")

        with patch("app.main.authenticate_request", side_effect=reject):
            response = TestClient(app).get("/processes")

        self.assertEqual(response.status_code, 401)

    def test_authenticated_process_list_is_scoped_to_user(self):
        class FakeBlobClient:
            async def list_blobs(self, prefix=None, include_metadata=False):
                self.prefix = prefix
                return [
                    {"name": "processes/u_test/alpha/state.json", "last_modified": "2026-05-22T10:00:00+00:00"},
                    {"name": "processes/u_other/beta/state.json", "last_modified": "2026-05-22T11:00:00+00:00"},
                ]

            async def get_state(self, process_id):
                return {
                    "process_id": process_id,
                    "fase_atual": "INTAKE_DOCS",
                    "dados_carro": {},
                    "docs": {},
                    "flags": {},
                }

        async def authenticate(_request):
            return AuthenticatedUser(user_key="u_test", subject="sub")

        fake_blob = FakeBlobClient()
        with patch("app.main.authenticate_request", side_effect=authenticate), patch("app.main.blob_client", fake_blob):
            response = TestClient(app).get("/processes", headers={"Authorization": "Bearer test"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_blob.prefix, "processes/u_test/")
        self.assertEqual([item["process_id"] for item in response.json()["processes"]], ["alpha"])

    def test_extract_logging_is_cp1252_safe_with_no_docs(self):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger("app.graph.graph_utils")
        old_level = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            state = ProcessState(process_id="test")
            result = asyncio.run(extract_all_pages_parallel(state))
            handler.flush()
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)
            stream.detach()

        self.assertEqual(result, [])

    def test_process_single_page_uses_one_vision_call(self):
        calls = {"count": 0}

        class FakeBlobClient:
            async def get_blob_as_base64(self, blob_name):
                return "ZmFrZS1pbWFnZQ=="

        async def fake_llm_create(**kwargs):
            calls["count"] += 1
            self.assertEqual(kwargs.get("response_format"), {"type": "json_object"})
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"full_desc":"VIN and buyer visible","extracted":{"vin":"WAUZZZ8V1KA654321"}}'
                        )
                    )
                ]
            )

        with patch("app.graph.graph_utils._get_blob_client", return_value=FakeBlobClient()), patch(
            "app.graph.graph_utils._llm_create",
            side_effect=fake_llm_create,
        ):
            result = asyncio.run(process_single_page("processes/test/docs/page_1.jpg", "invoice.pdf", "FATURA_COMPRA"))

        self.assertEqual(calls["count"], 1)
        self.assertIsNotNone(result)
        self.assertEqual(result["full_desc"], "VIN and buyer visible")
        self.assertIn("WAUZZZ8V1KA654321", result["gpt_raw"])


if __name__ == "__main__":
    unittest.main()
