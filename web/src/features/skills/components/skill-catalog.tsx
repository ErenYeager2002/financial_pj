'use client';

import { useMemo, useState } from 'react';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { SkillDedication, SkillSummary } from '@/features/platform-api/types';
import {
  clearSkillCatalogFilters,
  DEFAULT_SKILL_CATALOG_FILTERS,
  filterAndSortSkillCatalog,
  hasSkillCatalogFilters,
  skillCatalogCategories,
  skillCatalogDedicationOptions,
  type SkillCatalogFilters
} from '../skill-catalog-state';
import { SkillCatalogCard } from './skill-catalog-card';
import { SkillCatalogToolbar } from './skill-catalog-toolbar';

interface SkillCatalogProps {
  skills: SkillSummary[];
  adminDedications?: Record<string, SkillDedication>;
}

export function SkillCatalog({ skills, adminDedications }: SkillCatalogProps) {
  const [filters, setFilters] = useState<SkillCatalogFilters>(DEFAULT_SKILL_CATALOG_FILTERS);
  const categories = useMemo(() => skillCatalogCategories(skills), [skills]);
  const dedicationOptions = useMemo(
    () => skillCatalogDedicationOptions(adminDedications),
    [adminDedications]
  );
  const visibleSkills = useMemo(
    () => filterAndSortSkillCatalog(skills, filters, adminDedications),
    [adminDedications, filters, skills]
  );

  if (skills.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>暂无可用 Skill</CardTitle>
          <CardDescription>当前账号还没有获得已发布 Skill 的使用权限。</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  function clearFilters() {
    setFilters(clearSkillCatalogFilters());
  }

  return (
    <section className='space-y-4' aria-labelledby='skill-catalog-title'>
      <h2 id='skill-catalog-title' className='sr-only'>
        Skill 目录
      </h2>
      <SkillCatalogToolbar
        filters={filters}
        categories={categories}
        dedicationOptions={dedicationOptions}
        onFiltersChange={setFilters}
        onClear={clearFilters}
      />

      <div className='flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground'>
        <span>共 {skills.length} 个 Skill</span>
        <span aria-live='polite'>当前显示 {visibleSkills.length} 个</span>
      </div>

      {visibleSkills.length === 0 ? (
        <div className='rounded-xl border border-dashed p-8 text-center'>
          <p className='text-sm text-muted-foreground'>没有符合条件的 Skill</p>
          {hasSkillCatalogFilters(filters) && (
            <button
              type='button'
              className='platform-action mt-3 text-sm text-primary underline-offset-4 hover:underline'
              onClick={clearFilters}
            >
              清除筛选
            </button>
          )}
        </div>
      ) : (
        <div className='platform-skill-grid'>
          {visibleSkills.map((skill) => (
            <SkillCatalogCard
              key={skill.id}
              skill={skill}
              dedication={adminDedications?.[skill.id]}
            />
          ))}
        </div>
      )}
    </section>
  );
}
