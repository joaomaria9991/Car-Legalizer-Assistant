import json
from typing import Any, Dict, List

# -----------------------------
# Prompt(s)
# -----------------------------

HARMONIZE_DADOS_CARRO_SYSTEM = """You are an exacting data harmonization engine for Portuguese vehicle import paperwork (DAV / ISV).
Your job is to merge multiple partial extractions into ONE single flat JSON object, used to prefill a DAV form.

INPUT
- You will receive multiple "raw insights" from different documents/pages.
- Each insight contains:
  - doc_id
  - category (document type)
  - a JSON object string ("gpt_raw") with extracted fields (e.g., "34", "35", "42", "61", "DC10", etc.)
- Some extractions may contain typos, conflicting values, or values placed under the wrong code.

OUTPUT (STRICT)
- Output MUST be a single JSON object (no markdown, no extra text).
- Output keys MUST be exactly in the format: "<CODE>:<FIELD_NAME>".
- Output MUST contain ALL fields from the provided DAV template (even if null).
- If a value is unknown or cannot be confidently derived, output null.

MERGE & PRIORITY RULES
1) Prefer values from the most authoritative category when conflicts exist:
   Highest → Lowest
   - CERTIFICADO_MATRICULA
   - HOMOLOGACAO_TECNICA_IMT
   - COMPROVATIVO_INSPECAO_TECNICA
   - DOCUMENTO_TRANSPORTE_CMR
   - FATURA_COMPRA
   - OUTROS

2) If the same code appears multiple times:
   - pick the non-null value with highest category priority
   - if same priority, choose the one that is more complete / plausible
   - if still ambiguous, keep null for that field (do not guess)

3) Detect common OCR/typing variants and normalize:
   - Plate and VIN: remove spaces, keep uppercase.
   - Plate common confusions: O vs 0, I vs 1, S vs 5, etc. Prefer the variant that appears most often across documents.
   - Dates: output in "DD/MM/YYYY" when day/month/year are known.
   - Currency: output numeric string with dot decimal, no symbol (e.g., "15000.00").
   - Kilometers: output digits only (e.g., "156000").
   - Weights/capacity: output digits only.

4) Code semantic overrides (misplaced values):
   - CODE 42 is VIN (17 chars alphanumeric). If a "42" value looks like money (contains € or decimal with currency context) do NOT place it into 42; treat it as candidate for DC13 (price) or 58/77 (values) depending on context.
   - CODE 39 is fuel type (e.g., Diesel, Gasolina, Elétrico). If fuel appears elsewhere (like code 45), place it into 39.

5) Vehicle status:
   - If first registration date (field 60) exists and is in the past, set 55 to "Usado".
   - If first registration date is missing, keep 55 as null unless explicitly stated.

6) Consistency checks:
   - VIN should be 17 characters; if multiple VINs exist, pick the most frequent non-null valid-length one. If still conflicts, set null.
   - Plate should look like a plausible PT plate string; prefer the version repeated across documents.

DO NOT
- Do NOT invent unknown fields.
- Do NOT output arrays or nested objects.
- Do NOT include provenance, explanations, confidence scores, or comments in the output.
- Do NOT omit keys from the template.

Return ONLY the final JSON object.
"""

HARMONIZE_DADOS_CARRO_USER_TEMPLATE = """Harmoniza e preenche o JSON final no formato "CODIGO:Nome do Campo": "Valor" com base nos raw insights abaixo.

RAW INSIGHTS:
{raw_context}

DAV TEMPLATE (tens de devolver TODAS estas chaves, mesmo que seja null):
{dav_template}

Regras rápidas:
- Muito importante: Muitas vezes os valores campos podem ser iguais mas não tem o mesmo nome, Ex: "76:Quilómetros do veículo à data da transmissão" e "57:Quilómetros do veículo à data da DAV" podem ter o mesmo valor apesar de serem campos diferentes. Para estes casos, tenta perceber qual é o valor correto para cada campo com base no contexto.
- NÃO inventes nada. Se não tiveres, mete null.
- NORMALIZA datas para DD/MM/YYYY.
- NORMALIZA euros e kms para apenas números.
- Resultado final tem de ser APENAS um JSON (sem texto).
"""


