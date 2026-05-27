from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from datetime import date
from typing import Any, Iterable


Change = dict[str, Any]
CandidateMap = dict[str, list[dict[str, Any]]]


CATEGORY_WEIGHT = {
    "CERTIFICADO_MATRICULA": 6,
    "CARTAO_CIDADAO": 6,
    "CARTAO_CONTRIBUINTE": 6,
    "PASSAPORTE": 5,
    "FATURA_COMPRA": 6,
    "FATURA_PROFORMA": 6,
    "COMPROVATIVO_INSPECAO_TECNICA": 5,
    "HOMOLOGACAO_TECNICA_IMT": 4,
    "DOCUMENTO_TRANSPORTE_CMR": 4,
    "OUTROS": 2,
}

COMPANY_TOKENS = (
    " lda", " l.d.a", " sa", " s.a", " unipessoal", " sociedade", " empresa",
    " gmbh", " bv", " b.v", " sl", " s.l", " srl", " ltd", " limited",
    " inc", " corp", " motors", " cars", " auto", "automoveis",
)

COUNTRY_MARKERS = {
    "alemanha": "Alemanha",
    "germany": "Alemanha",
    "deutschland": "Alemanha",
    "belgica": "Bélgica",
    "belgium": "Bélgica",
    "belgie": "Bélgica",
    "franca": "França",
    "france": "França",
    "espanha": "Espanha",
    "spain": "Espanha",
    "italia": "Itália",
    "italy": "Itália",
    "holanda": "Países Baixos",
    "netherlands": "Países Baixos",
    "paises baixos": "Países Baixos",
    "portugal": "Portugal",
}

