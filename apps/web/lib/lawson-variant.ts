export const lawsonVariantLabels = {
  LAWSON: 'ローソン（その他表記）',
  LAWSON_STORE_100: 'ローソンストア100',
  NATURAL_LAWSON: 'ナチュラルローソン',
  LAWSON_THREE_F: 'ローソン・スリーエフ',
  LAWSON_TOKS: 'LAWSON+toks',
} as const;

export type LawsonVariant = keyof typeof lawsonVariantLabels;

function compact(value: string): string {
  return value.normalize('NFKC').toLowerCase().replace(/[\s\u3000・･\-‐ー－!！+＋]/g, '');
}

const aliases: Array<[LawsonVariant, string[]]> = [
  ['LAWSON_STORE_100', ['ローソンストア100', 'LAWSON STORE 100']],
  ['NATURAL_LAWSON', ['ナチュラルローソン', 'NATURAL LAWSON']],
  ['LAWSON_THREE_F', ['ローソン・スリーエフ', 'LAWSON THREE-F']],
  ['LAWSON_TOKS', ['LAWSON+toks', 'LAWSON STATION+toks']],
];

/** Classifies the Lawson sub-brand visible at the beginning of an observed POI name. */
export function lawsonVariantFromName(name: string): LawsonVariant {
  const normalized = compact(name);
  for (const [variant, names] of aliases) {
    if (names.some(alias => normalized.startsWith(compact(alias)))) return variant;
  }
  return 'LAWSON';
}

export function emptyLawsonVariantCounts(): Record<LawsonVariant, number> {
  return { LAWSON: 0, LAWSON_STORE_100: 0, NATURAL_LAWSON: 0, LAWSON_THREE_F: 0, LAWSON_TOKS: 0 };
}

export function addLawsonVariantCount(counts: Record<LawsonVariant, number>, name: string, amount = 1): void {
  counts[lawsonVariantFromName(name)] += amount;
}
