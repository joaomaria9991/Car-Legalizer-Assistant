import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  ClipboardList,
  Clock3,
  Download,
  Eye,
  FileSearch,
  FileText,
  FileUp,
  FolderOpen,
  History,
  Info,
  Languages,
  Loader2,
  MessageSquare,
  Plus,
  RefreshCw,
  ScanLine,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  X,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent, MutableRefObject } from "react";
import { API_BASE_URL, documentFileUrl, getProcess, healthCheck, listProcessDocuments, listProcesses, postEvent } from "./api";
import {
  codeOf,
  inducedEntries,
  isMissing,
  isNotApplicable,
  labelOf,
  orphanFields,
  stateMetrics,
} from "./dav";
import { splitFilesForUpload } from "./pdf";
import type {
  AgentProgressEntry,
  DavFieldMeta,
  DavDecision,
  DavDecisionOption,
  DavValue,
  ExtractJob,
  ProcessDocument,
  DocumentPage,
  ProcessSummary,
  ProcessState,
  UiFieldPrompt,
  UploadProgress,
} from "./types";

type BusyAction = "load" | "processes" | "new" | "upload" | "classify" | "extract" | "refresh" | "chat" | "noop" | "pipeline" | "decision" | null;
type TabId = "process" | "progress" | "assistant" | "dav" | "history";
type ChatMessage = {
  id: string;
  role: "assistant" | "user" | "system";
  text: string;
  ts: string;
  applied?: Array<Record<string, unknown>>;
};
type Lang = "pt" | "en";
type AppProps = {
  authEnabled?: boolean;
  userName?: string | null;
  onLogout?: () => void;
};

const STRINGS = {
  pt: {
    apiOnline: "API online",
    apiOffline: "API offline",
    checkingApi: "A verificar API",
    newProcess: "Novo processo",
    savedProcesses: "Processos guardados",
    noSavedProcesses: "Ainda não há processos guardados",
    startAutoId: "Começar com ID automático",
    newProcessHelp: "Cria um processo na Blob, carrega documentos e deixa o fluxo de agentes correr até à revisão.",
    advanced: "Avançado",
    openById: "Abrir por ID do processo",
    open: "Abrir",
    processes: "Processos",
    continueProcessing: "Continuar processamento",
    resumeExtract: "Retomar extração",
    process: "Processo",
    agentFlow: "Fluxo de agentes",
    assistant: "Assistente",
    davMirror: "Espelho DAV",
    history: "Histórico",
    documents: "Documentos",
    filled: "Preenchidos",
    induced: "Induzidos",
    conflicts: "Conflitos",
    review: "Revisão",
    uploadDocuments: "Carregar documentos",
    liveProcess: "Processo ativo",
    dropDocs: "Arrasta PDFs ou imagens",
    pdfConverted: "As páginas PDF são convertidas para JPG antes do upload.",
    uploadAndProcess: "Carregar e processar",
    pipelineSnapshot: "Resumo do pipeline",
    nowRunning: "A decorrer",
    agentIdle: "Agente parado",
    knownStages: "etapas conhecidas concluídas.",
    timeline: "Timeline",
    agentStages: "Etapas dos agentes",
    recentLog: "Log recente",
    historyFallback: "Histórico",
    noProgress: "Ainda não há eventos de progresso.",
    pendingContext: "Contexto pendente",
    missingInformation: "Informação em falta",
    reviewAssistant: "Assistente de revisão",
    davReady: "DAV pronta",
    moreDocsNeeded: "Mais documentos necessários",
    needsAttention: "Requer atenção",
    findMissing: "Procurar info em falta",
    send: "Enviar",
    assistantPlaceholder: "Diz-me os valores em falta, ex. 78=23; 67=21/05/2026, ou responde naturalmente.",
    you: "Tu",
    system: "Sistema",
    assistantIntro: "Carrega documentos e eu identifico a informação DAV em falta, explico onde a encontrar e preencho campos quando responderes.",
    pendingFields: "campo(s)",
    noPending: "Sem perguntas DAV pendentes.",
    noConflicts: "Sem conflitos detetados.",
    noReviewFields: "Sem campos de revisão suave.",
    noInduced: "Sem campos induzidos ainda.",
    missingFields: "Campos em falta",
    completeDav: "Campos DAV completos.",
    backendTimeline: "Timeline backend",
    classifiedGroups: "grupo(s) classificado(s)",
    noBackendHistory: "Ainda não há histórico backend.",
    noDocuments: "Sem documentos classificados ainda.",
    documentPages: "Páginas de documentos",
    preview: "Pré-visualizar",
    download: "Download",
    close: "Fechar",
    noDocumentPages: "Ainda não há páginas para mostrar.",
    extracting: "A extrair páginas",
    extractionComplete: "Extração completa",
    extractionFailed: "Extração falhou",
    extractionStale: "Extração parada",
    waitingExtraction: "À espera da extração",
    stageQueued: "Em espera",
    uploadStage: "Upload",
    classifyStage: "Classificação",
    extractStage: "Extração",
    harmonizeStage: "Harmonização",
    autofillStage: "Autofill",
    davReviewStage: "Revisão DAV",
    readyStage: "Pronto",
  },
  en: {
    apiOnline: "API online",
    apiOffline: "API offline",
    checkingApi: "Checking API",
    newProcess: "New process",
    savedProcesses: "Saved processes",
    noSavedProcesses: "No saved processes yet",
    startAutoId: "Start with an automatic process ID",
    newProcessHelp: "Create a Blob-backed process, upload documents, and let the agent flow run through review.",
    advanced: "Advanced",
    openById: "Open by process id",
    open: "Open",
    processes: "Processes",
    continueProcessing: "Continue processing",
    resumeExtract: "Resume extraction",
    process: "Process",
    agentFlow: "Agent Flow",
    assistant: "Assistant",
    davMirror: "DAV Mirror",
    history: "History",
    documents: "Documents",
    filled: "Filled",
    induced: "Induced",
    conflicts: "Conflicts",
    review: "Review",
    uploadDocuments: "Upload documents",
    liveProcess: "Live process",
    dropDocs: "Drop PDFs or images",
    pdfConverted: "PDF pages are converted to JPG before upload.",
    uploadAndProcess: "Upload and process",
    pipelineSnapshot: "Pipeline snapshot",
    nowRunning: "Now running",
    agentIdle: "Agent idle",
    knownStages: "known stages completed.",
    timeline: "Timeline",
    agentStages: "Agent stages",
    recentLog: "Recent log",
    historyFallback: "History fallback",
    noProgress: "No progress events yet.",
    pendingContext: "Pending context",
    missingInformation: "Missing information",
    reviewAssistant: "Review assistant",
    davReady: "DAV ready",
    moreDocsNeeded: "More documents needed",
    needsAttention: "Needs attention",
    findMissing: "Find missing info",
    send: "Send",
    assistantPlaceholder: "Tell me the missing values, e.g. 78=23; 67=21/05/2026, or answer naturally.",
    you: "You",
    system: "System",
    assistantIntro: "Upload documents and I will identify missing DAV information, explain where to find it, and fill fields when you answer.",
    pendingFields: "field(s)",
    noPending: "No pending DAV questions.",
    noConflicts: "No conflicts detected.",
    noReviewFields: "No soft review fields.",
    noInduced: "No induced fields yet.",
    missingFields: "Missing fields",
    completeDav: "DAV fields are complete.",
    backendTimeline: "Backend timeline",
    classifiedGroups: "classified group(s)",
    noBackendHistory: "No backend history yet.",
    noDocuments: "No classified documents yet.",
    documentPages: "Document pages",
    preview: "Preview",
    download: "Download",
    close: "Close",
    noDocumentPages: "No document pages to show yet.",
    extracting: "Extracting document pages",
    extractionComplete: "Extraction complete",
    extractionFailed: "Extraction failed",
    extractionStale: "Extraction stalled",
    waitingExtraction: "Waiting for extraction",
    stageQueued: "Waiting for this stage",
    uploadStage: "Upload",
    classifyStage: "Classify",
    extractStage: "Extract",
    harmonizeStage: "Harmonize",
    autofillStage: "Autofill",
    davReviewStage: "DAV Review",
    readyStage: "Ready",
  },
} satisfies Record<Lang, Record<string, string>>;

const workflowSteps = [
  { id: "upload", label: "Upload", icon: FileUp },
  { id: "classify", label: "Classify", icon: FileSearch },
  { id: "extract", label: "Extract", icon: ScanLine },
  { id: "review", label: "Review DAV", icon: ClipboardList },
  { id: "complete", label: "Complete", icon: ShieldCheck },
];

const tabs: Array<{ id: TabId; label: string; icon: LucideIcon }> = [
  { id: "process", label: "Process", icon: UploadCloud },
  { id: "progress", label: "Agent Flow", icon: Activity },
  { id: "assistant", label: "Assistant", icon: MessageSquare },
  { id: "dav", label: "DAV Mirror", icon: ClipboardList },
  { id: "history", label: "History", icon: History },
];

const progressStages: Array<{ id: string; label: string; icon: LucideIcon }> = [
  { id: "upload", label: "Upload", icon: UploadCloud },
  { id: "classify", label: "Classify", icon: FileSearch },
  { id: "extract", label: "Extract", icon: ScanLine },
  { id: "harmonize", label: "Harmonize", icon: ClipboardList },
  { id: "autofill", label: "Autofill", icon: Sparkles },
  { id: "dav_chat", label: "DAV Review", icon: Bot },
  { id: "complete", label: "Ready", icon: ShieldCheck },
];

type AtFieldKind = "text" | "select" | "date" | "money" | "number" | "textarea" | "derived";
type AtField = {
  code?: string;
  label: string;
  kind?: AtFieldKind;
  suffix?: string;
  span?: 1 | 2;
  placeholder?: string;
  value?: (state: ProcessState, fieldMap: Map<string, [string, DavValue]>) => DavValue;
};
type AtSection = {
  letter: string;
  title: string;
  fields: AtField[];
};
type AtTab = {
  id: string;
  title: string;
  sections: AtSection[];
};