MONTHS_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def apply_dav_autofill(
    dados_carro: dict[str, Any],
    raw_insights: list[dict[str, Any]] | None = None,
    today: date | None = None,
) -> list[Change]:
    """
    Fill empty DAV fields from high-confidence equivalents and raw extraction crumbs.

    The function mutates dados_carro in place and never overwrites non-empty values.
    """
    if not dados_carro:
        return []

    index = _code_index(dados_carro)
    changes: list[Change] = []
    candidates = _extract_candidates(raw_insights or [])
    today = today or date.today()

    def get(code: str) -> Any:
        key = index.get(code)
        return dados_carro.get(key) if key else None

    def fill(code: str, value: Any, reason: str, source: str | None = None) -> None:
        key = index.get(code)
        if not key or not _is_missing(dados_carro.get(key)):
            return
        cleaned = _clean_for_code(code, value)
        if _is_missing(cleaned):
            return
        dados_carro[key] = cleaned
        changes.append({
            "field": key,
            "value": cleaned,
            "reason": reason,
            "source": source,
        })

    def copy(target: str, source: str, reason: str, *, tax_id_only: bool = False) -> None:
        value = get(source)
        if tax_id_only and not _looks_like_tax_id(value):
            return
        fill(target, value, reason, source)

    # Values the LLM often sees in raw insights but may lose during harmonization.
    fill("61", _best_candidate(candidates, "plate"), "matricula found in source documents", "raw_insights")
    fill("42", _best_candidate(candidates, "vin"), "VIN found in source documents", "raw_insights")
    fill("57", _best_candidate(candidates, "kilometers"), "kilometers found in source documents", "raw_insights")
    fill("76", _best_candidate(candidates, "kilometers"), "kilometers found in source documents", "raw_insights")
    fill("60", _best_candidate(candidates, "first_registration_date"), "first registration date found in source documents", "raw_insights")
    fill("66", _best_candidate(candidates, "entry_date"), "entry date found in source documents", "raw_insights")
    fill("DC25", _best_candidate(candidates, "entry_date"), "entry date found in source documents", "raw_insights")
    fill("DC10", _best_candidate(candidates, "invoice_number"), "invoice number found in source documents", "raw_insights")
    fill("DC11", _best_candidate(candidates, "invoice_date"), "invoice date found in source documents", "raw_insights")
    fill("75", _best_candidate(candidates, "invoice_date"), "invoice date found in source documents", "raw_insights")
    fill("DC13", _best_candidate(candidates, "price"), "price found in source documents", "raw_insights")
    fill("77", _best_candidate(candidates, "price"), "acquisition value found in source documents", "raw_insights")
    fill("DC15", _best_candidate(candidates, "payment_method"), "payment method found in source documents", "raw_insights")
    fill("84", _best_candidate(candidates, "payment_method"), "payment method found in source documents", "raw_insights")
    fill("85", _best_candidate(candidates, "warranty"), "warranty terms found in source documents", "raw_insights")
    fill("86", _best_candidate(candidates, "legal_basis"), "legal basis found in source documents", "raw_insights")

    # Existing final DAV fields are already harmonized and should beat loose raw OCR.
    copy("18", "DC05", "declarante is the comprador")
    copy("DC05", "18", "comprador is the declarante")
    copy("17a", "DC08", "declarante id mirrors comprador tax id", tax_id_only=True)
    copy("DC08", "17a", "comprador tax id mirrors declarante id", tax_id_only=True)
    copy("06a", "DC08", "adquirente/proprietario id mirrors comprador tax id", tax_id_only=True)
    copy("06a", "17a", "adquirente/proprietario id mirrors declarante id", tax_id_only=True)
    copy("DC08", "06a", "comprador tax id mirrors adquirente/proprietario id", tax_id_only=True)

    # Party data: comprador, adquirente/proprietario and declarante are often the same person.
    fill("DC05", _best_candidate(candidates, "buyer_name"), "buyer name found in source documents", "raw_insights")
    fill("18", _best_candidate(candidates, "buyer_name"), "buyer/declarant name found in source documents", "raw_insights")
    fill("DC06", _best_candidate(candidates, "buyer_address"), "buyer address found in source documents", "raw_insights")
    fill("DC08", _best_candidate(candidates, "buyer_tax_id"), "buyer tax id found in source documents", "raw_insights")
    fill("17a", _best_candidate(candidates, "buyer_tax_id"), "buyer/declarant tax id found in source documents", "raw_insights")
    fill("06a", _best_candidate(candidates, "buyer_tax_id"), "buyer/acquirer tax id found in source documents", "raw_insights")

    fill("DC01", _best_candidate(candidates, "seller_name"), "seller name found in source documents", "raw_insights")
    fill("DC02", _best_candidate(candidates, "seller_address"), "seller address found in source documents", "raw_insights")
    fill("DC04", _best_candidate(candidates, "seller_tax_id"), "seller tax id found in source documents", "raw_insights")

    # Transaction/date/value mirrors.
    copy("75", "DC11", "invoice date is the transaction date")
    copy("DC11", "75", "transaction date is the invoice date")
    copy("77", "DC13", "acquisition value mirrors invoice vehicle price")
    copy("DC13", "77", "invoice vehicle price mirrors acquisition value")
    copy("58", "77", "commercial value defaults to known acquisition value")
    copy("58", "DC13", "commercial value defaults to known invoice price")
    copy("84", "DC15", "payment mode mirrors acquisition payment method")
    copy("DC15", "84", "acquisition payment method mirrors payment mode")
    copy("DC25", "66", "entry date mirrors DAV entry date")
    copy("66", "DC25", "DAV entry date mirrors entry date in complementary data")
    copy("76", "57", "transmission kilometers mirror DAV kilometers when only one odometer value is known")
    copy("57", "76", "DAV kilometers mirror transmission kilometers when only one odometer value is known")
    if not _is_missing(get("61")):
        copy("62", "60", "definitive registration date mirrors first registration date when only one date is known")

    if _has_any(get("DC13"), get("77"), get("58")):
        fill("DC14", "EUR", "currency defaults to EUR when euro values are extracted")

    buyer_status = _party_status(get("DC05") or get("18"), get("DC08") or get("17a") or get("06a"))
    fill("02", buyer_status, "taxable person status inferred from buyer/declarant")
    fill("DC07", buyer_status, "buyer quality inferred from buyer/declarant")

    seller_quality = _seller_quality(get("DC01"), get("DC04"))
    fill("DC03", seller_quality, "seller quality inferred from seller identity")
    fill("DC02a", _country_from_text(get("DC02")), "seller country inferred from seller address")
    fill("DC04a", _country_from_tax_id(get("DC04")) or _country_from_text(get("DC02")), "seller tax country inferred from VAT id/address")

    id_type_06 = _id_type(get("06a"))
    id_type_17 = _id_type(get("17a"))
    fill("06", id_type_06, "identification type inferred from acquired/proprietor id")
    fill("17", id_type_17, "identification type inferred from declarant id")

    if _same_person(get("18"), get("DC05")):
        fill("14", "Próprio", "declarant and buyer appear to be the same person")

    first_registration = _parse_date(get("60"))
    if first_registration and first_registration < today:
        fill("55", "Usado", "first registration date is in the past")
    elif _to_int(get("57")) or _to_int(get("76")):
        fill("55", "Usado", "vehicle has recorded kilometers")

    fill("33", _vehicle_fiscal_type(get("31"), get("32")), "vehicle fiscal type inferred from category/type")
    if _has_any(get("61"), get("60")):
        fill("69", "Definitiva", "import declaration type inferred from definitive registration data")
    if _raw_mentions(raw_insights, "IMT"):
        fill("89", "IMT - Instituto da Mobilidade e dos Transportes, I.P.", "IMT document found in source documents")

    entry_type = _entry_type(raw_insights, get("DC21"), get("DC22"))
    fill("66a", entry_type, "entry type inferred from transport evidence")
    fill("DC21", entry_type, "transport method inferred from entry evidence")

    legal_basis = _norm(get("86") or get("DC12") or "")
    if "138" in legal_basis or "intracomunitaria" in legal_basis:
        fill("DC12", "Transmissão intracomunitária", "VAT regime inferred from invoice legal basis")
        fill("80", "Operação intracomunitária", "non-taxable operation inferred from invoice legal basis")

    return changes


