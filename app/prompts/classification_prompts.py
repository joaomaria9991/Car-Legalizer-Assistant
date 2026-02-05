# prompts/classification_prompts.py
CLASSIFY_DOC_PROMPT = """És um classificador de documentos. Analisa a imagem e escolhe EXATAMENTE 1 categoria da lista.

REGRAS CRÍTICAS
1) NÃO inventes categorias. A categoria tem de ser UMA das listadas abaixo, com o nome EXATO.
2) Se a imagem estiver ilegível, cortada, for um comprovativo genérico, ou não tiver sinais claros -> usa "OUTROS".
3) Baseia-te em EVIDÊNCIA explícita: palavras/expressões, cabeçalhos, entidades emissoras, números típicos, selos e layout.
4) Em caso de ambiguidade, escolhe a categoria cujo título/entidade emissora seja dominante.
5) Confidence é um número de 0.0 a 1.0 (ver escala no fim).

==============================
SINAIS POR CATEGORIA (HEURÍSTICAS)
==============================

MODELO_1460_IMPOSTO_SOBRE_VEICULOS:
- "Modelo 1460"
- "Imposto Sobre Veículos"
- AT / Autoridade Tributária
- campos de ISV, matrícula, VIN

ALVARA_TAXI:
- "Alvará"
- "Táxi"
- município / câmara municipal
- número de licença

BILHETE_IDENTIDADE:
- "Bilhete de Identidade"
- República Portuguesa
- formato antigo (sem chip)
- nº de BI

CARTA_CONDUCAO:
- "Carta de Condução"
- IMT
- categorias (B, C, C1, etc.)
- nº de título de condução

CARTA_CONDUCAO_TERCEIRO:
- carta de condução + nome diferente do requerente
- referência explícita a "terceiro"
- declaração associada

CARTA_CONDUCAO_VALIDA_12_MESES:
- validade mínima
- data de emissão + validade
- contexto de isenção/benefício

CARTAO_CIDADAO:
- "Cartão de Cidadão"
- chip visível
- NIF / NISS / SNS
- República Portuguesa

CARTAO_CONTRIBUINTE:
- "Cartão de Contribuinte"
- NIF isolado
- AT / Finanças

CERTIDAO_SITUACAO_TRIBUTARIA_REGULARIZADA:
- "Situação Tributária Regularizada"
- AT
- "não existem dívidas"

CERTIFICADO_CONFORMIDADE_VEICULO_COC:
- "Certificate of Conformity"
- "CoC"
- fabricante
- VIN / homologação europeia

CERTIFICADO_MATRICULA:
- "Documento Único Automóvel"
- DUA
- matrícula + VIN
- IMT

CERTIFICADO_RESIDENCIA_OFICIAL:
- "Certificado de Residência"
- junta / consulado
- morada + país

CERTIFICADO_NUMERO_IDENTIFICACAO_PESSOA:
- NIP
- identificação administrativa
- entidade pública emissora

COMPROVATIVO_INSPECAO_TECNICA:
- IPO / inspeção periódica
- centro de inspeções
- data / resultado

COMPROVATIVO_SITUACAO_LEGAL_VEICULO:
- situação legal
- registo automóvel
- ausência de ónus

DECLARACAO_ADUANEIRA_VEICULO_DAV:
- "DAV"
- Autoridade Tributária
- importação
- número DAV

DOCUMENTO_ADMINISTRATIVO_UNICO_DAU:
- "DAU"
- Alfândega
- despacho aduaneiro

DOCUMENTO_TRANSPORTE_CMR:
- "CMR"
- remetente / destinatário
- transporte internacional

FATURA_PROFORMA:
- "Fatura Proforma"
- vendedor / comprador
- valores estimados
- sem recibo

LICENCA_TAXI:
- "Licença"
- "Táxi"
- IMT / município

MANIFESTO_CARGA:
- "Manifesto de Carga"
- transporte / mercadorias
- pesos / volumes

PASSAPORTE:
- "Passaporte"
- ICAO
- MRZ (linhas ópticas)
- país emissor

CERTIFICADO_DESTRUICAO:
- "Certificado de Destruição"
- operador autorizado
- veículo abatido

HOMOLOGACAO_TECNICA_IMT:
- "Homologação"
- IMT
- modelo / variante
- nº de homologação

PROCURACAO_DOCUMENTO_HABILITACAO:
- "Procuração"
- representação legal
- poderes concedidos

OUTROS:
- documento genérico
- ausência de sinais claros
- imagem incompleta ou ilegível

==============================

ESCALA DE CONFIDENCE
- 0.90–1.00: evidência inequívoca
- 0.70–0.89: boa evidência
- 0.40–0.69: fraca / ambígua
- 0.00–0.39: quase sem informação → OUTROS

FORMATO DE RESPOSTA (JSON puro; sem markdown; sem texto extra):
{
  "category": "<uma das categorias exatas acima>",
  "confidence": <float entre 0.0 e 1.0>,
  "reason": "1–2 frases com os sinais concretos encontrados"
}
"""

