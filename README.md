# Car Legalizer Assistant

Uma plataforma agentic para ajudar na legalização de veículos em Portugal, com foco no preenchimento da **Declaração Aduaneira de Veículos (DAV)** da Autoridade Tributária.

O produto recebe documentos do processo, classifica-os, extrai dados relevantes, cruza informação entre fontes, induz campos equivalentes, deteta campos em falta e guia o utilizador até uma DAV mais completa e auditável.

## Preview

Substitui estes placeholders pelos teus prints quando quiseres fazer showcase do produto.

| Process Hub | Agent Flow |
| --- | --- |
| ![Process Hub placeholder](docs/screenshots/process-hub.png) | ![Agent Flow placeholder](docs/screenshots/agent-flow.png) |

| DAV Mirror | Assistant |
| --- | --- |
| ![DAV Mirror placeholder](docs/screenshots/dav-mirror.png) | ![Assistant placeholder](docs/screenshots/assistant.png) |

| Document Preview | Mobile |
| --- | --- |
| ![Document Preview placeholder](docs/screenshots/document-preview.png) | ![Mobile placeholder](docs/screenshots/mobile.png) |

## O que faz

- **Process Hub** para criar processos novos ou retomar processos guardados em Azure Blob Storage.
- **Upload inteligente** de PDFs/imagens, com divisão de PDFs em páginas JPG no browser.
- **Classificação documental** para identificar faturas, certificados, transporte, homologação, inspeções e outros documentos relevantes.
- **Extração multimodal** com Azure OpenAI para obter dados estruturados por página.
- **Harmonização DAV** para consolidar várias fontes num único `dados_carro`.
- **Autofill determinístico** para preencher campos equivalentes, como comprador/declarante, datas espelhadas, valores e campos AT relacionados.
- **Metadados de confiança por campo**: extraído, induzido, utilizador, em falta, revisão, conflito ou não aplicável.
- **Regras de aplicabilidade** para bloquear campos que não fazem sentido, por exemplo dados de intermediário quando não houve intermediário.
- **Assistant de revisão** que pergunta primeiro decisões com impacto e depois ajuda a preencher campos em falta.
- **Espelho DAV ao estilo AT** com tabs, secções e códigos próximos do formulário real.
- **Preview e download de documentos** diretamente no frontend.
- **Timeline agentic** para acompanhar upload, classificação, extração, harmonização, autofill e revisão.

## Fluxo do produto

```mermaid
flowchart LR
    A["Criar ou abrir processo"] --> B["Upload de documentos"]
    B --> C["Classificação"]
    C --> D["Extração por página"]
    D --> E["Harmonização DAV"]
    E --> F["Autofill e regras"]
    F --> G["Assistant de revisão"]
    G --> H["Espelho DAV"]
    H --> I["DAV pronta para validação"]
```

## Arquitetura

```mermaid
flowchart TB
    U["Utilizador / Importador"]

    subgraph FE["Frontend React"]
        HUB["Process Hub"]
        UPLOAD["Upload + PDF page split"]
        PROGRESS["Agent Progress Timeline"]
        CHAT["Assistant Chat"]
        MIRROR["AT-style DAV Mirror"]
        DOCS["Document Preview / Download"]
    end

    subgraph API["FastAPI Backend"]
        EVENTS["/processes/{id}/events"]
        STATE_API["/processes + /documents"]
        BG["Background extraction jobs"]
    end

    subgraph AGENTS["Agentic Workflow"]
        CLASSIFY["Document classifier"]
        EXTRACT["Vision extraction per page"]
        HARMONIZE["DAV harmonizer"]
        AUTOFILL["Deterministic autofill"]
        RULES["Applicability rules"]
        REVIEW["DAV review planner"]
        TOOLCALL["set_dav_field tool-calling"]
    end

    subgraph MEMORY["Process Memory"]
        BLOB_DOCS["Blob docs/pages"]
        BLOB_STATE["Blob state.json"]
        META["Field trust metadata"]
        LOGS["Agent progress log"]
    end

    subgraph AI["External AI Services"]
        AOAI["Azure OpenAI"]
    end

    U <--> HUB
    U <--> CHAT
    U --> UPLOAD
    HUB <--> STATE_API
    UPLOAD --> EVENTS
    CHAT <--> EVENTS
    PROGRESS <--> STATE_API
    MIRROR <--> STATE_API
    DOCS <--> STATE_API

    EVENTS <--> BLOB_STATE
    STATE_API <--> BLOB_STATE
    STATE_API <--> BLOB_DOCS
    EVENTS --> BG

    BG --> CLASSIFY
    CLASSIFY <--> AOAI
    CLASSIFY --> BLOB_STATE
    BG --> EXTRACT
    EXTRACT <--> BLOB_DOCS
    EXTRACT <--> AOAI
    EXTRACT --> HARMONIZE
    HARMONIZE <--> AOAI
    HARMONIZE --> AUTOFILL
    AUTOFILL --> RULES
    RULES --> REVIEW
    REVIEW --> CHAT
    CHAT --> TOOLCALL
    TOOLCALL --> AUTOFILL

    AUTOFILL --> META
    RULES --> META
    REVIEW --> META
    AGENTS --> LOGS
    META --> BLOB_STATE
    LOGS --> BLOB_STATE
    BLOB_STATE --> PROGRESS
    BLOB_STATE --> MIRROR
    BLOB_STATE --> CHAT
```

## Stack

- **Frontend:** React, TypeScript, Vite, CSS, lucide-react, pdfjs-dist.
- **Backend:** FastAPI, Pydantic, LangGraph, Azure OpenAI SDK, Azure Blob Storage SDK.
- **AI:** Azure OpenAI vision/text extraction, deterministic harmonization/autofill layers.

## Estrutura

```text
app/
  graph/            Backend workflow, extraction, autofill, DAV metadata
  models/           Pydantic state/event models
  prompts/          Classification/extraction/DAV prompts
  storage/          Azure Blob client
frontend/
  src/              React app, DAV mirror, assistant, API client
```

## Como correr localmente

### 1. Backend

Cria um `.env` local com as tuas variáveis. Não faças commit desse ficheiro.

```powershell
AZURE_STORAGE_CONNECTION_STRING=...
CONTAINER_NAME=car-legalization
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-11-20
CORS_ORIGINS=http://localhost:5173
```

Instala e corre:

```powershell
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```powershell
cd frontend
npm install
copy .env.example .env
npm run dev
```

Por default, o frontend espera a API em:

```text
http://localhost:8000
```

## Testes

Backend:

```powershell
venv\Scripts\python.exe -m unittest discover -s app\tests -p "test*.py"
venv\Scripts\python.exe -m compileall -q app
```

Frontend:

```powershell
cd frontend
npm run build
```

## Roadmap

- Geração/exportação final da DAV.
- Melhor auditoria por fonte/documento/página.
- Mais regras AT de aplicabilidade.
- Melhor chunking do frontend build.
- Autenticação de utilizadores.
- Observabilidade com dashboards de erros/progresso.


## Licença

Ver [LICENSE](LICENSE).
