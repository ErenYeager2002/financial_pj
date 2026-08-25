export type SupplementPrefix = 'AR' | 'SO';

export interface ParsedSupplementIdentifiers {
  values: string[];
  invalid: string[];
}

export interface HistoricalReferencePayment {
  historical_parent_only?: boolean | null;
}

export interface HistoricalReferenceArGroup {
  payments?: HistoricalReferencePayment[] | null;
}

export interface PartitionedFetchedArGroups<T> {
  current: T[];
  historicalReferences: T[];
}

export function parseSupplementIdentifiers(
  input: string,
  prefix: SupplementPrefix
): ParsedSupplementIdentifiers {
  const identifiers = [
    ...new Set(
      input
        .split(/[\s,，;；]+/)
        .map((item) => item.trim().toUpperCase())
        .filter(Boolean)
    )
  ];
  const pattern = new RegExp(`^${prefix}[A-Z0-9_-]{3,30}$`);
  return {
    values: identifiers.filter((identifier) => pattern.test(identifier)),
    invalid: identifiers.filter((identifier) => !pattern.test(identifier))
  };
}

export function lastPageOffset(total: number, pageSize: number): number {
  if (total <= 0 || pageSize <= 0) return 0;
  return Math.floor((total - 1) / pageSize) * pageSize;
}

export function partitionFetchedArGroups<T extends HistoricalReferenceArGroup>(
  groups: readonly T[] | null | undefined
): PartitionedFetchedArGroups<T> {
  const current: T[] = [];
  const historicalReferences: T[] = [];

  for (const group of groups ?? []) {
    const payments = group.payments ?? [];
    const isHistoricalReference =
      payments.length > 0 && payments.every((payment) => payment.historical_parent_only === true);
    (isHistoricalReference ? historicalReferences : current).push(group);
  }

  return { current, historicalReferences };
}