const AT_DAV_TABS: AtTab[] = [
  {
    id: "geral",
    title: "Geral",
    sections: [
      {
        letter: "A",
        title: "Identificação da declaração",
        fields: [
          { code: "01", label: "Alfândega da criação", kind: "select", span: 2 },
          { code: "01a", label: "Alfândega da versão atual", kind: "select", span: 2 },
          { code: "02", label: "Estatuto do Sujeito Passivo", kind: "select", span: 2 },
          { label: "Ano / Número DAV", kind: "derived", value: (state) => `${davYear(state)} / ${davNumber(state)}` },
          { label: "Data de Aceitação", kind: "date", value: (state) => davAcceptedDate(state) },
          { label: "Versão / Revisão DAV", kind: "derived", value: (state) => `${davVersion(state)} / ${davRevision(state)}` },
          { code: "05", label: "Regime de ISV", kind: "select", span: 2 },
          { label: "Número de Referência", placeholder: "" },
          { label: "Data Notificação Liq. Oficiosa", kind: "date", placeholder: "" },
          { label: "Liquidação Oficiosa", kind: "select", placeholder: "---" },
        ],
      },
    ],
  },
  {
    id: "operador",
    title: "Operador",
    sections: [
      {
        letter: "B",
        title: "Adquirente/Proprietário",
        fields: [
          { code: "06", label: "Tipo de Identificação", kind: "select" },
          { code: "06a", label: "Número Identificação" },
        ],
      },
      {
        letter: "C",
        title: "Declarante/Representante",
        fields: [
          { code: "14", label: "Qualidade representação", kind: "select" },
          { code: "15", label: "Tipo de Identificação Representante", kind: "select" },
          { code: "15a", label: "Número Identificação Representante" },
          { code: "16", label: "NIF (Sociedade HD)" },
          { code: "17", label: "Tipo de Identificação Declarante", kind: "select" },
          { code: "17a", label: "Número Identificação Declarante" },
          { code: "18", label: "Nome / Denominação Social", span: 2 },
        ],
      },
    ],
  },
  {
    id: "veiculo",
    title: "Veículo",
    sections: [
      {
        letter: "E",
        title: "Características do Veículo",
        fields: [
          { code: "30", label: "Código de Homologação" },
          { code: "31", label: "Categoria de Veículo", kind: "select" },
          { code: "32", label: "Tipo de Veículo IMT", kind: "select" },
          { code: "33", label: "Tipo de Veículo Fiscal", kind: "select" },
          { code: "34", label: "Código/Designação Marca" },
          { code: "35", label: "Modelo do Veículo" },
          { code: "36", label: "Variante" },
          { code: "36a", label: "Versão" },
          { label: "Designação Comercial", value: (_state, fields) => valueForCode(fields, "35") },
          { code: "37", label: "Peso Bruto", suffix: "kg", kind: "number" },
          { code: "38", label: "Tara", suffix: "kg", kind: "number" },
          { code: "39", label: "Combustível", kind: "select" },
          { code: "40", label: "Cor", kind: "select" },
          { code: "41", label: "Tipo Caixa", kind: "select" },
          { code: "42", label: "Nº Quadro (Chassis)" },
          { code: "43", label: "Nº Motor" },
          { code: "44", label: "Nº Lugares", kind: "number" },
          { code: "45", label: "Cilindrada", suffix: "cm³", kind: "number" },
          { code: "46", label: "Nº Eixos Motores", kind: "select" },
          { code: "47", label: "Comprimento Caixa", suffix: "mm", kind: "number" },
          { code: "48", label: "Altura mínima da caixa", suffix: "mm", kind: "number" },
          { code: "49", label: "Antepara Inamovível da Caixa", kind: "select" },
          { code: "49a", label: "Tipo de testes CO2", kind: "select" },
          { code: "50", label: "Emissão Gases CO2", suffix: "g/km", kind: "number" },
          { code: "51", label: "Emissão Partículas", suffix: "g/km", kind: "number" },
          { code: "52", label: "Autonomia da Bateria", kind: "select" },
          { code: "53", label: "Caixa de Velocidades", kind: "select" },
        ],
      },
      {
        letter: "F",
        title: "Apresentação do Veículo",
        fields: [
          { code: "55", label: "Veículo Novo/Usado", kind: "select" },
          { code: "56", label: "País Procedência", kind: "select" },
          { code: "57", label: "Num. Quilómetros à data DAV", kind: "number" },
          { code: "58", label: "Valor Comercial", kind: "money", suffix: "€" },
          { label: "PVP no ano da 1ª Matrícula", kind: "money", suffix: "€", placeholder: "" },
        ],
      },
      {
        letter: "G",
        title: "Matrículas Anteriores",
        fields: [
          { code: "60", label: "Data Primeira Matrícula", kind: "date" },
          { code: "61", label: "Nº de Matrícula Definitiva" },
          { code: "62", label: "Data de Atribuição da Matrícula Definitiva", kind: "date" },
          { code: "63", label: "Nº de Matrícula Provisória" },
          { code: "64", label: "Data de Atribuição da Matrícula Provisória", kind: "date" },
          { code: "65", label: "Data de Fim Validade", kind: "date" },
        ],
      },
      {
        letter: "G1",
        title: "Informação para IUC - Imposto Único de Circulação",
        fields: [
          { label: "Categoria A/B do IUC", kind: "textarea", span: 2, value: () => "As casas 65a e 65b são de preenchimento facultativo. Quando aplicável, confirme a data/país da primeira matrícula." },
          { label: "65a. Data da primeira matrícula UE/EEE", kind: "date", value: (_state, fields) => valueForCode(fields, "60") },
          { label: "65b. País da 1ª matrícula UE/EEE", kind: "select", value: (_state, fields) => valueForCode(fields, "56") },
          { label: "Categoria D do IUC", kind: "select", placeholder: "---" },
        ],
      },
      {
        letter: "H",
        title: "Entrada em Território Nacional",
        fields: [
          { code: "66", label: "Data de Entrada", kind: "date" },
          { code: "66a", label: "Tipo de Entrada", kind: "select" },
          { code: "67", label: "Termo Prazo de Apresentação da DAV", kind: "date" },
          { code: "68", label: "Número declaração de importação" },
          { code: "69", label: "Tipo de declaração de importação", kind: "select" },
          { code: "70", label: "País entrada livre prática na UE", kind: "select" },
        ],
      },
    ],
  },
  {
    id: "outros",
    title: "Outros",
    sections: [
      {
        letter: "J",
        title: "Base Tributável do IVA",
        fields: [
          { code: "75", label: "Data Transmissão", kind: "date" },
          { code: "76", label: "Nº Quilómetros à data da transmissão", suffix: "KM", kind: "number" },
          { code: "77", label: "Valor Aquisição", suffix: "€", kind: "money" },
          { code: "78", label: "Taxa de IVA", suffix: "%", kind: "number" },
          { code: "79", label: "Código Isenção", kind: "select" },
          { code: "80", label: "Operação não tributável", kind: "select" },
        ],
      },
      {
        letter: "L",
        title: "Modo de Pagamento",
        fields: [
          { code: "84", label: "Modo Pagamento", kind: "select" },
          { code: "85", label: "Garantia (Tipo / Ano / Número)", kind: "select" },
          { label: "Titular da Garantia", kind: "select", placeholder: "---" },
          { code: "86", label: "Fundamento legal" },
        ],
      },
      {
        letter: "M",
        title: "Instituto Mobilidade dos Transportes",
        fields: [
          { code: "89", label: "Serviço emissor", kind: "select" },
          { code: "90", label: "Número da Matrícula" },
          { code: "91", label: "Data", kind: "date" },
        ],
      },
      {
        letter: "N",
        title: "Observações",
        fields: [
          { label: "Observações", kind: "textarea", span: 2, placeholder: "" },
        ],
      },
    ],
  },
  {
    id: "dados-complementares",
    title: "Dados Complementares",
    sections: [
      {
        letter: "A",
        title: "Identificação do vendedor constante na fatura / declaração de venda",
        fields: [
          { code: "DC01", label: "Denominação Social/Nome" },
          { code: "DC02", label: "Sede/Domicílio" },
          { code: "DC02a", label: "País Sede/Domicílio", kind: "select" },
          { code: "DC03", label: "Qualidade", kind: "select" },
          { code: "DC04", label: "Identificação Fiscal" },
          { code: "DC04a", label: "País Identificação Fiscal", kind: "select" },
        ],
      },
      {
        letter: "B",
        title: "Identificação do comprador constante na fatura / declaração de venda",
        fields: [
          { code: "DC05", label: "Denominação Social/Nome" },
          { code: "DC06", label: "Sede/Domicílio" },
          { code: "DC07", label: "Qualidade", kind: "select" },
          { code: "DC08", label: "Identificação Fiscal" },
        ],
      },
      {
        letter: "C",
        title: "Enquadramento para efeitos de IVA do comprador",
        fields: [
          { code: "DC09", label: "Enquadramento a que o comprador está sujeito para efeitos de IVA", kind: "select", span: 2 },
        ],
      },
      {
        letter: "D",
        title: "Outros elementos da fatura",
        fields: [
          { code: "DC10", label: "Número da fatura" },
          { code: "DC11", label: "Data da fatura", kind: "date" },
          { code: "DC12", label: "Regime utilizado", kind: "select", span: 2 },
          { code: "DC13", label: "Preço", suffix: "€", kind: "money" },
          { code: "DC14", label: "Sigla da moeda", kind: "select" },
        ],
      },
      {
        letter: "E",
        title: "Meio de pagamento utilizado na aquisição do veículo",
        fields: [
          { code: "DC15", label: "Meio de Pagamento", kind: "select", span: 2 },
        ],
      },
      {
        letter: "F",
        title: "Intermediários na transação",
        fields: [
          { code: "DC16", label: "Existem intermediários na transação?", kind: "select" },
          { code: "DC17", label: "Denominação Social/Nome" },
          { code: "DC18", label: "Sede/Domicílio" },
          { code: "DC19", label: "Qualidade", kind: "select" },
          { code: "DC20", label: "Identificação fiscal" },
        ],
      },
      {
        letter: "G",
        title: "Meio de transporte utilizado",
        fields: [
          { code: "DC21", label: "Meio de transporte utilizado para transportar o veículo até Portugal", kind: "select", span: 2 },
        ],
      },
      {
        letter: "H",
        title: "Empresa transportadora",
        fields: [
          { code: "DC22", label: "Denominação Social/Nome" },
          { code: "DC23", label: "Sede/Domicílio" },
          { code: "DC24", label: "Identificação fiscal" },
        ],
      },
      {
        letter: "I",
        title: "Data de entrada do veículo em território nacional",
        fields: [
          { code: "DC25", label: "Data de entrada do veículo em território nacional", kind: "date" },
        ],
      },
      {
        letter: "J",
        title: "Forma como teve conhecimento do negócio",
        fields: [
          { code: "DC26", label: "Forma como teve conhecimento", kind: "select" },
          { code: "DC27", label: "Site de internet" },
        ],
      },
    ],
  },
];