# -----------------------------
# Default DAV template (flat keys)
# -----------------------------
DEFAULT_DAV_TEMPLATE: Dict[str, Any] = {
  "01:Alfândega da criação da DAV": None,
  "01a:Alfândega da versão atual da DAV": None,
  "02:Estatuto do sujeito passivo": None,
  "05:Regime de ISV aplicado": None,

  "06:Tipo de identificação do adquirente/proprietário": None,
  "06a:Número de identificação do adquirente/proprietário (Número CC)": None,

  "14:Qualidade da representação do declarante": None,
  "15:Tipo de identificação do representante": None,
  "15a:Número de identificação do representante": None,
  "16:NIF da sociedade HD": None,
  "17:Tipo de identificação do declarante": None,
  "17a:Número de identificação do declarante": None,
  "18:Nome ou denominação social do declarante": None,


  "30:Número de registo no IMT": None,
  "31:Categoria do veículo": None,
  "32:Tipo de veículo IMT": None,
  "33:Tipo de veículo fiscal": None,
  "34:Marca do veículo": None,
  "35:Modelo do veículo": None,
  "36:Variante do veículo": None,
  "36a:Versão do veículo": None,
  "37:Peso bruto do veículo em kg": None,
  "38:Tara do veículo em kg": None,
  "39:Tipo de combustível": None,
  "40:Cor do veículo": None,
  "41:Tipo de caixa de velocidades": None,
  "42:Número de quadro (VIN)": None,
  "43: Número de Motor": None,
  "44:Número de lugares": None,
  "45:Cilindrada do motor em cm3": None,
  "46:Número de eixos motores": None,
  "47:Comprimento da caixa em mm": None,
  "48:Altura mínima da caixa em mm": None,
  "49:Antepara inamovível da caixa": None,
  "49a:Tipo de testes CO2": None,
  "50:Emissões de CO2 em g/km": None,
  "51:Emissões de partículas em g/km": None,
  "52:Autonomia da bateria": None,
  "53:Tipo de caixa de velocidades": None,

  "55:Estado do veículo": None,
  "57:Quilómetros do veículo à data da DAV": None,
  "58:Valor comercial do veículo": None,
  "56:País de procedência do veículo": None,

  "60:Data da primeira matrícula": None,
  "61:Número da matrícula definitiva": None,
  "62:Data de atribuição da matrícula definitiva": None,
  "63:Número da matrícula provisória": None,
  "64:Data de atribuição da matrícula provisória": None,
  "65:Data de fim da validade da matrícula provisória": None,

  "66:Data de entrada do veículo em território nacional": None,
  "66a:Tipo de entrada do veículo": None,
  "67:Data de apresentação da DAV": None,
  "68:Número da declaração de importação": None,
  "69:Tipo de declaração de importação": None,
  "70:País de entrada em livre prática na UE": None,

  "75:Data da transmissão do veículo": None,
  "76:Quilómetros do veículo à data da transmissão": None,
  "77:Valor de aquisição do veículo em euros": None,
  "78:Taxa de IVA aplicada": None,
  "79:Código de isenção de IVA": None,
  "80:Indicação de operação não tributável": None,

  "84:Modo de pagamento": None,
  "85:Garantia do veículo": None,
  "86:Fundamento legal": None,

  "89:Serviço emissor do IMT": None,
  "90:Número de matrícula atribuído": None,
  "91:Data do registo IMT": None,

  "DC01:Nome ou denominação social do vendedor": None,
  "DC02:Morada do vendedor": None,
  "DC02a:País do vendedor": None,
  "DC03:Qualidade do vendedor": None,
  "DC04:Identificação fiscal do vendedor": None,
  "DC04a:País da identificação fiscal do vendedor": None,

  "DC05:Nome ou denominação social do comprador": None,
  "DC06:Morada do comprador": None,
  "DC07:Qualidade do comprador": None,
  "DC08:Identificação fiscal do comprador": None,

  "DC09:Enquadramento do comprador para efeitos de IVA": None,
  "DC10:Número da fatura": None,
  "DC11:Data da fatura": None,
  "DC12:Regime de tributação utilizado": None,
  "DC13:Preço do veículo": None,
  "DC14:Moeda utilizada": None,
  "DC15:Meio de pagamento da aquisição": None,

  "DC16:Existência de intermediários na transação": None,
  "DC17:Nome do intermediário": None,
  "DC18:Morada do intermediário": None,
  "DC19:Qualidade do intermediário": None,
  "DC20:Identificação fiscal do intermediário": None,

  "DC21:Meio de transporte utilizado para trazer o veículo": None,
  "DC22:Nome da empresa transportadora": None,
  "DC23:Morada da empresa transportadora": None,
  "DC24:Identificação fiscal da empresa transportadora": None,

  "DC25:Data de entrada do veículo em território nacional": None,
  "DC26:Forma como teve conhecimento do negócio": None,
  "DC27:Site de internet associado ao negócio": None
}