def extract_dav_candidates(raw_insights: list[dict[str, Any]] | None) -> CandidateMap:
    return _extract_candidates(raw_insights or [])


def candidate_key(kind: str, value: Any) -> str | None:
    return _candidate_key(kind, value)


def candidate_display_value(kind: str, value: Any) -> str:
    return _display_value(kind, value)


def _code_index(dados_carro: dict[str, Any]) -> dict[str, str]:
    index: dict[str, str] = {}
    for key in dados_carro:
        code = key.split(":", 1)[0].strip()
        index[code] = key
    return index


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _has_any(*values: Any) -> bool:
    return any(not _is_missing(v) for v in values)


def _clean_for_code(code: str, value: Any) -> Any:
    if _is_missing(value):
        return None
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(str(v) for v in value if not _is_missing(v))
    value = str(value).strip()
    if not value:
        return None

    if code in {"42"}:
        return _normalize_vin(value)
    if code in {"61", "63", "90"}:
        return _normalize_plate(value)
    if code in {"37", "38", "44", "45", "46", "47", "48", "50", "51", "52", "57", "76"}:
        return _digits_only(value)
    if code in {"58", "77", "DC13"}:
        return _normalize_money(value)
    if code in {"60", "62", "64", "65", "66", "67", "75", "DC11", "DC25", "91"}:
        parsed = _parse_date(value)
        return parsed.strftime("%d/%m/%Y") if parsed else value
    if code in {"06a", "15a", "17a", "DC04", "DC04a", "DC08", "DC20", "DC24"}:
        return _normalize_identifier(value)
    return _squash_ws(value)


def _extract_candidates(raw_insights: Iterable[dict[str, Any]]) -> CandidateMap:
    candidates: CandidateMap = defaultdict(list)
    for insight in raw_insights:
        category = str(insight.get("category") or "OUTROS")
        base_weight = CATEGORY_WEIGHT.get(category, CATEGORY_WEIGHT["OUTROS"])
        source = str(insight.get("page_blob") or insight.get("doc_id") or category)
        parsed = _parse_jsonish(insight.get("gpt_raw"))
        if parsed is not None:
            _walk_json(parsed, [], candidates, category, source, base_weight)

        text = "\n".join(
            str(part or "") for part in (insight.get("full_desc"), insight.get("gpt_raw"))
        )
        _extract_from_text(text, candidates, category, source, base_weight)
    return candidates


