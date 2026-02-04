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



HARMONIZE_DADOS_CARRO = """
Tens abaixo o conteúdo textual que foi extraído por uma IA de TODAS as páginas de documentos relacionados com um carro.
O texto já pode estar parcialmente estruturado, mas assume que pode haver redundâncias, contradições ou campos em branco.

----------------- CONTEXTO COMPLETO -----------------
{raw_context}
-----------------------------------------------------

A partir APENAS da informação acima, constrói um ÚNICO objeto JSON com o melhor conhecimento que consegues ter sobre o carro.
Segue estas regras:

1) Estrutura EXATA do JSON de saída (sem texto extra, sem comentários, sem campos adicionais):

{{
  "marca": string | null,
  "modelo": string | null,
  "versao": string | null,
  "matricula_origem": string | null,
  "matricula_portuguesa": string | null,
  "vin": string | null,
  "combustivel": string | null,
  "potencia_kw": number | null,
  "cilindrada_cm3": number | null,
  "ano_fabricacao": number | null,
  "ano_primeira_matricula": number | null,
  "co2_g_km": number | null,
  "peso_bruto_kg": number | null,
  "lugares": number | null,
  "portas": number | null,
  "caixa": string | null,          // ex: "manual", "automatica"
  "tracao": string | null,         // ex: "dianteira", "traseira", "4x4"
  "cor": string | null,
  "extras_relevantes": string | null,   // texto livre com extras importantes
  "origem_pais": string | null,
  "observacoes": string | null
}}

2) Se um campo NÃO estiver presente em lado nenhum do contexto, coloca explicitamente null.
3) Se encontraste valores contraditórios em páginas diferentes:
   - escolhe o valor que parece mais fiável (por exemplo, aparece em documentos oficiais como certificado de matrícula ou COC),
   - e explica brevemente a dúvida em "observacoes".
4) NUNCA inventes dados. Se não tens a certeza, usa null e descreve a dúvida em "observacoes".
5) A resposta deve ser APENAS o JSON final, sem qualquer texto antes ou depois.
"""