const AT_DAV_CODES = new Set(
  AT_DAV_TABS.flatMap((tab) => tab.sections.flatMap((section) => section.fields.map((field) => field.code).filter(Boolean))) as string[],
);

const POLLING_ACTIONS: BusyAction[] = ["upload", "classify", "extract", "chat", "noop", "decision"];
const UPLOAD_CONCURRENCY = 3;

function App({ authEnabled = false, userName = null, onLogout }: AppProps) {
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem("car-legalizer-lang") === "en" ? "en" : "pt"));
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [processId, setProcessId] = useState("");
  const [manualProcessId, setManualProcessId] = useState("");
  const [processes, setProcesses] = useState<ProcessSummary[]>([]);
  const [state, setState] = useState<ProcessState | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("process");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploads, setUploads] = useState<UploadProgress[]>([]);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [notice, setNotice] = useState<string>("");
  const [answer, setAnswer] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [documents, setDocuments] = useState<ProcessDocument[]>([]);
  const [previewPage, setPreviewPage] = useState<{ document: ProcessDocument; page: DocumentPage } | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const processIdRef = useRef(processId);
  const pollTimerRef = useRef<number | null>(null);
  const lastUiMessageRef = useRef("");
  const autoReviewRequestedRef = useRef<string | null>(null);
  const t = STRINGS[lang];

  const metrics = useMemo(() => (state ? stateMetrics(state) : null), [state]);
  const uiOut = state?.flags?.ui_out;
  const activeStep = state ? stepForState(state) : "upload";
  const missingFields = useMemo(
    () => Object.entries(state?.dados_carro || {}).filter(([fieldKey, value]) => !isNotApplicable(state?.flags?.dav_field_meta?.[fieldKey]) && isMissing(value)),
    [state],
  );
  const induced = useMemo(() => (state ? inducedEntries(state) : []), [state]);
  const conflictFields = useMemo(
    () => Object.entries(state?.flags?.dav_field_meta || {}).filter(([, meta]) => meta.status === "conflict" && !isNotApplicable(meta)),
    [state],
  );
  const reviewFields = useMemo(
    () => Object.entries(state?.flags?.dav_field_meta || {}).filter(([, meta]) => meta.status === "needs_review" && !isNotApplicable(meta)),
    [state],
  );
  const extractJobActive = state ? isExtractJobActive(state) : false;
  const effectiveBusy: BusyAction = busy || (extractJobActive ? "extract" : null);

  useEffect(() => {
    healthCheck().then((online) => {
      setApiOnline(online);
      if (online) {
        void refreshProcessList(true);
      }
    });
  }, []);

  useEffect(() => {
    localStorage.setItem("car-legalizer-lang", lang);
  }, [lang]);

  useEffect(() => {
    processIdRef.current = processId;
  }, [processId]);

  useEffect(() => {
    if (!state || !extractJobActive) {
      return undefined;
    }
    startPolling();
    return () => stopPolling();
  }, [state, extractJobActive, processId]);

  useEffect(() => {
    if (!state || isExtractJobActive(state)) {
      return;
    }
    const job = state.flags?.extract_job;
    const key = `${state.process_id}:${job?.finished_at || job?.status || state.fase_atual}`;
    if (job?.status === "done" && state.fase_atual === "DAV_FLOW" && autoReviewRequestedRef.current !== key) {
      autoReviewRequestedRef.current = key;
      setActiveTab("assistant");
      void askForMissingFields();
    }
  }, [state]);

  useEffect(() => {
    const messageParts = [uiOut?.message, uiOut?.assistant_message].filter(Boolean) as string[];
    if (!messageParts.length) {
      return;
    }
    const text = messageParts.join("\n\n");
    const key = `${state?.process_id || "none"}:${uiOut?.type || "info"}:${text}`;
    if (lastUiMessageRef.current === key) {
      return;
    }
    lastUiMessageRef.current = key;
    setChatMessages((current) => [
      ...current,
      {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        text,
        ts: new Date().toISOString(),
        applied: uiOut?.applied,
      },
    ]);
  }, [state?.process_id, uiOut?.message, uiOut?.assistant_message, uiOut?.type]);

  useEffect(() => {
    return () => stopPolling();
  }, []);

  async function refreshProcessList(silent = false) {
    setBusy((current) => current || "processes");
    if (!silent) {
      setNotice("");
    }
    try {
      const response = await listProcesses();
      setProcesses(response.processes);
      setApiOnline(true);
    } catch (error) {
      setApiOnline(false);
      if (!silent) {
        setNotice(error instanceof Error ? error.message : "Could not list saved processes");
      }
    } finally {
      setBusy((current) => (current === "processes" ? null : current));
    }
  }

  async function pollProcessOnce(silent = true) {
    const trimmed = processIdRef.current.trim();
    if (!trimmed) {
      return;
    }

    try {
      const liveState = await getProcess(trimmed);
      setState(liveState);
      setApiOnline(true);
    } catch (error) {
      setApiOnline(false);
      if (!silent) {
        setNotice(error instanceof Error ? error.message : "Backend polling failed");
      }
    }
  }

  function startPolling() {
    stopPolling();
    void pollProcessOnce(true);
    pollTimerRef.current = window.setInterval(() => {
      void pollProcessOnce(true);
    }, 1500);
  }

  function stopPolling() {
    if (pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }

  async function runLive<T>(action: BusyAction, task: () => Promise<T>): Promise<T | undefined> {
    const shouldPoll = action !== null && POLLING_ACTIONS.includes(action);
    setBusy(action);
    setNotice("");
    if (shouldPoll) {
      startPolling();
    }

    try {
      return await task();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Unexpected error");
      return undefined;
    } finally {
      if (shouldPoll) {
        stopPolling();
        await pollProcessOnce(true);
      }
      setBusy(null);
    }
  }

  async function refreshProcess() {
    const result = await runLive("refresh", async () => getProcess(processId.trim()));
    if (result) {
      setState(result);
      setApiOnline(true);
    }
  }

  async function loadProcess(id = processId.trim()) {
    const trimmed = id.trim();
    if (!trimmed) {
      setNotice("Add a process id first.");
      return;
    }
    const result = await runLive("load", async () => getProcess(trimmed));
    if (result) {
      setProcessId(result.process_id);
      setManualProcessId(result.process_id);
      setState(result);
      await refreshDocuments(result.process_id);
      setApiOnline(true);
      setActiveTab(nextTabForState(result));
      setChatMessages([{
        id: `system-${Date.now()}`,
        role: "system",
        text: lang === "pt" ? `Processo ${result.process_id} aberto.` : `Process ${result.process_id} opened.`,
        ts: new Date().toISOString(),
      }]);
    }
  }

  async function createNewProcess() {
    const id = makeProcessId();
    setProcessId(id);
    setManualProcessId(id);
    await loadProcess(id);
  }

  async function openManualProcess() {
    const id = manualProcessId.trim();
    if (!id) {
      setNotice("Add a process id first.");
      return;
    }
    setProcessId(id);
    await loadProcess(id);
  }

  async function sendEvent(event: Record<string, unknown>, action: BusyAction) {
    if (action === "classify" || action === "extract" || action === "pipeline") {
      setActiveTab("progress");
    }
    const result = await runLive(action, async () => postEvent(processId.trim(), event));
    if (result?.state) {
      setState(result.state);
      setApiOnline(true);
    }
    return result?.state;
  }

  async function runAgentPipeline() {
    if (!state) {
      return;
    }
    setActiveTab("progress");
    setBusy("pipeline");
    try {
      const hasDocs = Object.keys(state.docs || {}).length > 0;
      if (!hasDocs || state.fase_atual === "INTAKE_DOCS") {
        const classified = await postEvent(processId.trim(), { type: "classify_docs" });
        if (classified?.state) {
          setState(classified.state);
        }
      }

      const extracting = await postEvent(processId.trim(), { type: "start_extract" });
      if (extracting?.state) {
        setState(extracting.state);
      }

      const finished = await waitForExtractToFinish();
      if (finished) {
        setState(finished);
        if (finished.flags?.extract_job?.status === "done") {
          const reviewed = await postEvent(processId.trim(), { type: "noop" });
          if (reviewed?.state) {
            setState(reviewed.state);
          }
          setActiveTab("assistant");
        }
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Agent pipeline failed");
    } finally {
      setBusy(null);
      await pollProcessOnce(true);
    }
  }

  async function refreshDocuments(id = processId.trim()) {
    if (!id) {
      return;
    }
    try {
      const response = await listProcessDocuments(id);
      setDocuments(response.documents);
    } catch {
      setDocuments([]);
    }
  }

  async function waitForExtractToFinish(): Promise<ProcessState | undefined> {
    for (let index = 0; index < 240; index += 1) {
      const liveState = await getProcess(processIdRef.current.trim());
      setState(liveState);
      const status = liveState.flags?.extract_job?.status;
      if (status !== "queued" && status !== "running") {
        return liveState;
      }
      await delay(1500);
    }
    setNotice("Extraction is still running. The Agent Flow tab will keep updating.");
    return undefined;
  }

  async function uploadSelectedFiles() {
    if (!selectedFiles.length) {
      setNotice("Choose PDF or image documents first.");
      return;
    }

    await runLive("upload", async () => {
      const initial = selectedFiles.map((file) => ({
        id: `${file.name}-${file.size}`,
        filename: file.name,
        sourceName: file.name,
        status: "splitting" as const,
      }));
      setUploads(initial);

      const pages = await splitFilesForUpload(selectedFiles);
      setUploads(
        pages.map((page) => ({
          id: `${page.sourceName}-${page.pageNumber}-${page.filename}`,
          filename: page.filename,
          sourceName: page.sourceName,
          status: "queued",
        })),
      );

      async function uploadPage(page: (typeof pages)[number]) {
        const id = `${page.sourceName}-${page.pageNumber}-${page.filename}`;
        setUploads((current) =>
          current.map((item) => (item.id === id ? { ...item, status: "uploading" } : item)),
        );

        try {
          const file = new File([page.blob], page.filename, { type: "image/jpeg" });
          const result = await postEvent(processId.trim(), { type: "upload_doc" }, file);
          if (result?.state) {
            setState(result.state);
          }

          setUploads((current) =>
            current.map((item) => (item.id === id ? { ...item, status: "done" } : item)),
          );
        } catch (error) {
          setUploads((current) =>
            current.map((item) =>
              item.id === id
                ? { ...item, status: "error", message: error instanceof Error ? error.message : "Upload failed" }
                : item,
            ),
          );
          throw error;
        }
      }

      let nextPageIndex = 0;
      async function uploadWorker() {
        while (nextPageIndex < pages.length) {
          const page = pages[nextPageIndex];
          nextPageIndex += 1;
          await uploadPage(page);
        }
      }

      const workerCount = Math.min(UPLOAD_CONCURRENCY, pages.length);
      await Promise.all(Array.from({ length: workerCount }, uploadWorker));
      setSelectedFiles([]);
    });

    await refreshDocuments();
    await runAgentPipeline();
  }

  async function askForMissingFields() {
    setActiveTab("assistant");
    await sendEvent({ type: "noop" }, "noop");
  }

  async function sendAnswer() {
    const message = answer.trim();
    if (!message) {
      return;
    }
    setChatMessages((current) => [
      ...current,
      { id: `user-${Date.now()}`, role: "user", text: message, ts: new Date().toISOString() },
    ]);
    setAnswer("");
    setActiveTab("assistant");
    await sendEvent({ type: "dav_user_message", data: { message } }, "chat");
  }

  async function sendDecisionAnswer(decision: DavDecision, option: DavDecisionOption) {
    setActiveTab("assistant");
    setChatMessages((current) => [
      ...current,
      {
        id: `user-decision-${Date.now()}`,
        role: "user",
        text: `${decision.message}\n${option.label}`,
        ts: new Date().toISOString(),
      },
    ]);
    await sendEvent(
      {
        type: "dav_decision_answer",
        data: {
          decision_id: decision.id,
          field: decision.field,
          value: option.value,
          field_updates: option.field_updates,
        },
      },
      "decision",
    );
  }

  function handleFiles(files: FileList | null) {
    if (!files) {
      return;
    }
    setSelectedFiles(Array.from(files));
    setUploads([]);
    setNotice("");
  }

  function closeProcess() {
    stopPolling();
    setState(null);
    setProcessId("");
    setManualProcessId("");
    setSelectedFiles([]);
    setUploads([]);
    setDocuments([]);
    setPreviewPage(null);
    setChatMessages([]);
    setActiveTab("process");
    void refreshProcessList(true);
  }

  if (!state || !metrics) {
    return (
      <ProcessHub
        apiOnline={apiOnline}
        busy={busy}
        manualProcessId={manualProcessId}
        notice={notice}
        processes={processes}
        onManualProcessId={setManualProcessId}
        onNewProcess={createNewProcess}
        onOpenManual={openManualProcess}
        onOpenProcess={loadProcess}
        onRefresh={() => refreshProcessList(false)}
        lang={lang}
        onToggleLang={() => setLang((current) => (current === "pt" ? "en" : "pt"))}
        authEnabled={authEnabled}
        userName={userName}
        onLogout={onLogout}
        t={t}
      />
    );
  }

  return (
    <main className="app-shell">
      <aside className="workflow-rail" aria-label="Workflow">
        <div className="brand-block">
          <div className="brand-mark">
            <ShieldCheck size={24} aria-hidden="true" />
          </div>
          <div>
            <p className="eyebrow">DAV Console</p>
            <h1>Car Legalizer</h1>
          </div>
        </div>

        <nav className="step-list">
          {workflowSteps.map((step, index) => {
            const Icon = step.icon;
            const status = workflowStatus(step.id, activeStep, index);
            return (
              <div className={`step-item ${status}`} key={step.id}>
                <span className="step-icon">
                  <Icon size={17} aria-hidden="true" />
                </span>
                <span>{workflowStepLabel(step.id, t)}</span>
              </div>
            );
          })}
        </nav>

        <div className="rail-footer">
          <span className={`connection-dot ${apiOnline ? "online" : apiOnline === false ? "offline" : ""}`} />
          <span>{apiOnline ? t.apiOnline : apiOnline === false ? t.apiOffline : t.checkingApi}</span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Process</p>
            <div className="process-row">
              <strong className="process-chip">{processId}</strong>
              <button
                className="icon-button"
                type="button"
                onClick={refreshProcess}
                disabled={busy !== null}
                title="Refresh process"
              >
                {busy === "refresh" ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
              </button>
            </div>
          </div>

          <div className="top-actions" role="group" aria-label="Process actions">
            <button className="secondary-button" type="button" onClick={closeProcess} disabled={busy !== null}>
              <FolderOpen size={17} />
              {t.processes}
            </button>
            <button className="secondary-button lang-button" type="button" onClick={() => setLang((current) => (current === "pt" ? "en" : "pt"))}>
              <Languages size={17} />
              <span className={lang === "pt" ? "active-lang" : ""}>PT</span>
              <span aria-hidden="true">/</span>
              <span className={lang === "en" ? "active-lang" : ""}>EN</span>
            </button>
            {authEnabled ? (
              <button className="secondary-button" type="button" onClick={onLogout}>
                <ShieldCheck size={17} />
                {userName || "Conta"}
              </button>
            ) : null}
            <button className="primary-button" type="button" onClick={runAgentPipeline} disabled={busy !== null && !isExtractJobStale(state)}>
              {busy === "pipeline" ? <Loader2 className="spin" size={17} /> : <Activity size={17} />}
              {isExtractJobStale(state) ? t.resumeExtract : t.continueProcessing}
            </button>
          </div>
        </header>

        {notice ? (
          <div className="notice" role="status">
            <Info size={17} aria-hidden="true" />
            <span>{notice}</span>
          </div>
        ) : null}

        <FeatureStrip metrics={metrics} uiType={uiOut?.type} busy={effectiveBusy} extractJob={state.flags?.extract_job} t={t} />

        <TabNav activeTab={activeTab} onTab={setActiveTab} busy={effectiveBusy} t={t} />

        <section className="tab-surface">
          {activeTab === "process" ? (
            <IntakeTab
              files={selectedFiles}
              uploads={uploads}
              busy={effectiveBusy}
              state={state}
              documents={documents}
              onFiles={handleFiles}
              onPickFiles={() => fileInputRef.current?.click()}
              onUpload={uploadSelectedFiles}
              onProcess={runAgentPipeline}
              onPreview={setPreviewPage}
              processId={processId}
              t={t}
              fileInputRef={fileInputRef}
            />
          ) : null}

          {activeTab === "progress" ? <AgentProgress state={state} busy={effectiveBusy} t={t} /> : null}

          {activeTab === "dav" ? <DavMirror state={state} /> : null}

          {activeTab === "assistant" ? (
            <AssistantPanel
              state={state}
              missingFields={missingFields}
              induced={induced}
              conflicts={conflictFields}
              reviewFields={reviewFields}
              messages={chatMessages}
              answer={answer}
              busy={effectiveBusy}
              t={t}
              onAskMissing={askForMissingFields}
              onAnswer={setAnswer}
              onDecision={sendDecisionAnswer}
              onSendAnswer={sendAnswer}
            />
          ) : null}

          {activeTab === "history" ? <HistoryPanel state={state} documents={documents} processId={processId} onPreview={setPreviewPage} t={t} /> : null}
        </section>
      </section>
      {previewPage ? (
        <DocumentPreviewModal
          processId={processId}
          preview={previewPage}
          onClose={() => setPreviewPage(null)}
          t={t}
        />
      ) : null}
    </main>
  );
}

type ProcessHubProps = {
  apiOnline: boolean | null;
  busy: BusyAction;
  lang: Lang;
  manualProcessId: string;
  notice: string;
  processes: ProcessSummary[];
  authEnabled: boolean;
  userName: string | null;
  t: typeof STRINGS[Lang];
  onManualProcessId: (value: string) => void;
  onNewProcess: () => void;
  onOpenManual: () => void;
  onOpenProcess: (processId: string) => void;
  onRefresh: () => void;
  onToggleLang: () => void;
  onLogout?: () => void;
};

function ProcessHub({
  apiOnline,
  busy,
  lang,
  manualProcessId,
  notice,
  processes,
  authEnabled,
  userName,
  t,
  onManualProcessId,
  onNewProcess,
  onOpenManual,
  onOpenProcess,
  onRefresh,
  onToggleLang,
  onLogout,
}: ProcessHubProps) {
  return (
    <main className="hub-shell">
      <section className="hub-panel">
        <div className="hub-header">
          <div className="brand-block">
            <div className="brand-mark">
              <ShieldCheck size={25} aria-hidden="true" />
            </div>
            <div>
              <p className="eyebrow">DAV Console</p>
              <h1>Car Legalizer</h1>
            </div>
          </div>
          <div className="rail-footer hub-status">
            <span className={`connection-dot ${apiOnline ? "online" : apiOnline === false ? "offline" : ""}`} />
            <span>{apiOnline ? t.apiOnline : apiOnline === false ? `${t.apiOffline}: ${API_BASE_URL}` : t.checkingApi}</span>
            <button className="secondary-button lang-button" type="button" onClick={onToggleLang}>
              <Languages size={17} />
              <span className={lang === "pt" ? "active-lang" : ""}>PT</span>
              <span aria-hidden="true">/</span>
              <span className={lang === "en" ? "active-lang" : ""}>EN</span>
            </button>
            {authEnabled ? (
              <button className="secondary-button" type="button" onClick={onLogout}>
                <ShieldCheck size={17} />
                {userName || "Conta"}
              </button>
            ) : null}
          </div>
        </div>

        {notice ? (
          <div className="notice" role="status">
            <Info size={17} aria-hidden="true" />
            <span>{notice}</span>
          </div>
        ) : null}

        <div className="hub-grid">
          <section className="tool-panel hub-start">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">{t.newProcess}</p>
                <h2>{t.startAutoId}</h2>
              </div>
              <Plus size={22} aria-hidden="true" />
            </div>
            <p className="assistant-message muted">
              {t.newProcessHelp}
            </p>
            <button className="primary-button full-width" type="button" onClick={onNewProcess} disabled={busy !== null || apiOnline === false}>
              {busy === "new" || busy === "load" ? <Loader2 className="spin" size={17} /> : <Plus size={17} />}
              {t.newProcess}
            </button>

            <div className="manual-open">
              <p className="eyebrow">{t.advanced}</p>
              <div className="process-row">
                <input
                  className="process-input"
                  value={manualProcessId}
                  onChange={(event) => onManualProcessId(event.target.value)}
                  placeholder={t.openById}
                  aria-label="Manual process id"
                />
                <button className="secondary-button" type="button" onClick={onOpenManual} disabled={busy !== null || apiOnline === false}>
                  <ChevronRight size={17} />
                  {t.open}
                </button>
              </div>
            </div>
          </section>

          <section className="tool-panel hub-processes">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">{t.savedProcesses}</p>
                <h2>{processes.length ? `${processes.length} Blob process(es)` : t.noSavedProcesses}</h2>
              </div>
              <button className="icon-button" type="button" onClick={onRefresh} disabled={busy !== null || apiOnline === false} title="Refresh processes">
                {busy === "processes" ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
              </button>
            </div>

            <div className="process-list">
              {processes.map((process) => (
                <button className="process-card" type="button" key={process.process_id} onClick={() => onOpenProcess(process.process_id)} disabled={busy !== null}>
                  <span className="process-card-title">
                    <FolderOpen size={17} aria-hidden="true" />
                    <strong>{process.process_id}</strong>
                  </span>
                  <span>{process.fase_atual}{process.sub_fase ? ` / ${process.sub_fase}` : ""}</span>
                  <small>
                    {process.docs_count} docs · {process.filled_fields}/{process.total_fields} fields · {process.conflict_fields} {t.conflicts.toLowerCase()}
                  </small>
                  <small>{process.last_modified ? formatDateTime(process.last_modified) : "No timestamp"}</small>
                </button>
              ))}
              {!processes.length ? (
                <div className="empty-processes">
                  <Search size={20} aria-hidden="true" />
                  <span>No `processes/*/state.json` entries found in the configured Blob container.</span>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}

type FeatureStripProps = {
  metrics: ReturnType<typeof stateMetrics>;
  uiType?: string;
  busy: BusyAction;
  extractJob?: ExtractJob;
  t: typeof STRINGS[Lang];
};

function FeatureStrip({ metrics, uiType, busy, extractJob, t }: FeatureStripProps) {
  const items = [
    { label: t.documents, value: metrics.docs, icon: FileSearch, tone: "blue" },
    { label: t.filled, value: `${metrics.filledFields}/${metrics.totalFields}`, icon: CheckCircle2, tone: "teal" },
    { label: t.induced, value: metrics.inducedFields, icon: Sparkles, tone: "teal" },
    { label: t.conflicts, value: metrics.conflictFields, icon: XCircle, tone: "red" },
    { label: t.review, value: metrics.reviewFields || metrics.missingFields, icon: AlertTriangle, tone: "amber" },
    { label: t.assistant, value: busy || (extractJob?.status ? `extract ${extractJob.status}` : uiType) || "idle", icon: Bot, tone: "blue" },
  ];

  return (
    <section className="feature-strip" aria-label="Process metrics">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <div className={`metric-tile ${item.tone}`} key={item.label}>
            <Icon size={18} aria-hidden="true" />
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        );
      })}
    </section>
  );
}

function TabNav({ activeTab, onTab, busy, t }: { activeTab: TabId; onTab: (tab: TabId) => void; busy: BusyAction; t: typeof STRINGS[Lang] }) {
  const labels: Record<TabId, string> = {
    process: t.process,
    progress: t.agentFlow,
    assistant: t.assistant,
    dav: t.davMirror,
    history: t.history,
  };
  return (
    <nav className="tab-nav" aria-label="Pipeline tabs">
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const active = activeTab === tab.id;
        const showRunning = tab.id === "progress" && busy !== null;
        return (
          <button className={active ? "tab-button active" : "tab-button"} type="button" onClick={() => onTab(tab.id)} key={tab.id}>
            <Icon size={17} aria-hidden="true" />
            <span>{labels[tab.id]}</span>
            {showRunning ? <span className="tab-live-dot" aria-label="Running" /> : null}
          </button>
        );
      })}
    </nav>
  );
}

