export type DataTableConfig = typeof dataTableConfig;

export const dataTableConfig = {
  textOperators: [
    { label: '包含', value: 'iLike' as const },
    { label: '不包含', value: 'notILike' as const },
    { label: '等于', value: 'eq' as const },
    { label: '不等于', value: 'ne' as const },
    { label: '为空', value: 'isEmpty' as const },
    { label: '不为空', value: 'isNotEmpty' as const }
  ],
  numericOperators: [
    { label: '等于', value: 'eq' as const },
    { label: '不等于', value: 'ne' as const },
    { label: '小于', value: 'lt' as const },
    { label: '小于或等于', value: 'lte' as const },
    { label: '大于', value: 'gt' as const },
    { label: '大于或等于', value: 'gte' as const },
    { label: '介于', value: 'isBetween' as const },
    { label: '为空', value: 'isEmpty' as const },
    { label: '不为空', value: 'isNotEmpty' as const }
  ],
  dateOperators: [
    { label: '等于', value: 'eq' as const },
    { label: '不等于', value: 'ne' as const },
    { label: '早于', value: 'lt' as const },
    { label: '晚于', value: 'gt' as const },
    { label: '早于或等于', value: 'lte' as const },
    { label: '晚于或等于', value: 'gte' as const },
    { label: '介于', value: 'isBetween' as const },
    { label: '相对于今天', value: 'isRelativeToToday' as const },
    { label: '为空', value: 'isEmpty' as const },
    { label: '不为空', value: 'isNotEmpty' as const }
  ],
  selectOperators: [
    { label: '等于', value: 'eq' as const },
    { label: '不等于', value: 'ne' as const },
    { label: '为空', value: 'isEmpty' as const },
    { label: '不为空', value: 'isNotEmpty' as const }
  ],
  multiSelectOperators: [
    { label: '包含任意一项', value: 'inArray' as const },
    { label: '不包含任何一项', value: 'notInArray' as const },
    { label: '为空', value: 'isEmpty' as const },
    { label: '不为空', value: 'isNotEmpty' as const }
  ],
  booleanOperators: [
    { label: '等于', value: 'eq' as const },
    { label: '不等于', value: 'ne' as const }
  ],
  sortOrders: [
    { label: '升序', value: 'asc' as const },
    { label: '降序', value: 'desc' as const }
  ],
  filterVariants: [
    'text',
    'number',
    'range',
    'date',
    'dateRange',
    'boolean',
    'select',
    'multiSelect'
  ] as const,
  operators: [
    'iLike',
    'notILike',
    'eq',
    'ne',
    'inArray',
    'notInArray',
    'isEmpty',
    'isNotEmpty',
    'lt',
    'lte',
    'gt',
    'gte',
    'isBetween',
    'isRelativeToToday'
  ] as const,
  joinOperators: ['and', 'or'] as const
};
