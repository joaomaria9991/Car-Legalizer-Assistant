EXTRACT_DADOS_CARRO = """
Analisa fatura/DUA e extrai dados do carro NUMERICAMENTE:

TEXTO:
{texto}

JSON exato (não inventes valores):
{{
  "marca": "Mercedes",
  "modelo": "A250e", 
  "matricula": "AB-12-CD",
  "chassi": "WDD...",
  "cilindrada": "1600",
  "potencia_kw": 118,
  "ano": 2023,
  "quilometros": 25000,
  "valor_fatura": 35000
}}

APENAS JSON VÁLIDO.
"""

GENERATE_DAV = """
DAV oficial português para:
CARRO: {dados_carro}
FISCAL: {dados_fiscal}

Texto DAV completo, formato oficial.
"""