def _walk_json(
    value: Any,
    path: list[str],
    candidates: CandidateMap,
    category: str,
    source: str,
    base_weight: int,
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _walk_json(child, [*path, str(key)], candidates, category, source, base_weight)
        return
    if isinstance(value, list):
        for child in value:
            _walk_json(child, path, candidates, category, source, max(1, base_weight - 1))
        return

    if _is_missing(value):
        return

    path_text = _norm(" ".join(path))
    raw_value = str(value)
    role = _role_from_path(path_text)

    if _path_has(path_text, "vin", "chassi", "chassis", "quadro"):
        for vin in _find_vins(raw_value):
            _add(candidates, "vin", vin, base_weight + 2, category, source)

    if _path_has(path_text, "matricula", "inscricao", "license plate", "kennzeichen", "placa"):
        for plate in _find_plates(raw_value):
            _add(candidates, "plate", plate, base_weight + 2, category, source)

    if _path_has(path_text, "quilometragem", "quilomet", "kilomet", "odometer"):
        km = _digits_only(raw_value)
        if km:
            _add(candidates, "kilometers", km, base_weight + 1, category, source)

    if _path_has(path_text, "primeiro registo", "primeiro registro", "first registration", "data primeiro", "primeira matricula"):
        _add_date_candidate(candidates, "first_registration_date", raw_value, base_weight + 1, category, source)

    if _path_has(path_text, "entrada") and _path_has(path_text, "portugal", "pt", "territorio"):
        _add_date_candidate(candidates, "entry_date", raw_value, base_weight + 1, category, source)

    if _path_has(path_text, "fatura numero", "factura numero", "invoice number", "fatura numero", "numero fatura") and not _path_has(path_text, "data"):
        _add(candidates, "invoice_number", raw_value, base_weight + 1, category, source)

    if _path_has(path_text, "fatura data", "factura data", "invoice date", "data fatura"):
        _add_date_candidate(candidates, "invoice_date", raw_value, base_weight + 1, category, source)

    if _path_has(path_text, "preco", "price", "valor total", "valor liquido", "valor veiculo", "gesamtbetrag", "netto"):
        money = _normalize_money(raw_value)
        if money:
            _add(candidates, "price", money, base_weight + 1, category, source)

    if _path_has(path_text, "pagamento", "payment", "forma de pagamento", "meio de pagamento"):
        _add(candidates, "payment_method", _squash_ws(raw_value), base_weight, category, source)

    if _path_has(path_text, "garantia", "warranty"):
        _add(candidates, "warranty", _squash_ws(raw_value), base_weight, category, source)

    if _path_has(path_text, "fundamento", "regulamento", "legal", "artigo", "article"):
        _add(candidates, "legal_basis", _squash_ws(raw_value), base_weight, category, source)

    if role == "buyer":
        _extract_party_leaf(candidates, path_text, raw_value, "buyer", base_weight, category, source)
    elif role == "seller":
        _extract_party_leaf(candidates, path_text, raw_value, "seller", base_weight, category, source)


def _extract_party_leaf(
    candidates: CandidateMap,
    path_text: str,
    raw_value: str,
    role: str,
    base_weight: int,
    category: str,
    source: str,
) -> None:
    if _path_has(path_text, "nome", "name", "firma", "cliente", "full name"):
        cleaned = _clean_name(raw_value)
        if cleaned and not _looks_like_noise(cleaned):
            _add(candidates, f"{role}_name", cleaned, base_weight + 1, category, source)

    if _path_has(path_text, "morada", "endereco", "address", "residencia"):
        cleaned = _squash_ws(raw_value)
        if cleaned:
            _add(candidates, f"{role}_address", cleaned, base_weight + 1, category, source)

    if _path_has(path_text, "nif", "fiscal", "tax", "contribuinte", "ust", "vat"):
        ident = _normalize_identifier(raw_value)
        if ident:
            _add(candidates, f"{role}_tax_id", ident, base_weight + 1, category, source)


def _extract_from_text(
    text: str,
    candidates: CandidateMap,
    category: str,
    source: str,
    base_weight: int,
) -> None:
    if not text:
        return

    for vin in _find_vins(text):
        _add(candidates, "vin", vin, base_weight, category, source)

    plate_labels = (
        r"(?:matr[ií]cula|n[uú]mero de inscri[cç][aã]o|license plate|placa)"
        r"\s*(?:do ve[ií]culo)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\s\-]{4,14})"
    )
    for match in re.finditer(plate_labels, text, flags=re.IGNORECASE):
        for plate in _find_plates(match.group(1)):
            _add(candidates, "plate", plate, base_weight, category, source)

    buyer_patterns = [
        ("buyer_name", r"(?:cliente|comprador|propriet[aá]rio|requerente|declarante)\s*(?:/ empresa)?\s*[:\-]\s*([^\n\r]+)"),
        ("buyer_tax_id", r"(?:nif|identifica[cç][aã]o fiscal)\s*(?:do comprador|do cliente|do requerente|do declarante|declarante|comprador|cliente|requerente)\s*[:\-]?\s*([A-Z0-9\s\.\-]{8,18})"),
        ("buyer_address", r"(?:morada|resid[eê]ncia|endere[cç]o)\s*(?:do comprador|do cliente|do requerente)?\s*[:\-]\s*([^\n\r]+)"),
        ("seller_name", r"(?:vendedor|empresa vendedora|seller)\s*[:\-]\s*([^\n\r]+)"),
        ("seller_tax_id", r"(?:ust[-\s]?idnr|vat|identifica[cç][aã]o fiscal do vendedor)\s*[:\-]?\s*([A-Z]{0,2}[0-9A-Z\s\.\-]{8,18})"),
        ("seller_address", r"(?:morada do vendedor|endere[cç]o do vendedor|seller address)\s*[:\-]\s*([^\n\r]+)"),
    ]
    for kind, pattern in buyer_patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = match.group(1).strip(" .;-")
            if kind.endswith("_tax_id"):
                value = _normalize_identifier(value)
            elif kind.endswith("_name"):
                value = _clean_name(value)
            else:
                value = _squash_ws(value)
            if value and not _looks_like_noise(value):
                _add(candidates, kind, value, base_weight, category, source)

    _extract_party_lines(text, candidates, category, source, base_weight)

    invoice_no = re.search(r"(?:n[uú]mero da fatura|n[ºo]\s*fatura|invoice number)\s*[:\-]\s*([A-Z0-9][A-Z0-9\-\.\/]+)", text, flags=re.IGNORECASE)
    if invoice_no:
        _add(candidates, "invoice_number", invoice_no.group(1), base_weight, category, source)

    for label, kind in (
        (r"(?:data da fatura|invoice date)", "invoice_date"),
        (r"(?:data de entrada|entrada do ve[ií]culo em portugal|entrada em portugal)", "entry_date"),
        (r"(?:primeira matr[ií]cula|primeiro registo|first registration)", "first_registration_date"),
    ):
        for match in re.finditer(label + r".{0,80}", text, flags=re.IGNORECASE | re.DOTALL):
            _add_date_candidate(candidates, kind, match.group(0), base_weight, category, source)

    for match in re.finditer(r"(?:quilometragem|quil[oó]metros|km)\s*[:\-]?\s*([0-9][0-9\.,\s]{2,12})\s*(?:km)?", text, flags=re.IGNORECASE):
        km = _digits_only(match.group(1))
        if km:
            _add(candidates, "kilometers", km, base_weight, category, source)

    for match in re.finditer(r"(?:valor total|pre[cç]o|valor l[ií]quido|gesamtbetrag|netto)\s*[:\-]?\s*(?:€|EUR)?\s*([0-9][0-9\.,\s]{2,15})", text, flags=re.IGNORECASE):
        money = _normalize_money(match.group(1))
        if money:
            _add(candidates, "price", money, base_weight, category, source)

    if re.search(r"\b(conduziu|conduzido|conduzida|por mim conduzido)\b", text, flags=re.IGNORECASE):
        _add(candidates, "entry_type", "Conduzido pelo próprio", base_weight, category, source)


def _extract_party_lines(
    text: str,
    candidates: CandidateMap,
    category: str,
    source: str,
    base_weight: int,
) -> None:
    role: str | None = None
    role_ttl = 0
    for raw_line in text.splitlines():
        line = raw_line.strip(" -•\t")
        if not line:
            role_ttl = max(0, role_ttl - 1)
            continue
        line_norm = _norm(line)
        if _path_has(line_norm, "vendedor", "empresa vendedora", "seller"):
            role = "seller"
            role_ttl = 5
        elif _path_has(line_norm, "cliente", "comprador", "buyer", "requerente", "declarante", "proprietario"):
            role = "buyer"
            role_ttl = 5

        if role and role_ttl > 0:
            nif_match = re.search(r"\b(?:NIF|USt[-\s]?IdNr|VAT|Identifica[cç][aã]o fiscal)\b\s*[:\-]?\s*([A-Z0-9\s\.\-]{8,18})", line, flags=re.IGNORECASE)
            if nif_match:
                ident = _normalize_identifier(nif_match.group(1))
                if ident:
                    _add(candidates, f"{role}_tax_id", ident, base_weight, category, source)

            address_match = re.search(r"(?:morada|endere[cç]o|resid[eê]ncia)\s*[:\-]\s*(.+)$", line, flags=re.IGNORECASE)
            if address_match:
                _add(candidates, f"{role}_address", _squash_ws(address_match.group(1)), base_weight, category, source)

        if category in {"CARTAO_CIDADAO", "CARTAO_CONTRIBUINTE"} or _path_has(line_norm, "eu,", "declaro", "declara:"):
            nif_match = re.search(r"\bNIF\b\s*[:\-]?\s*([0-9\s\.\-]{9,15})", line, flags=re.IGNORECASE)
            if nif_match:
                ident = _normalize_identifier(nif_match.group(1))
                if ident:
                    _add(candidates, "buyer_tax_id", ident, base_weight, category, source)

        role_ttl = max(0, role_ttl - 1)
        if role_ttl == 0:
            role = None


def _add_date_candidate(
    candidates: CandidateMap,
    kind: str,
    value: str,
    weight: int,
    category: str,
    source: str,
) -> None:
    parsed = _parse_date(value)
    if parsed:
        _add(candidates, kind, parsed.strftime("%d/%m/%Y"), weight, category, source)


def _add(candidates: CandidateMap, kind: str, value: Any, weight: int, category: str, source: str) -> None:
    if _is_missing(value):
        return
    value = _squash_ws(str(value))
    if not value:
        return
    candidates[kind].append({
        "value": value,
        "weight": weight,
        "category": category,
        "source": source,
    })


def _best_candidate(candidates: CandidateMap, kind: str) -> Any:
    values = candidates.get(kind) or []
    if not values:
        return None

    scores: dict[str, int] = defaultdict(int)
    display: dict[str, str] = {}
    for item in values:
        normalized = _candidate_key(kind, item["value"])
        if not normalized:
            continue
        scores[normalized] += int(item.get("weight") or 1)
        display.setdefault(normalized, _display_value(kind, item["value"]))

    if not scores:
        return None
    winner = max(scores, key=lambda value: (scores[value], len(display[value])))
    return display[winner]


def _candidate_key(kind: str, value: Any) -> str | None:
    if _is_missing(value):
        return None
    if kind == "vin":
        return _normalize_vin(value)
    if kind == "plate":
        return _normalize_plate(value)
    if kind in {"price"}:
        return _normalize_money(value)
    if kind.endswith("_date"):
        parsed = _parse_date(value)
        return parsed.strftime("%d/%m/%Y") if parsed else None
    if kind in {"kilometers"}:
        return _digits_only(value)
    if kind.endswith("_tax_id"):
        return _normalize_identifier(value)
    return _norm(str(value))


def _display_value(kind: str, value: Any) -> str:
    if kind == "vin":
        return _normalize_vin(value) or str(value)
    if kind == "plate":
        return _normalize_plate(value) or str(value)
    if kind == "price":
        return _normalize_money(value) or str(value)
    if kind.endswith("_date"):
        parsed = _parse_date(value)
        return parsed.strftime("%d/%m/%Y") if parsed else str(value)
    if kind == "kilometers":
        return _digits_only(value) or str(value)
    if kind.endswith("_tax_id"):
        return _normalize_identifier(value) or str(value)
    return _squash_ws(str(value))


def _parse_jsonish(raw: Any) -> Any:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _role_from_path(path_text: str) -> str | None:
    if _path_has(path_text, "vendedor", "seller", "empresa vendedora", "dados empresa vendedora", "remetente"):
        return "seller"
    if _path_has(path_text, "comprador", "buyer", "cliente", "kunde", "adquirente", "requerente", "declarante", "proprietario", "owner"):
        return "buyer"
    return None


def _path_has(path_text: str, *needles: str) -> bool:
    return any(_norm(needle) in path_text for needle in needles)


def _find_vins(text: Any) -> list[str]:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(text)).upper()
    vins = re.findall(r"[A-HJ-NPR-Z0-9]{17}", cleaned)
    return [vin for vin in vins if not re.fullmatch(r"\d{17}", vin)]