type IntakeTabProps = {
  files: File[];
  uploads: UploadProgress[];
  busy: BusyAction;
  state: ProcessState;
  documents: ProcessDocument[];
  processId: string;
  t: typeof STRINGS[Lang];
  onFiles: (files: FileList | null) => void;
  onPickFiles: () => void;
  onUpload: () => void;
  onProcess: () => void;
  onPreview: (preview: { document: ProcessDocument; page: DocumentPage }) => void;
  fileInputRef: MutableRefObject<HTMLInputElement | null>;
};

function IntakeTab(props: IntakeTabProps) {
  return (
    <div className="tab-grid intake-grid">
      <UploadPanel {...props} />
      <div className="tab-grid">
        <CapabilityPanel state={props.state} t={props.t} />
        <DocumentsPanel
          documents={props.documents}
          processId={props.processId}
          onPreview={props.onPreview}
          t={props.t}
        />
      </div>
    </div>
  );
}

function CapabilityPanel({ state, t }: { state: ProcessState; t: typeof STRINGS[Lang] }) {
  const docs = Object.entries(state.docs || {});
  const progressCount = state.flags?.agent_progress?.length || 0;
  return (
    <section className="tool-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Capabilities</p>
          <h2>{t.pipelineSnapshot}</h2>
        </div>
        <Activity size={22} aria-hidden="true" />
      </div>

      <div className="capability-list">
        <CapabilityItem icon={FileSearch} title={t.classifyStage} detail={`${docs.length} document group(s) in state`} />
        <CapabilityItem icon={ScanLine} title={t.extractStage} detail={`${state.flags?.raw_page_insights?.length || 0} extracted page insight(s)`} />
        <CapabilityItem icon={Sparkles} title="Autofill induction" detail="Deterministic buyer/declarant, invoice and vehicle mirrors are marked" />
        <CapabilityItem icon={MessageSquare} title={t.assistant} detail={`${progressCount} progress event(s) available for review`} />
      </div>
    </section>
  );
}

