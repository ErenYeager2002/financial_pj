import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import {
  hasSkillCatalogFilters,
  type SkillCatalogDedicationOption,
  type SkillCatalogFilters,
  type SkillRiskFilter
} from '../skill-catalog-state';

interface SkillCatalogToolbarProps {
  filters: SkillCatalogFilters;
  categories: string[];
  dedicationOptions: SkillCatalogDedicationOption[];
  onFiltersChange: (filters: SkillCatalogFilters) => void;
  onClear: () => void;
}

export function SkillCatalogToolbar({
  filters,
  categories,
  dedicationOptions,
  onFiltersChange,
  onClear
}: SkillCatalogToolbarProps) {
  const hasFilters = hasSkillCatalogFilters(filters);

  function update<K extends keyof SkillCatalogFilters>(key: K, value: SkillCatalogFilters[K]) {
    onFiltersChange({ ...filters, [key]: value });
  }

  return (
    <div className='rounded-xl border bg-card p-3'>
      <div className='platform-skill-toolbar'>
        <label className='relative min-w-0 flex-1'>
          <Icons.search
            aria-hidden='true'
            className='pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground'
          />
          <Input
            value={filters.query}
            onChange={(event) => update('query', event.target.value)}
            placeholder='搜索 Skill 名称、描述、标签或操作'
            aria-label='搜索 Skill 名称、描述、标签或操作'
            className='pl-9'
          />
        </label>

        <div className='flex flex-wrap items-center gap-2'>
          <label className='platform-control-target min-w-0 max-w-full'>
            <NativeSelect
              value={filters.category || 'all'}
              onChange={(event) =>
                update(
                  'category',
                  event.currentTarget.value === 'all' ? '' : event.currentTarget.value
                )
              }
              aria-label='按业务分类筛选'
            >
              <NativeSelectOption value='all'>全部分类</NativeSelectOption>
              {categories.map((category) => (
                <NativeSelectOption key={category} value={category}>
                  {category}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>

          <label className='platform-control-target min-w-0 max-w-full'>
            <NativeSelect
              value={filters.risk}
              onChange={(event) => update('risk', event.currentTarget.value as SkillRiskFilter)}
              aria-label='按风险类型筛选'
            >
              <NativeSelectOption value='all'>全部风险</NativeSelectOption>
              <NativeSelectOption value='read_only'>只读</NativeSelectOption>
              <NativeSelectOption value='write'>写入操作</NativeSelectOption>
              <NativeSelectOption value='external_action'>外部操作</NativeSelectOption>
            </NativeSelect>
          </label>

          {dedicationOptions.length > 0 && (
            <label className='platform-control-target min-w-0 max-w-full'>
              <NativeSelect
                value={filters.dedicationUserId || 'all'}
                onChange={(event) =>
                  update(
                    'dedicationUserId',
                    event.currentTarget.value === 'all' ? '' : event.currentTarget.value
                  )
                }
                aria-label='按专属人员筛选'
              >
                <NativeSelectOption value='all'>全部人员</NativeSelectOption>
                {dedicationOptions.map((option) => (
                  <NativeSelectOption key={option.userId} value={option.userId}>
                    {option.displayName}
                    {option.disabled ? '（已停用）' : ''}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </label>
          )}

          <Button
            type='button'
            variant={filters.popularOnly ? 'secondary' : 'outline'}
            aria-pressed={filters.popularOnly}
            onClick={() => update('popularOnly', !filters.popularOnly)}
          >
            <Icons.exclusive aria-hidden='true' />
            常用
          </Button>

          {hasFilters && (
            <Button type='button' variant='ghost' onClick={onClear}>
              清除筛选
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