def _find_plates(text: Any) -> list[str]:
    found: list[str] = []
    for token in re.findall(r"[A-Z0-9][A-Z0-9\s\-]{3,14}[A-Z0-9]", str(text).upper()):
        plate = _normalize_plate(token)
        if plate and _looks_like_plate(plate):
            found.append(plate)
    return found


def _normalize_vin(value: Any) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()
    match = re.search(r"[A-HJ-NPR-Z0-9]{17}", cleaned)
    return match.group(0) if match else None


def _normalize_plate(value: Any) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()
    if not _looks_like_plate(cleaned):
        return None
    return cleaned


def _looks_like_plate(value: Any) -> bool:
    value = str(value or "").upper()
    if len(value) < 5 or len(value) > 10:
        return False
    if len(value) == 17:
        return False
    if not re.search(r"[A-Z]", value) or not re.search(r"\d", value):
        return False
    if re.fullmatch(r"[A-Z]\d{2,3}[A-Z]?", value):
        return False
    return True


def _digits_only(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits or None


def _normalize_money(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    text = re.sub(r"[^0-9,\.]", "", raw)
    if not text:
        return None

    if "," in text and "." in text:
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        text = text.replace(thousands_sep, "")
        text = text.replace(decimal_sep, ".")
    elif "," in text:
        parts = text.split(",")
        text = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) in {1, 2} else "".join(parts)
    elif text.count(".") > 1:
        parts = text.split(".")
        text = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) in {1, 2} else "".join(parts)

    try:
        amount = float(text)
    except ValueError:
        return None
    return f"{amount:.2f}"