function CapabilityItem({ icon: Icon, title, detail }: { icon: LucideIcon; title: string; detail: string }) {
  return (
    <div className="capability-item">
      <Icon size={18} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <span>{detail}</span>
      </div>
    </div>
  );
}

function UploadPanel({
  files,
  uploads,
  busy,
  onFiles,
  onPickFiles,
  onUpload,
  onProcess,
  fileInputRef,
  t,
}: IntakeTabProps) {
  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    onFiles(event.dataTransfer.files);
  }

  return (
    <section className="tool-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Intake</p>
          <h2>{t.uploadDocuments}</h2>
        </div>
        <span className="status-pill live">{t.liveProcess}</span>
      </div>

      <div
        className="drop-zone"
        onDragOver={(event) => event.preventDefault()}
        onDrop={onDrop}
        role="button"
        tabIndex={0}
        onClick={onPickFiles}
      >
        <UploadCloud size={28} aria-hidden="true" />
        <div>
          <strong>{files.length ? `${files.length} file(s) selected` : t.dropDocs}</strong>
          <span>{t.pdfConverted}</span>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,.webp"
          multiple
          onChange={(event) => onFiles(event.target.files)}
          hidden
        />
      </div>

      {files.length ? (
        <div className="file-list">
          {files.map((file) => (
            <span className="file-chip" key={`${file.name}-${file.size}`}>
              {file.name}
            </span>
          ))}
        </div>
      ) : null}

      {uploads.length ? (
        <div className="upload-list">
          {uploads.map((upload) => (
            <div className={`upload-row ${upload.status}`} key={upload.id}>
              <CircleDot size={15} aria-hidden="true" />
              <span>{upload.filename}</span>
              <strong>{upload.status}</strong>
            </div>
          ))}
        </div>
      ) : null}

      <div className="action-row">
        <button className="primary-button" type="button" onClick={onUpload} disabled={busy !== null}>
          {busy === "upload" ? <Loader2 className="spin" size={17} /> : <UploadCloud size={17} />}
          {t.uploadAndProcess}
        </button>
        <button className="secondary-button" type="button" onClick={onProcess} disabled={busy !== null}>
          {busy === "pipeline" ? <Loader2 className="spin" size={17} /> : <Activity size={17} />}
          {t.continueProcessing}
        </button>
      </div>
    </section>
  );
}

function DocumentsPanel({
  documents,
  processId,
  onPreview,
  t,
}: {
  documents: ProcessDocument[];
  processId: string;
  onPreview: (preview: { document: ProcessDocument; page: DocumentPage }) => void;
  t: typeof STRINGS[Lang];
}) {
  return (
    <section className="tool-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{t.documents}</p>
          <h2>{t.documentPages}</h2>
        </div>
        <FileText size={22} aria-hidden="true" />
      </div>
      <div className="document-list">
        {documents.map((document) => (
          <div className="document-card" key={document.doc_id}>
            <div className="document-card-head">
              <div>
                <strong>{document.filename}</strong>
                <span>{document.category} / {document.status}</span>
              </div>
              <small>{document.pages.length} page(s)</small>
            </div>
            <div className="document-pages">
              {document.pages.map((page) => (
                <div className="document-page-row" key={page.blob_path}>
                  <span>{page.filename}</span>
                  <button className="icon-button" type="button" onClick={() => onPreview({ document, page })} title={t.preview}>
                    <Eye size={17} />
                  </button>
                  <a className="icon-button" href={documentFileUrl(processId, page.blob_path)} target="_blank" rel="noreferrer" title={t.download}>
                    <Download size={17} />
                  </a>
                </div>
              ))}
            </div>
          </div>
        ))}
        {!documents.length ? <p className="empty-note">{t.noDocumentPages}</p> : null}
      </div>
    </section>
  );
}

function DocumentPreviewModal({
  processId,
  preview,
  onClose,
  t,
}: {
  processId: string;
  preview: { document: ProcessDocument; page: DocumentPage };
  onClose: () => void;
  t: typeof STRINGS[Lang];
}) {
  const url = documentFileUrl(processId, preview.page.blob_path);
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t.preview}>
      <section className="document-modal">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{preview.document.category}</p>
            <h2>{preview.page.filename}</h2>
          </div>
          <div className="top-actions">
            <a className="secondary-button" href={url} target="_blank" rel="noreferrer">
              <Download size={17} />
              {t.download}
            </a>
            <button className="icon-button" type="button" onClick={onClose} title={t.close}>
              <X size={18} />
            </button>
          </div>
        </div>
        <div className="document-preview-frame">
          <img src={url} alt={preview.page.filename} />
        </div>
      </section>
    </div>
  );
}

