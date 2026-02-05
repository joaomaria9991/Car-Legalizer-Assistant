EXTRACT_DADOS_CARRO = """
Analisa esta imagem de um documento automóvel e extrai APENAS os dados relevantes para DAV Alfândega Portuguesa.

IMPORTANTE:
- Documento pode estar em ALEMÃO, INGLÊS, PORTUGUÊS ou outras línguas
- Extrai MESMO ASSIM - reconhece números, matrículas, VIN, etc.
- Devolve SEMPRE o mesmo JSON, mesmo que alguns campos sejam null

JSON EXATO:
{{
  "34": "Marca (Mercedes, BMW, etc)",
  "35": "Modelo completo (A180, 320d, etc)", 
  "36": "Variante (CDI, AMG, etc)",
  "42": "VIN/Chassi (17 dígitos)",
  "61": "Matrícula definitiva",
  "45": "Cilindrada cm³",
  "39": "Combustível (Diesel, Benzin, Gasolina, etc)",
  "37": "Peso bruto kg",
  "44": "Nº lugares",
  "41": "Caixa (Manual, Automática)",
  "40": "Cor",
  "60": "1ª matrícula (YYYY-MM-DD)",
  "DC10": "Nº fatura",
  "DC11": "Data fatura (YYYY-MM-DD)",
  "DC13": "Preço €",
  "DC01": "Vendedor",
  "DC05": "Comprador"
}}

Regras:
1. NUNCA inventes dados
2. Se não encontrares = null (NÃO deixes string vazia)
3. Matrícula: reconhece formatos DE, PT, etc (ex: AA00AA, M-AB 1234)
4. VIN: SEMPRE 17 dígitos alfanuméricos
5. Data: formato YYYY-MM-DD quando possível
"""




GENERATE_DAV = """
DAV oficial português para:
CARRO: {dados_carro}
FISCAL: {dados_fiscal}

Texto DAV completo, formato oficial.
"""