def _parse_date(value: Any) -> date | None:
    text = str(value or "")
    if not text.strip():
        return None

    for pattern in (
        r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b",
        r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b",
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        a, b, c = [int(part) for part in match.groups()]
        if a > 1900:
            year, month, day = a, b, c
        else:
            day, month, year = a, b, c
            if year < 100:
                year += 2000 if year < 70 else 1900
        try:
            return date(year, month, day)
        except ValueError:
            pass

    month_pattern = r"\b(\d{1,2})\s+de\s+([A-Za-zçÇãõáéíóúâêôà]+)\s+(?:de\s+)?(\d{4})\b"
    match = re.search(month_pattern, text, flags=re.IGNORECASE)
    if match:
        day = int(match.group(1))
        month_name = _norm(match.group(2))
        month = MONTHS_PT.get(month_name)
        year = int(match.group(3))
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                return None

    return None


def _normalize_identifier(value: Any) -> str | None:
    text = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    return text or None


def _looks_like_tax_id(value: Any) -> bool:
    ident = _normalize_identifier(value)
    if not ident:
        return False
    return bool(re.fullmatch(r"\d{9}", ident) or re.fullmatch(r"[A-Z]{2}[A-Z0-9]{8,14}", ident))


def _id_type(value: Any) -> str | None:
    ident = _normalize_identifier(value)
    if not ident:
        return None
    if re.fullmatch(r"\d{9}", ident):
        return "NIF"
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{8,14}", ident):
        return "NIF estrangeiro"
    return "Cartão de Cidadão"


def _party_status(name: Any, tax_id: Any) -> str | None:
    name_norm = f" {_norm(name or '')} "
    if any(token.strip() in name_norm for token in COMPANY_TOKENS):
        return "Empresa"
    ident = _normalize_identifier(tax_id)
    if ident and not re.match(r"^[A-Z]{2}", ident):
        return "Particular"
    if ident and re.match(r"^[A-Z]{2}", ident):
        return "Empresa"
    if name and len(str(name).split()) >= 2:
        return "Particular"
    return None


def _seller_quality(name: Any, tax_id: Any) -> str | None:
    status = _party_status(name, tax_id)
    if status == "Empresa":
        return "Empresa"
    if _looks_like_tax_id(tax_id) and re.match(r"^[A-Z]{2}", _normalize_identifier(tax_id) or ""):
        return "Empresa"
    return status


def _country_from_text(value: Any) -> str | None:
    text = _norm(value or "")
    for marker, country in COUNTRY_MARKERS.items():
        if marker in text:
            return country
    return None


def _country_from_tax_id(value: Any) -> str | None:
    ident = _normalize_identifier(value)
    if not ident or len(ident) < 2:
        return None
    prefix = ident[:2]
    return {
        "DE": "Alemanha",
        "BE": "Bélgica",
        "FR": "França",
        "ES": "Espanha",
        "IT": "Itália",
        "NL": "Países Baixos",
        "PT": "Portugal",
    }.get(prefix)


def _same_person(left: Any, right: Any) -> bool:
    if _is_missing(left) or _is_missing(right):
        return False
    left_norm = _norm(left)
    right_norm = _norm(right)
    if left_norm == right_norm:
        return True
    left_parts = set(left_norm.split())
    right_parts = set(right_norm.split())
    common = left_parts & right_parts
    return len(common) >= 2 and len(common) >= min(len(left_parts), len(right_parts)) - 1


def _vehicle_fiscal_type(category: Any, vehicle_type: Any) -> str | None:
    text = _norm(f"{category or ''} {vehicle_type or ''}")
    if "m1" in text or "passage" in text or "ligeiro" in text:
        return "Ligeiro de passageiros"
    if "mercadorias" in text or "n1" in text:
        return "Ligeiro de mercadorias"
    return None


def _entry_type(raw_insights: list[dict[str, Any]] | None, dc21: Any, dc22: Any) -> str | None:
    if not _is_missing(dc21):
        return dc21
    if not _is_missing(dc22):
        return "Transportadora"
    if _raw_mentions(raw_insights, "conduziu") or _raw_mentions(raw_insights, "conduzido") or _raw_mentions(raw_insights, "por mim conduzido"):
        return "Conduzido pelo próprio"
    if _raw_mentions(raw_insights, "CMR"):
        return "Transportadora"
    return None


def _raw_mentions(raw_insights: list[dict[str, Any]] | None, needle: str) -> bool:
    if not raw_insights or not needle:
        return False
    needle_norm = _norm(needle)
    for insight in raw_insights:
        haystack = _norm(f"{insight.get('category') or ''}\n{insight.get('gpt_raw') or ''}\n{insight.get('full_desc') or ''}")
        if needle_norm in haystack:
            return True
    return False


def _to_int(value: Any) -> int | None:
    digits = _digits_only(value)
    return int(digits) if digits else None


def _clean_name(value: Any) -> str | None:
    text = _squash_ws(str(value or "").strip(" .;-:"))
    if not text or _looks_like_tax_id(text):
        return None
    return text


def _looks_like_noise(value: Any) -> bool:
    text = _norm(value or "")
    return text in {"nao especificado", "none", "null", "n/a", "---"} or len(text) < 2


def _squash_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _norm(value: Any) -> str:
    text = str(value or "").lower()
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _squash_ws(ascii_text)