function AgentProgress({ state, busy, t }: { state: ProcessState; busy: BusyAction; t: typeof STRINGS[Lang] }) {
  const entries = state.flags?.agent_progress || [];
  const extractJob = state.flags?.extract_job;
  const extractRunning = isExtractJobActive(state);
  const latestByStage = useMemo(() => {
    const map = new Map<string, AgentProgressEntry>();
    entries.forEach((entry) => map.set(entry.stage, entry));
    return map;
  }, [entries]);
  const running = extractRunning
    ? {
        message: extractJobMessage(extractJob, t),
        detail: {
          pages_done: extractJob?.pages_done ?? 0,
          pages_total: extractJob?.pages_total ?? 0,
        },
      }
    : [...entries].reverse().find((entry) => latestByStage.get(entry.stage)?.id === entry.id && entry.status === "running");
  const completed = progressStages.filter((stage) => {
    if (stage.id === "extract" && extractJob?.status) {
      return extractJob.status === "done";
    }
    const entry = latestByStage.get(stage.id);
    return entry?.status === "done" || entry?.status === "warning";
  }).length;
  const percent = Math.round((completed / progressStages.length) * 100);
  const fallbackLogs = !entries.length ? state.historico || [] : [];

  return (
    <div className="tab-grid progress-grid">
      <section className="tool-panel now-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t.nowRunning}</p>
            <h2>{running?.message || (busy ? `${busy} in progress` : t.agentIdle)}</h2>
          </div>
          {running || busy ? <Loader2 className="spin" size={22} aria-hidden="true" /> : <CheckCircle2 size={22} aria-hidden="true" />}
        </div>
        <div className="progress-meter" aria-label={`${percent}% complete`}>
          <span style={{ width: `${percent}%` }} />
        </div>
        <p className="meter-note">{completed} / {progressStages.length} {t.knownStages}</p>
        {running?.detail ? <DetailBlock detail={running.detail} /> : null}
      </section>

      <section className="tool-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Timeline</p>
            <h2>{t.agentStages}</h2>
          </div>
          <Clock3 size={22} aria-hidden="true" />
        </div>
        <div className="stage-timeline">
          {progressStages.map((stage) => {
            const Icon = stage.icon;
            const entry = latestByStage.get(stage.id);
            const status = stage.id === "extract" && extractJob?.status
              ? extractJobStageStatus(extractJob)
              : entry?.status || "queued";
            const message = stage.id === "extract" && extractJob?.status
              ? extractJobMessage(extractJob, t)
              : entry?.message || t.stageQueued;
            return (
              <div className={`stage-row ${status}`} key={stage.id}>
                <details className="stage-help">
                  <summary className="stage-icon" aria-label={stageLabel(stage.id, t)}>
                    <Icon size={17} aria-hidden="true" />
                  </summary>
                  <div className="stage-popover">
                    <strong>{stageLabel(stage.id, t)}</strong>
                    <span>{stageDescription(stage.id, t)}</span>
                    <small>{status} / {message}</small>
                    {entry?.detail ? <DetailBlock detail={entry.detail} /> : null}
                  </div>
                </details>
                <div>
                  <strong>{stageLabel(stage.id, t)}</strong>
                  <span>{message}</span>
                </div>
                <ProgressIcon status={status} />
              </div>
            );
          })}
        </div>
      </section>

      <section className="tool-panel log-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Recent log</p>
            <h2>{entries.length ? `${entries.length} events` : t.historyFallback}</h2>
          </div>
          <Activity size={22} aria-hidden="true" />
        </div>
        <div className="event-log">
          {entries.length
            ? [...entries].reverse().slice(0, 18).map((entry) => <ProgressLogItem entry={entry} key={entry.id} />)
            : fallbackLogs.slice().reverse().map((message, index) => (
                <div className="log-item" key={`${message}-${index}`}>
                  <span className="log-time">history</span>
                  <strong>{message}</strong>
                </div>
              ))}
          {!entries.length && !fallbackLogs.length ? <p className="empty-note">{t.noProgress}</p> : null}
        </div>
      </section>
    </div>
  );
}

function ProgressIcon({ status }: { status: string }) {
  if (status === "running") {
    return <Loader2 className="spin stage-status running" size={17} aria-hidden="true" />;
  }
  if (status === "done") {
    return <CheckCircle2 className="stage-status done" size={17} aria-hidden="true" />;
  }
  if (status === "warning" || status === "stale") {
    return <AlertTriangle className="stage-status warning" size={17} aria-hidden="true" />;
  }
  if (status === "error") {
    return <XCircle className="stage-status error" size={17} aria-hidden="true" />;
  }
  return <CircleDot className="stage-status queued" size={16} aria-hidden="true" />;
}

function ProgressLogItem({ entry }: { entry: AgentProgressEntry }) {
  return (
    <div className={`log-item ${entry.status}`}>
      <span className="log-time">{formatTime(entry.ts)}</span>
      <strong>{entry.message}</strong>
      <small>{entry.stage} / {entry.status}</small>
    </div>
  );
}

function DetailBlock({ detail }: { detail: Record<string, unknown> }) {
  return (
    <div className="detail-block">
      {Object.entries(detail).slice(0, 6).map(([key, value]) => (
        <span key={key}>
          <strong>{key}</strong>
          {Array.isArray(value) ? value.length : String(value)}
        </span>
      ))}
    </div>
  );
}