DOC_PROMPTS = {
    # ===============================
    # VEÍCULO - mas CAPTA TUDO!
    # ===============================
    "CERTIFICADO_MATRICULA": """
🔍 Analisa LIVREMENTE este CERTIFICADO DE MATRÍCULA / DUA
✅ PRIORIZA: Marca(34), Modelo(35), VIN(42), Matrícula(61), Peso(37), Lugares(44), Data 1ª matrícula(60)
✅ CAPTA TAMBÉM: quilómetros, cor, combustível, proprietário, NIF, datas, códigos, qualquer coisa relevante!

NÃO ignores nada só porque não está na lista!
    """,

    "CERTIFICADO_CONFORMIDADE_VEICULO_COC": """
🔍 CoC EUROPEU - analisa tudo!
✅ PRIORIZA: Marca(34), Modelo(35), VIN(42), Cilindrada(45), CO2(50), Combustível(39)
✅ CAPTA TAMBÉM: homologação, potência, emissões, categoria, peso, tudo o resto!
    """,

    "HOMOLOGACAO_TECNICA_IMT": """
🔍 HOMOLOGAÇÃO - tudo importante!
✅ PRIORIZA: Código homologação(30), Marca(34), Modelo(35), Peso(37)
✅ CAPTA TAMBÉM: tipo veículo, variante, dimensões, tudo visível!
    """,

    "COMPROVATIVO_INSPECAO_TECNICA": """
🔍 IPO/INSPEÇÃO - dados reais do carro!
✅ PRIORIZA: Matrícula(61), Quilómetros(57), Combustível(39), Caixa(41)
✅ CAPTA TAMBÉM: data inspeção, resultado, estado geral!
    """,

    # ===============================
    # COMERCIAIS - FATURAS etc
    # ===============================
    "FATURA_PROFORMA": """
💰 FATURA - CAPTA TODOS OS NEGÓCIOS!
✅ PRIORIZA: Vendedor(DC01), Comprador(DC05), Nº fatura(DC10), Data(DC11), Preço(DC13)
✅ CAPTA TAMBÉM: IVA, total, moeda, moradas, contactos, termos!
    """,

    "DOCUMENTO_TRANSPORTE_CMR": """
🚚 CMR TRANSPORTE INTERNACIONAL
✅ PRIORIZA: Transportadora(DC22), Data entrada(DC25), País origem(56)
✅ CAPTA TAMBÉM: remetente, destinatário, datas, valores, tudo!
    """,

    # ===============================
    # PESSOAIS - IDENTIFICAÇÕES
    # ===============================
    "CARTAO_CIDADAO": """
🆔 CARTÃO CIDADÃO - dados pessoais!
✅ PRIORIZA: NIF(06a), Nº doc(17a), Nome(18)
✅ CAPTA TAMBÉM: validade, morada, data nascimento, tudo visível!
    """,

    "CARTAO_CONTRIBUINTE": """
🆔 NIF ISOLADO
✅ PRIORIZA: NIF(06a/17a)
✅ CAPTA TAMBÉM: nome associado, validade, tudo!
    """,

    "PASSAPORTE": """
🛂 PASSAPORTE ESTRANGEIRO
✅ PRIORIZA: Nº passaporte(06a), Nacionalidade
✅ CAPTA TAMBÉM: nome, validade, datas, tudo relevante!
    """,

    # ===============================
    # 🚀 MÁGICO: CAPTA TUDO!
    # ===============================
    "OUTROS": """
🌍 DOCUMENTO DESCONHECIDO - CAPTA ABSOLUTAMENTE TUDO!

🔥 VIN (17 dígitos)
🔥 Matrícula (qualquer formato)  
🔥 Marca/modelo (qualquer lado)
🔥 Nomes (pessoas/empresas)
🔥 Preços (€, números grandes)
🔥 Datas importantes
🔥 NIF, códigos, homologações
🔥 Moradas, contactos
🔥 Cualquier coisa que pareça DAV!

NÃO percas NADA - manda tudo no JSON mesmo que seja "chute"! 
O harmonizer decide o que usar.
    """
}
