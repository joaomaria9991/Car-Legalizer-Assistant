import type { DavFieldMeta, DavValue, ProcessState } from "./types";

export type DavSection = {
  id: string;
  title: string;
  codes: string[];
};

export const DAV_SECTIONS: DavSection[] = [
  {
    id: "identity",
    title: "Identificacao",
    codes: ["01", "01a", "02", "05", "06", "06a", "14", "15", "15a", "16", "17", "17a", "18"],
  },
  {
    id: "vehicle",
    title: "Veiculo",
    codes: [
      "30", "31", "32", "33", "34", "35", "36", "36a", "37", "38", "39", "40", "41",
      "42", "43", "44", "45", "46", "47", "48", "49", "49a", "50", "51", "52", "53",
      "55", "56", "57", "58",
    ],
  },
  {
    id: "registration",
    title: "Matriculas",
    codes: ["60", "61", "62", "63", "64", "65", "89", "90", "91"],
  },
  {
    id: "entry",
    title: "Entrada e importacao",
    codes: ["66", "66a", "67", "68", "69", "70", "DC21", "DC22", "DC23", "DC24", "DC25"],
  },
  {
    id: "transaction",
    title: "Transacao",
    codes: ["75", "76", "77", "78", "79", "80", "84", "85", "86", "DC10", "DC11", "DC12", "DC13", "DC14", "DC15"],
  },
  {
    id: "complementary",
    title: "Dados complementares",
    codes: [
      "DC01", "DC02", "DC02a", "DC03", "DC04", "DC04a", "DC05", "DC06", "DC07", "DC08",
      "DC09", "DC16", "DC17", "DC18", "DC19", "DC20", "DC26", "DC27",
    ],
  },
];

const SECTION_ORDER = new Map(
  DAV_SECTIONS.flatMap((section, sectionIndex) =>
    section.codes.map((code, fieldIndex) => [code, sectionIndex * 1000 + fieldIndex] as const),
  ),
);

export function codeOf(fieldKey: string): string {
  return fieldKey.split(":", 1)[0];
}

export function labelOf(fieldKey: string): string {
  return fieldKey.includes(":") ? fieldKey.split(":").slice(1).join(":") : fieldKey;
}

export function isMissing(value: DavValue | undefined): boolean {
  return value === null || value === undefined || (typeof value === "string" && value.trim() === "");
}

export function isNotApplicable(meta?: DavFieldMeta): boolean {
  return meta?.status === "not_applicable";
}

export function sortDavFields(fields: [string, DavValue][]): [string, DavValue][] {
  return [...fields].sort(([left], [right]) => {
    const leftCode = codeOf(left);
    const rightCode = codeOf(right);
    const leftOrder = SECTION_ORDER.get(leftCode) ?? 99999;
    const rightOrder = SECTION_ORDER.get(rightCode) ?? 99999;
    return leftOrder - rightOrder || leftCode.localeCompare(rightCode, undefined, { numeric: true });
  });
}

export function fieldsForSection(
  dadosCarro: Record<string, DavValue>,
  section: DavSection,
): [string, DavValue][] {
  const codes = new Set(section.codes);
  return sortDavFields(Object.entries(dadosCarro).filter(([key]) => codes.has(codeOf(key))));
}

export function orphanFields(dadosCarro: Record<string, DavValue>): [string, DavValue][] {
  const known = new Set(DAV_SECTIONS.flatMap((section) => section.codes));
  return sortDavFields(Object.entries(dadosCarro).filter(([key]) => !known.has(codeOf(key))));
}

export function stateMetrics(state: ProcessState) {
  const fields = Object.entries(state.dados_carro || {});
  const meta = state.flags?.dav_field_meta || {};
  const missing = fields.filter(([field, value]) => !isNotApplicable(meta[field]) && isMissing(value));
  const induced = Object.entries(state.flags?.dav_field_meta || {}).filter(([, meta]) => meta.origin === "induced");
  const conflicts = Object.entries(state.flags?.dav_field_meta || {}).filter(([, meta]) => meta.status === "conflict");
  const review = Object.entries(state.flags?.dav_field_meta || {}).filter(([, meta]) => meta.status === "needs_review");
  const notApplicable = Object.entries(state.flags?.dav_field_meta || {}).filter(([, meta]) => isNotApplicable(meta));
  const docs = Object.values(state.docs || {}).filter((doc) => Array.isArray(doc.pages));
  return {
    totalFields: fields.length,
    filledFields: fields.filter(([, value]) => !isMissing(value)).length,
    missingFields: missing.length,
    inducedFields: induced.length,
    conflictFields: conflicts.length,
    reviewFields: review.length,
    notApplicableFields: notApplicable.length,
    progressEntries: state.flags?.agent_progress?.length || 0,
    docs: docs.length,
  };
}

export function inducedEntries(state: ProcessState): Array<[string, DavFieldMeta]> {
  return Object.entries(state.flags?.dav_field_meta || {})
    .filter(([, meta]) => meta.origin === "induced")
    .sort(([left], [right]) => {
      const leftOrder = SECTION_ORDER.get(codeOf(left)) ?? 99999;
      const rightOrder = SECTION_ORDER.get(codeOf(right)) ?? 99999;
      return leftOrder - rightOrder;
    });
}