function DavMirror({ state }: { state: ProcessState }) {
  const [activeAtTab, setActiveAtTab] = useState(AT_DAV_TABS[0].id);
  const fieldMap = useMemo(() => buildDavFieldMap(state.dados_carro), [state.dados_carro]);
  const activeTabConfig = AT_DAV_TABS.find((tab) => tab.id === activeAtTab) || AT_DAV_TABS[0];
  const extraFields = orphanFields(state.dados_carro).filter(([fieldKey]) => !AT_DAV_CODES.has(codeOf(fieldKey)));

  return (
    <section className="dav-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">AT mirror</p>
          <h2>Declaração Aduaneira de Veículos</h2>
        </div>
        <span className="status-pill">{state.fase_atual}</span>
      </div>

      <AtDavShell
        activeTab={activeTabConfig}
        fieldMap={fieldMap}
        state={state}
        onTab={setActiveAtTab}
      />

      {extraFields.length ? (
        <section className="at-orphans">
          <h3>Outros campos</h3>
          <div className="at-orphan-grid">
            {extraFields.map(([fieldKey, value]) => (
              <DavField
                key={fieldKey}
                fieldKey={fieldKey}
                value={value}
                meta={state.flags?.dav_field_meta?.[fieldKey]}
              />
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}

function AtDavShell({
  activeTab,
  fieldMap,
  state,
  onTab,
}: {
  activeTab: AtTab;
  fieldMap: Map<string, [string, DavValue]>;
  state: ProcessState;
  onTab: (tabId: string) => void;
}) {
  return (
    <div className="at-dav-shell">
      <div className="at-title">Declaração Aduaneira de Veículos</div>
      <div className="at-meta-strip">
        <span><strong>Estância DAV:</strong> {displayOrPlaceholder(valueForCode(fieldMap, "01") || "PT000750")}</span>
        <span><strong>Data Aceitação:</strong> {displayOrPlaceholder(davAcceptedDate(state))}</span>
        <span><strong>Ano DAV:</strong> {davYear(state)}</span>
        <span><strong>Número DAV:</strong> {davNumber(state)}</span>
        <span><strong>Versão DAV:</strong> {davVersion(state)}</span>
        <span><strong>Revisão DAV:</strong> {davRevision(state)}</span>
        <span><strong>Data:</strong> {davCurrentDate(state)}</span>
      </div>

      <AtDavTabs activeTabId={activeTab.id} onTab={onTab} />

      <div className="at-page">
        {activeTab.sections.map((section) => (
          <AtDavSection
            fieldMap={fieldMap}
            key={`${activeTab.id}-${section.letter}`}
            section={section}
            state={state}
          />
        ))}
      </div>
    </div>
  );
}

function AtDavTabs({ activeTabId, onTab }: { activeTabId: string; onTab: (tabId: string) => void }) {
  return (
    <div className="at-tabbar" role="tablist" aria-label="Separadores AT DAV">
      {AT_DAV_TABS.map((tab) => (
        <button
          aria-selected={tab.id === activeTabId}
          className={tab.id === activeTabId ? "active" : ""}
          key={tab.id}
          onClick={() => onTab(tab.id)}
          role="tab"
          type="button"
        >
          {tab.title}
        </button>
      ))}
    </div>
  );
}

function AtDavSection({
  fieldMap,
  section,
  state,
}: {
  fieldMap: Map<string, [string, DavValue]>;
  section: AtSection;
  state: ProcessState;
}) {
  return (
    <section className="at-section">
      <div className="at-section-title">
        <span className="at-letter">{section.letter}</span>
        <strong>{section.title}</strong>
      </div>
      <div className="at-fields">
        {section.fields.map((field, index) => (
          <AtDavField
            field={field}
            fieldMap={fieldMap}
            key={`${section.letter}-${field.code || field.label}-${index}`}
            state={state}
          />
        ))}
      </div>
    </section>
  );
}

function AtDavField({
  field,
  fieldMap,
  state,
}: {
  field: AtField;
  fieldMap: Map<string, [string, DavValue]>;
  state: ProcessState;
}) {
  const fieldEntry = field.code ? fieldMap.get(field.code) : undefined;
  const fieldKey = fieldEntry?.[0];
  const value = field.value ? field.value(state, fieldMap) : fieldEntry?.[1];
  const meta = fieldKey ? state.flags?.dav_field_meta?.[fieldKey] : undefined;
  const notApplicable = isNotApplicable(meta);
  const missing = !notApplicable && (isMissing(value) || meta?.status === "missing");
  const status = atFieldStatus(meta, missing);
  const badge = atFieldBadge(meta, missing);
  const kind = field.kind || "text";
  const displayValue = missing ? "" : String(value ?? "");

  return (
    <div
      className={`at-field span-${field.span || 1} ${status ? `at-${status}` : ""}`}
      title={meta?.reason || undefined}
    >
      <div className="at-label">
        <span>{field.code ? `${field.code}. ` : ""}{field.label}:</span>
        {badge ? <small className={`at-badge ${status}`}>{badge}</small> : null}
        {meta?.reason ? (
          <details className="at-meta-detail">
            <summary aria-label="Detalhe do campo">i</summary>
            <span>{meta.reason}</span>
          </details>
        ) : null}
      </div>
      <AtFieldValue
        kind={kind}
        suffix={field.suffix}
        value={displayValue}
        placeholder={field.placeholder}
      />
    </div>
  );
}

function AtFieldValue({
  kind,
  placeholder,
  suffix,
  value,
}: {
  kind: AtFieldKind;
  placeholder?: string;
  suffix?: string;
  value: string;
}) {
  const normalized = value || placeholder || "";
  if (kind === "date") {
    const parts = splitDateParts(normalized);
    return (
      <div className="at-date-value" aria-label={normalized || "sem valor"}>
        <span>{parts[0]}</span>
        <b>-</b>
        <span>{parts[1]}</span>
        <b>-</b>
        <span>{parts[2]}</span>
      </div>
    );
  }

  if (kind === "textarea") {
    return <div className="at-value at-textarea">{normalized}</div>;
  }

  return (
    <div className={`at-value ${kind === "select" ? "select-like" : ""}`}>
      <span>{normalized}</span>
      {kind === "select" ? <ChevronRight size={12} aria-hidden="true" /> : null}
      {suffix ? <em>{suffix}</em> : null}
    </div>
  );
}

function DavField({ fieldKey, value, meta }: { fieldKey: string; value: DavValue; meta?: DavFieldMeta }) {
  const notApplicable = isNotApplicable(meta);
  const missing = !notApplicable && (isMissing(value) || meta?.status === "missing");
  const induced = meta?.origin === "induced";
  const conflict = meta?.status === "conflict";
  const review = meta?.status === "needs_review";
  const badge = notApplicable ? "Not applicable" : conflict ? "Conflict" : review ? "Review" : induced ? "Induced" : missing ? "Missing" : "";
  const id = `field-${codeOf(fieldKey).replace(/[^a-z0-9]/gi, "-")}`;

  return (
    <label className={`field-row ${missing ? "missing" : ""} ${induced ? "induced" : ""} ${conflict ? "conflict" : ""} ${review ? "review" : ""} ${notApplicable ? "not-applicable" : ""}`} htmlFor={id}>
      <span className="field-label">
        <strong>{codeOf(fieldKey)}</strong>
        <span>{labelOf(fieldKey)}</span>
        {badge ? (
          <span className={`field-badge ${notApplicable ? "not-applicable" : conflict ? "conflict" : review ? "review" : induced ? "induced" : "missing"}`} title={meta?.reason || "Field status"}>
            {badge}
          </span>
        ) : null}
      </span>
      <input id={id} value={missing ? "" : String(value)} placeholder="Missing" readOnly />
      {meta?.reason ? <span className="field-reason">{meta.reason}</span> : null}
      {meta?.alternatives?.length ? (
        <details className="field-details">
          <summary>Alternatives</summary>
          {meta.alternatives.slice(0, 4).map((alternative, index) => (
            <span key={`${fieldKey}-${index}`}>
              {String(alternative.value ?? alternative.key ?? "candidate")}
              {alternative.selected ? " (selected)" : ""}
            </span>
          ))}
        </details>
      ) : null}
    </label>
  );
}

type AssistantPanelProps = {
  state: ProcessState;
  missingFields: [string, DavValue][];
  induced: [string, DavFieldMeta][];
  conflicts: [string, DavFieldMeta][];
  reviewFields: [string, DavFieldMeta][];
  messages: ChatMessage[];
  answer: string;
  busy: BusyAction;
  onAskMissing: () => void;
  onAnswer: (value: string) => void;
  onDecision: (decision: DavDecision, option: DavDecisionOption) => void;
  onSendAnswer: () => void;
  t: typeof STRINGS[Lang];
};

function AssistantPanel({
  state,
  missingFields,
  induced,
  conflicts,
  reviewFields,
  messages,
  answer,
  busy,
  onAskMissing,
  onAnswer,
  onDecision,
  onSendAnswer,
  t,
}: AssistantPanelProps) {
  const uiOut = state.flags?.ui_out;
  const uiFields = uiOut?.fields || [];
  const decisions = uiOut?.decisions || [];

  return (
    <div className="assistant-layout">
      <section className="tool-panel assistant-chat-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Assistant</p>
            <h2>{assistantTitle(uiOut?.type, t)}</h2>
          </div>
          <Bot size={22} aria-hidden="true" />
        </div>

        {decisions.length ? (
          <DecisionCards decisions={decisions} busy={busy} onDecision={onDecision} />
        ) : null}

        <div className="chat-thread" aria-label="Assistant conversation">
          {messages.length ? messages.map((message) => (
            <div className={`chat-message ${message.role}`} key={message.id}>
              <span>{message.role === "user" ? t.you : message.role === "system" ? t.system : t.assistant}</span>
              <p>{message.text}</p>
              {message.applied?.length ? <small>{message.applied.length} field update(s) applied</small> : null}
            </div>
          )) : (
            <div className="chat-message assistant">
              <span>{t.assistant}</span>
              <p>{t.assistantIntro}</p>
            </div>
          )}
        </div>

        <div className="chat-box">
          <textarea
            value={answer}
            onChange={(event) => onAnswer(event.target.value)}
            placeholder={t.assistantPlaceholder}
            rows={4}
          />
          <div className="chat-actions">
            <button className="secondary-button" type="button" onClick={onAskMissing} disabled={busy !== null}>
              {busy === "noop" ? <Loader2 className="spin" size={17} /> : <RefreshCw size={17} />}
              {t.findMissing}
            </button>
            <button className="primary-button" type="button" onClick={onSendAnswer} disabled={busy !== null || !answer.trim()}>
              {busy === "chat" ? <Loader2 className="spin" size={17} /> : <Send size={17} />}
              {t.send}
            </button>
          </div>
        </div>
      </section>

      <section className="assistant-context">
        <section className="tool-panel compact">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{t.pendingContext}</p>
              <h2>{uiFields.length || missingFields.length} {t.pendingFields}</h2>
            </div>
            <ClipboardList size={22} aria-hidden="true" />
          </div>
          <div className="question-list">
            {uiFields.length
              ? uiFields.map((field, index) => (
                  <QuestionItem
                    field={field}
                    meta={metaForPrompt(state, field)}
                    key={`${fieldKeyFromPrompt(field)}-${index}`}
                  />
                ))
              : missingFields.slice(0, 12).map(([fieldKey]) => (
                  <QuestionItem field={fieldKey} meta={state.flags?.dav_field_meta?.[fieldKey]} key={fieldKey} />
                ))}
            {!uiFields.length && !missingFields.length ? <p className="empty-note">{t.noPending}</p> : null}
          </div>
        </section>

        <section className="review-grid assistant-review-grid">
          <ReviewList title={t.conflicts} count={conflicts.length} icon={XCircle} items={conflicts} empty={t.noConflicts} tone="conflict" />
          <ReviewList title={t.review} count={reviewFields.length} icon={AlertTriangle} items={reviewFields} empty={t.noReviewFields} tone="review" />
          <ReviewList title={t.induced} count={induced.length} icon={Sparkles} items={induced} empty={t.noInduced} tone="induced" />
          <MissingList missingFields={missingFields} t={t} />
        </section>
      </section>
    </div>
  );
}

function DecisionCards({
  busy,
  decisions,
  onDecision,
}: {
  busy: BusyAction;
  decisions: DavDecision[];
  onDecision: (decision: DavDecision, option: DavDecisionOption) => void;
}) {
  return (
    <div className="decision-stack" aria-label="DAV decisions">
      {decisions.map((decision) => (
        <article className={`decision-card ${decision.kind}`} key={decision.id}>
          <div className="decision-card-head">
            <span>Decisão</span>
            <strong>{decision.label}</strong>
          </div>
          <h3>{decision.message}</h3>
          {decision.reason ? <p>{decision.reason}</p> : null}
          {decision.impact ? <small>{decision.impact}</small> : null}
          <div className="decision-options">
            {decision.options.map((option, index) => (
              <button
                className="decision-option"
                disabled={busy !== null}
                key={`${decision.id}-${index}-${String(option.value ?? option.label)}`}
                onClick={() => onDecision(decision, option)}
                type="button"
              >
                <span>{option.label}</span>
                {option.description ? <small>{option.description}</small> : null}
              </button>
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}

function ReviewList({
  title,
  count,
  icon: Icon,
  items,
  empty,
  tone,
}: {
  title: string;
  count: number;
  icon: LucideIcon;
  items: [string, DavFieldMeta][];
  empty: string;
  tone: string;
}) {
  return (
    <section className="tool-panel compact">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{title}</p>
          <h2>{count}</h2>
        </div>
        <Icon size={22} aria-hidden="true" />
      </div>
      <div className="review-list">
        {items.slice(0, 12).map(([fieldKey, meta]) => (
          <div className={`review-item ${tone}`} key={fieldKey}>
            <strong>{codeOf(fieldKey)}</strong>
            <span>{labelOf(fieldKey)}</span>
            <small>{meta.reason}</small>
          </div>
        ))}
        {!items.length ? <p className="empty-note">{empty}</p> : null}
      </div>
    </section>
  );
}

function MissingList({ missingFields, t }: { missingFields: [string, DavValue][]; t: typeof STRINGS[Lang] }) {
  return (
    <section className="tool-panel compact">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{t.missingFields}</p>
          <h2>{missingFields.length}</h2>
        </div>
        <AlertTriangle size={22} aria-hidden="true" />
      </div>
      <div className="review-list">
        {missingFields.slice(0, 16).map(([fieldKey]) => (
          <div className="review-item missing-mini" key={fieldKey}>
            <strong>{codeOf(fieldKey)}</strong>
            <span>{labelOf(fieldKey)}</span>
          </div>
        ))}
        {!missingFields.length ? <p className="empty-note">{t.completeDav}</p> : null}
      </div>
    </section>
  );
}

function HistoryPanel({
  state,
  documents,
  processId,
  onPreview,
  t,
}: {
  state: ProcessState;
  documents: ProcessDocument[];
  processId: string;
  onPreview: (preview: { document: ProcessDocument; page: DocumentPage }) => void;
  t: typeof STRINGS[Lang];
}) {
  const docs = Object.entries(state.docs || {});
  const rawCount = state.flags?.raw_page_insights?.length || 0;
  return (
    <div className="tab-grid history-grid">
      <section className="tool-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t.history}</p>
            <h2>{t.backendTimeline}</h2>
          </div>
          <History size={22} aria-hidden="true" />
        </div>
        <div className="history-list">
          {(state.historico || []).slice().reverse().map((item, index) => (
            <div className="history-item" key={`${item}-${index}`}>
              <span>{(state.historico || []).length - index}</span>
              <strong>{item}</strong>
            </div>
          ))}
          {!state.historico?.length ? <p className="empty-note">{t.noBackendHistory}</p> : null}
        </div>
      </section>

      <section className="tool-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t.documents}</p>
            <h2>{docs.length} {t.classifiedGroups}</h2>
          </div>
          <FileText size={22} aria-hidden="true" />
        </div>
        <div className="doc-list">
          {docs.map(([docId, doc]) => (
            <div className="doc-item" key={docId}>
              <strong>{String(doc.category || "OUTRO")}</strong>
              <span>{docId}</span>
              <small>{Array.isArray(doc.pages) ? `${doc.pages.length} page(s)` : "No pages"} / {String(doc.status || "pending")}</small>
            </div>
          ))}
          {!docs.length ? <p className="empty-note">{t.noDocuments}</p> : null}
        </div>
        <div className="raw-summary">
          <ScanLine size={18} aria-hidden="true" />
          <span>{rawCount} raw extraction insight(s)</span>
        </div>
      </section>

      <DocumentsPanel documents={documents} processId={processId} onPreview={onPreview} t={t} />
    </div>
  );
}

function QuestionItem({ field, meta }: { field: string | UiFieldPrompt; meta?: DavFieldMeta }) {
  if (typeof field === "string") {
    return (
      <div className={`question-item ${meta?.status || ""}`}>
        <strong>{codeOf(field)}</strong>
        <span>{labelOf(field)}</span>
        {meta?.reason ? <small>{meta.reason}</small> : null}
        {meta?.source_doc || meta?.source_page ? <small>{[meta.source_doc, meta.source_page].filter(Boolean).join(" / ")}</small> : null}
      </div>
    );
  }

  return (
    <div className={`question-item ${meta?.status || ""}`}>
      <strong>{field.field || "Field"}</strong>
      <span>{field.label || field.explain || "Pending"}</span>
      {field.where ? <small>{field.where}</small> : null}
      {meta?.reason ? <small>{meta.reason}</small> : null}
    </div>
  );
}

function fieldKeyFromPrompt(field: string | UiFieldPrompt): string {
  return typeof field === "string" ? field : field.field || field.label || "field";
}

function stepForState(state: ProcessState): string {
  const uiType = state.flags?.ui_out?.type;
  if (uiType === "dav_ready" || state.fase_atual === "DAV_DRAFT_READY") {
    return "complete";
  }
  if (state.fase_atual === "DAV_FLOW") {
    return "review";
  }
  if (state.fase_atual === "EXTRACT_VALIDATE") {
    return "extract";
  }
  const docs = Object.values(state.docs || {});
  if (docs.some((doc) => doc.status === "classified")) {
    return "classify";
  }
  return "upload";
}

function workflowStatus(stepId: string, activeStep: string, index: number): "done" | "active" | "pending" {
  const activeIndex = workflowSteps.findIndex((step) => step.id === activeStep);
  if (stepId === activeStep) {
    return "active";
  }
  if (index < activeIndex) {
    return "done";
  }
  return "pending";
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "now";
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function buildDavFieldMap(dadosCarro: Record<string, DavValue>): Map<string, [string, DavValue]> {
  const map = new Map<string, [string, DavValue]>();
  for (const entry of Object.entries(dadosCarro || {})) {
    map.set(codeOf(entry[0]), entry);
  }
  return map;
}

function valueForCode(fieldMap: Map<string, [string, DavValue]>, code: string): DavValue {
  return fieldMap.get(code)?.[1] ?? null;
}

function displayOrPlaceholder(value: DavValue, fallback = "---"): string {
  return isMissing(value) ? fallback : String(value);
}

function splitDateParts(value: string): [string, string, string] {
  const trimmed = value.trim();
  const iso = trimmed.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/);
  if (iso) {
    return [iso[1], iso[2].padStart(2, "0"), iso[3].padStart(2, "0")];
  }
  const pt = trimmed.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$/);
  if (pt) {
    return [pt[3], pt[2].padStart(2, "0"), pt[1].padStart(2, "0")];
  }
  return ["", "", ""];
}

function davYear(state: ProcessState): string {
  const accepted = davAcceptedDate(state) || davCurrentDate(state);
  return splitDateParts(accepted)[0] || new Date().getFullYear().toString();
}

function davAcceptedDate(state: ProcessState): string {
  const progressDate = state.flags?.agent_progress?.find((entry) => entry.stage === "upload")?.ts;
  return progressDate ? new Date(progressDate).toISOString().slice(0, 10) : "";
}

function davCurrentDate(state: ProcessState): string {
  const dates = [
    state.flags?.extract_job?.finished_at,
    state.flags?.extract_job?.started_at,
    state.flags?.agent_progress?.at(-1)?.ts,
  ].filter(Boolean);
  const date = dates[0] ? new Date(String(dates[0])) : new Date();
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().slice(0, 10);
}

function davNumber(state: ProcessState): string {
  const digits = state.process_id.replace(/\D/g, "");
  return digits ? digits.slice(-8).padStart(8, "0") : "--------";
}

function davVersion(state: ProcessState): string {
  return state.flags?.extract_job?.status === "done" ? "2" : "1";
}

function davRevision(state: ProcessState): string {
  const reviewCount = (state.flags?.agent_progress || []).filter((entry) => entry.stage === "dav_chat").length;
  return String(Math.max(0, Math.min(reviewCount, 9)));
}

function atFieldStatus(meta: DavFieldMeta | undefined, missing: boolean): string {
  if (meta?.status === "not_applicable") {
    return "not-applicable";
  }
  if (meta?.status === "conflict") {
    return "conflict";
  }
  if (meta?.status === "needs_review") {
    return "review";
  }
  if (meta?.origin === "induced") {
    return "induced";
  }
  if (missing) {
    return "missing";
  }
  return "";
}

function atFieldBadge(meta: DavFieldMeta | undefined, missing: boolean): string {
  if (meta?.status === "not_applicable") {
    return "não aplicável";
  }
  if (meta?.status === "conflict") {
    return "conflito";
  }
  if (meta?.status === "needs_review") {
    return "rever";
  }
  if (meta?.origin === "induced") {
    return "induzido";
  }
  if (missing) {
    return "em falta";
  }
  return "";
}

function isExtractJobActive(state: ProcessState): boolean {
  const status = state.flags?.extract_job?.status;
  return status === "queued" || status === "running";
}

function isExtractJobStale(state: ProcessState): boolean {
  const job = state.flags?.extract_job;
  return job?.status === "stale" || job?.stale === true;
}

function extractJobStageStatus(job?: ExtractJob): string {
  if (!job?.status) {
    return "queued";
  }
  if (job.status === "queued" || job.status === "running" || job.status === "done" || job.status === "warning" || job.status === "stale" || job.status === "error") {
    return job.status;
  }
  return "queued";
}

function extractJobMessage(job: ExtractJob | undefined, t: typeof STRINGS[Lang]): string {
  if (!job?.status) {
    return t.waitingExtraction;
  }

  const done = job.pages_done ?? 0;
  const total = job.pages_total ?? 0;
  const pages = total ? `${done}/${total}` : String(done);

  if (job.status === "running" || job.status === "queued") {
    return `${t.extracting} (${pages})`;
  }
  if (job.status === "done") {
    return `${t.extractionComplete} (${pages})`;
  }
  if (job.status === "stale") {
    return `${t.extractionStale} (${pages})`;
  }
  if (job.status === "warning") {
    return job.error ? `${job.error} (${pages})` : `${t.extractionStale} (${pages})`;
  }
  if (job.status === "error") {
    return job.error ? `${t.extractionFailed}: ${job.error}` : t.extractionFailed;
  }
  return `Extraction ${job.status}`;
}

function stageLabel(stageId: string, t: typeof STRINGS[Lang]): string {
  const labels: Record<string, string> = {
    upload: t.uploadStage,
    classify: t.classifyStage,
    extract: t.extractStage,
    harmonize: t.harmonizeStage,
    autofill: t.autofillStage,
    dav_chat: t.davReviewStage,
    complete: t.readyStage,
  };
  return labels[stageId] || stageId;
}

function workflowStepLabel(stepId: string, t: typeof STRINGS[Lang]): string {
  const labels: Record<string, string> = {
    upload: t.uploadStage,
    classify: t.classifyStage,
    extract: t.extractStage,
    review: t.davReviewStage,
    complete: t.readyStage,
  };
  return labels[stepId] || stepId;
}

function stageDescription(stageId: string, t: typeof STRINGS[Lang]): string {
  if (t === STRINGS.pt) {
    const descriptions: Record<string, string> = {
      upload: "Recebe PDFs/imagens e guarda páginas JPG na Blob.",
      classify: "Agrupa páginas e identifica o tipo de documento.",
      extract: "Lê cada página com visão e extrai evidências estruturadas.",
      harmonize: "Combina evidências de todas as páginas no espelho DAV.",
      autofill: "Preenche equivalências seguras, como comprador e declarante.",
      dav_chat: "Prepara perguntas para campos em falta, conflito ou revisão.",
      complete: "Marca o processo como pronto para validação final.",
    };
    return descriptions[stageId] || stageId;
  }
  const descriptions: Record<string, string> = {
    upload: "Receives PDFs/images and stores JPG pages in Blob.",
    classify: "Groups pages and identifies document type.",
    extract: "Reads each page with vision and extracts structured evidence.",
    harmonize: "Combines all page evidence into the DAV mirror.",
    autofill: "Fills safe deterministic equivalences, such as buyer and declarant.",
    dav_chat: "Prepares questions for missing, conflict, or review fields.",
    complete: "Marks the process ready for final validation.",
  };
  return descriptions[stageId] || stageId;
}

function makeProcessId(): string {
  const stamp = new Date()
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\..+/, "")
    .replace("T", "-");
  return `process-${stamp}`;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function nextTabForState(state: ProcessState): TabId {
  if (isExtractJobActive(state)) {
    return "progress";
  }
  if (state.fase_atual === "DAV_FLOW" || state.flags?.ui_out?.type === "dav_question") {
    return "assistant";
  }
  if (Object.keys(state.docs || {}).length || state.flags?.agent_progress?.length) {
    return "progress";
  }
  return "process";
}

function assistantTitle(type: string | undefined, t: typeof STRINGS[Lang]): string {
  if (type === "dav_question") {
    return t.missingInformation;
  }
  if (type === "dav_ready") {
    return t.davReady;
  }
  if (type === "request_upload") {
    return t.moreDocsNeeded;
  }
  if (type === "error") {
    return t.needsAttention;
  }
  return t.reviewAssistant;
}

function metaForPrompt(state: ProcessState, field: string | UiFieldPrompt): DavFieldMeta | undefined {
  const meta = state.flags?.dav_field_meta || {};
  if (typeof field === "string") {
    return meta[field];
  }
  if (field.field && meta[field.field]) {
    return meta[field.field];
  }
  if (!field.field) {
    return undefined;
  }
  return Object.entries(meta).find(([key]) => key.startsWith(`${field.field}:`))?.[1];
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default App;
