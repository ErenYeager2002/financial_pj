"use client";

import { nativeSkillDisplay } from '@/features/skills/native-skill-display';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import type { SkillInstallCatalog, NativeSkillRead } from '@/features/platform-api/generated';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export function SkillInstallCatalogView() {
  const router = useRouter();
  const [catalog, setCatalog] = useState<SkillInstallCatalog | null>(null);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  async function request(path: string, body: object) {
    const response = await fetch(`/api/platform/admin/skill-sources/${path}`, {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '仓库请求失败');
    return data;
  }
  async function refresh() {
    setBusy('catalog'); setError(''); setMessage('');
    try {setCatalog(await request('install-catalog', {}) as SkillInstallCatalog);}
    catch (error) {setError(error instanceof Error ? error.message : '目录读取失败');}
    finally {setBusy('');}
  }
  async function prepare(sourcePath: string) {
    if (!catalog) return;
    setBusy(sourcePath); setError(''); setMessage('');
    try {
      const release = await request('prepare-install', {source_path: sourcePath, expected_commit: catalog.commit}) as NativeSkillRead;
      setMessage(`${nativeSkillDisplay(release.id, release.name).name} 已安装，可在 Skill 中心开始对话。`);
      setCatalog({...catalog, candidates: catalog.candidates.map(item => item.source_path === sourcePath ? {...item, state: "installed", reason: "已安装当前版本"} : item)});
      router.refresh();
    } catch (error) {setError(error instanceof Error ? error.message : '安装失败');}
    finally {setBusy('');}
  }
  const labels = {ready: '可安装', installed: '已安装', needs_adaptation: '说明文件无效', excluded: '不提供安装'};
  return <Card>
    <CardHeader><CardTitle>从 Gitee 安装 Skill</CardTitle><CardDescription>直接从 finance-skills/main 安装 SKILL.md、脚本和参考资料，无需额外安装清单。更新后已有会话继续使用原版本，新对话使用最新版本。</CardDescription></CardHeader>
    <CardContent className="space-y-3">
      <Button onClick={() => void refresh()} disabled={Boolean(busy)}>{busy === 'catalog' ? '读取仓库中…' : '读取安装目录'}</Button>
      {catalog && <p className="text-xs text-muted-foreground break-all">本次固定提交：{catalog.commit}</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {message && <p role="status" className="text-sm">{message}</p>}
      {catalog && <div className="max-h-[32rem] overflow-auto rounded-md border divide-y" aria-label="Gitee 可安装 Skill 目录">{catalog.candidates.map(item => { const display = nativeSkillDisplay(item.skill_id); return <div key={item.source_path} className="flex flex-wrap items-center justify-between gap-3 p-3">
        <div className="min-w-0"><p className="font-medium">{display.name}</p><p className="text-xs text-muted-foreground break-all">{item.skill_id} · {item.version}</p><p className="text-sm text-muted-foreground">{display.description}</p><p className="text-xs text-muted-foreground">{labels[item.state]} · {item.reason}</p></div>
        <Button variant="outline" disabled={Boolean(busy) || item.state !== 'ready'} onClick={() => void prepare(item.source_path)}>{busy === item.source_path ? '安装中…' : item.reason.includes('新版本') ? '更新' : '安装'}</Button>
      </div>; })}</div>}
    </CardContent>
  </Card>;
}
