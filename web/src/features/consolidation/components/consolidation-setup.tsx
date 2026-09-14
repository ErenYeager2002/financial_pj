'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { createRun, uploadSkillFile } from '@/features/run-setup/api/service';
import { fetchRun } from '@/features/runs/api/service';
import { platformClientRequest } from '@/features/platform-api/client';
import type { RunDetail } from '@/features/platform-api/types';
import { createClientId } from '@/lib/client-id';

const companies = [
  ['HEAD','北京本部'],['CULTURE','北京文化传媒'],['SHANGHAI','上海智译'],
  ['SHANDONG','山东分公司'],['HUNAN_TECH','湖南科技'],['HUNAN_BRANCH','湖南分公司'],
  ['SICHUAN','四川分公司'],['JINAN','济南子公司']
];
type Material = { id: string; original_name: string };
type Output = { file_id: string; name: string };
type Result = {
  summary?: { complete?: boolean; coverage_complete?: boolean; report_count?: number; missing_report_count?: number };
  coverage?: Array<{ company: string; bs: string; is: string; cf: string }>;
  warnings?: string[];
  output_files?: Output[];
};
const terminal = new Set(['succeeded','failed','timed_out','cancelled']);
function previousMonth() {
  const date = new Date(); date.setDate(1); date.setMonth(date.getMonth()-1);
  return String(date.getFullYear())+'-'+String(date.getMonth()+1).padStart(2,'0');
}
function linkForFile(id: string) { return '/api/platform/files/'+encodeURIComponent(id)+'/download'; }

export function ConsolidationSetup() {
  const [month,setMonth]=useState(previousMonth);
  const [materials,setMaterials]=useState<Material[]>([]);
  const [fetchKingdee,setFetchKingdee]=useState(true);
  const [account,setAccount]=useState('');
  const [password,setPassword]=useState('');
  const [configured,setConfigured]=useState(false);
  const [busy,setBusy]=useState(false);
  const [runId,setRunId]=useState('');
  const [run,setRun]=useState<RunDetail|null>(null);
  const [parent,setParent]=useState('');
  const [error,setError]=useState('');
  const key=useRef(createClientId());
  const result=(run?.result ?? {}) as Result;
  const running=Boolean(runId && (!run || !terminal.has(run.state)));

  useEffect(()=>{
    setRunId(new URL(window.location.href).searchParams.get('run') ?? '');
    platformClientRequest<{configured:boolean}>('/api/platform/service-credentials/kingdee','账号状态读取失败')
      .then(v=>setConfigured(v.configured)).catch(()=>setConfigured(false));
  },[]);
  useEffect(()=>{
    if(!runId)return;
    let cancelled=false;
    const refresh=async()=>{
      try {
        const value=await fetchRun(runId);
        if(cancelled)return;
        if(value.skill_id!=='consolidated-statements')throw new Error('此任务不属于合并报表。');
        setRun(value);
      } catch(e) {
        if(!cancelled){setError(e instanceof Error?e.message:'任务状态读取失败');}
      }
    };
    void refresh();
    const timer=setInterval(()=>void refresh(),3000);
    return ()=>{cancelled=true;clearInterval(timer);};
  },[runId]);

  async function saveCredential() {
    if(!account.trim() || !password){toast.error('请填写金蝶账号和密码');return;}
    setBusy(true);
    try {
      await platformClientRequest('/api/platform/service-credentials/kingdee','账号保存失败',{
        method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({account,password})
      });
      setPassword('');setAccount('');setConfigured(true);toast.success('金蝶账号已加密保存');
    }catch(e){toast.error(e instanceof Error?e.message:'保存失败');}
    finally{setBusy(false);}
  }

  async function upload(selected: FileList|null) {
    if(!selected?.length)return;
    setBusy(true);setError('');
    try {
      for(const file of Array.from(selected)) {
        if(!/\.(xlsx|xls)$/i.test(file.name) || file.size>30*1024*1024)throw new Error('请上传30MB以内的xls或xlsx文件');
        const stored=await uploadSkillFile({skillId:'consolidated-statements',role:'reports',file});
        setMaterials(current=>current.some(x=>x.id===stored.id)?current:[...current,{id:stored.id,original_name:stored.name}]);
      }
    }catch(e){setError(e instanceof Error?e.message:'上传失败');}
    finally{setBusy(false);}
  }

  async function start() {
    if(!month || (!fetchKingdee && !materials.length)){setError('请选择月份，并上传报表或启用金蝶取数');return;}
    if(fetchKingdee && !configured){setError('请先保存金蝶账号，或关闭金蝶取数后使用上传文件');return;}
    setBusy(true);setError('');
    try {
      const task=await createRun({
        skill_id:'consolidated-statements',message:'',
        parameters:{period:month.replace('-',''),fetch_kingdee:fetchKingdee,...(parent?{parent_run_id:parent}:{})},
        files:{reports:materials.map(x=>x.id)},idempotency_key:key.current
      });
      setRun(task);setRunId(task.id);
      const url=new URL(window.location.href);url.searchParams.set('run',task.id);window.history.replaceState(null,'',url);
    }catch(e){setError(e instanceof Error?e.message:'创建任务失败');}
    finally{setBusy(false);}
  }

  async function supplement() {
    if(!run)return;
    setBusy(true);setError('');
    try {
      const bindings=run.files as Record<string,Array<{file_id:string;name:string}>>;
      const originals=(bindings.reports ?? []).map(x=>({id:x.file_id,original_name:x.name}));
      const fetched=(result.output_files ?? []).filter(x=>/_(资产负债表|利润表|现金流量表)__\d{6}期\.xlsx$/.test(x.name));
      for(const item of fetched) {
        const response=await fetch(linkForFile(item.file_id));
        if(!response.ok)throw new Error('原始取数文件读取失败，请保留当前版本后重新上传');
        const stored=await uploadSkillFile({skillId:'consolidated-statements',role:'reports',file:new File([await response.blob()],item.name)});
        originals.push({id:stored.id,original_name:stored.name});
      }
      const period=String(run.parameters?.period ?? month.replace('-',''));
      setMonth(period.slice(0,4)+'-'+period.slice(4));setParent(run.id);
      setMaterials(originals);setFetchKingdee(true);setRun(null);setRunId('');key.current=createClientId();
      const url=new URL(window.location.href);url.searchParams.delete('run');window.history.replaceState(null,'',url);
      toast.success('已复用原始资料，运行后只补取尚未成功识别的金蝶报表');
    }catch(e){setError(e instanceof Error?e.message:'准备补充版本失败');}
    finally{setBusy(false);}
  }

  return <div className='space-y-5'>
    <Card><CardHeader><CardTitle>按月生成合并报表</CardTitle></CardHeader><CardContent className='space-y-4'>
      <p className='text-sm text-muted-foreground'>采用北京本部字段。山东管理费用计入成本；不做抵销及其他人工调整。底稿包含合并、母公司各三张主表，明细金额为数值，合计和汇总金额使用公式；同时分别提供三张合并表、三张母公司表的独立文件。</p>
      <div className='flex flex-wrap items-end gap-5'>
        <div className='space-y-2'><Label htmlFor='report-month'>会计月份</Label><Input id='report-month' type='month' value={month} onChange={e=>setMonth(e.target.value)} disabled={busy||Boolean(runId)||Boolean(parent)} /></div>
        <label className='flex gap-2 text-sm'><input type='checkbox' checked={fetchKingdee} onChange={e=>setFetchKingdee(e.target.checked)} disabled={busy||Boolean(runId)} />从金蝶获取缺少的报表</label>
      </div>
      {fetchKingdee && !runId && <details open={!configured} className='rounded-md border p-3'>
        <summary className='cursor-pointer text-sm'>金蝶账号：{configured?'已配置，可更新':'尚未配置'}</summary>
        <div className='mt-3 grid gap-3 md:grid-cols-3'>
          <Input aria-label='金蝶账号' autoComplete='username' value={account} onChange={e=>setAccount(e.target.value)} placeholder='金蝶账号' />
          <Input aria-label='金蝶密码' autoComplete='new-password' type='password' value={password} onChange={e=>setPassword(e.target.value)} placeholder='金蝶密码' />
          <Button variant='outline' onClick={()=>void saveCredential()} disabled={busy}>加密保存账号</Button>
        </div><p className='mt-2 text-xs text-muted-foreground'>密码仅用于服务器登录，不写入报表或任务参数。遇到人工验证会提示补充授权或上传文件。</p>
      </details>}
      {!runId && <div className='space-y-2'>
        <Label htmlFor='statement-upload'>公司原始报表（支持一个文件包含三张表）</Label>
        <Input id='statement-upload' type='file' accept='.xls,.xlsx' multiple disabled={busy} onChange={e=>{void upload(e.target.files);e.target.value='';}} />
        <p className='text-xs text-muted-foreground'>按表内公司、月份及字段识别。同公司同月同表内容冲突时，请保留一个权威来源。资产负债表应勾选重分类、不勾选应交税费重分类。</p>
        {materials.map(file=><div key={file.id} className='flex items-center justify-between gap-3 rounded border p-2 text-sm'><span className='break-all'>{file.original_name}</span><Button size='sm' variant='ghost' disabled={busy} onClick={()=>setMaterials(v=>v.filter(x=>x.id!==file.id))}>移出本次</Button></div>)}
      </div>}
      {parent && <p className='text-sm'>本次生成关联补充版本，保留上次结果。</p>}
      {error && <p role='alert' className='text-sm text-destructive'>{error}</p>}
      {!runId && <Button disabled={busy} onClick={()=>void start()}>{busy?'正在处理…':'运行报表任务'}</Button>}
      {runId && <div className='space-y-3 rounded-md bg-muted/40 p-4'>
        <p>{running?'正在运行':run?.state==='succeeded'?(result.summary?.complete?'资料完整且校验通过':'已生成部分底稿或待核实底稿，请检查下方范围'):'任务未完成'}</p>
        {run?.state==='succeeded' && <p className='text-sm font-medium'>已纳入 {result.summary?.report_count ?? 0} / 24 张报表；缺少 {result.summary?.missing_report_count ?? 24-(result.summary?.report_count ?? 0)} 张。{result.summary?.coverage_complete===false?'当前为部分底稿。':''}</p>}
        <progress className='w-full' max={100} value={run?.progress ?? 0} />
        <p className='text-sm'>{run?.progress_message}</p>
        {run?.error_message && <p role='alert' className='text-sm text-destructive'>{run.error_message}</p>}
        <Link className='text-sm underline' href={'/dashboard/runs/'+encodeURIComponent(runId)}>查看任务详情与事件</Link>
        <p className='text-xs text-muted-foreground'>关闭页面不会中断任务，回到当前地址或任务中心可以继续查看。</p>
        {!running && <Button variant='outline' disabled={busy} onClick={()=>void supplement()}>补取缺表或补充资料</Button>}
      </div>}
    </CardContent></Card>
    <Card><CardHeader><CardTitle>报表资料范围</CardTitle></CardHeader><CardContent>
      <div className='overflow-x-auto'><table className='w-full text-sm'><thead><tr className='border-b text-left'><th className='p-2'>公司</th><th>资产负债表</th><th>利润表</th><th>现金流量表</th></tr></thead><tbody>
        {companies.map(([code,name])=>{const row=result.coverage?.find(x=>x.company===code);return <tr key={code} className='border-b'><td className='p-2'>{name}</td>{(['bs','is','cf'] as const).map(k=><td key={k}>{row?.[k] ?? '运行后核验'}</td>)}</tr>;})}
      </tbody></table></div>
      <p className='mt-3 text-xs text-muted-foreground'>分别显示已纳入、未上传、未取数、取数失败及解析失败。程序执行成功不代表资料齐全；缺少的整张报表不会按零纳入。</p>
    </CardContent></Card>
    {(result.output_files?.length ?? 0)>0 && <Card><CardHeader><CardTitle>结果文件</CardTitle></CardHeader><CardContent className='space-y-3'>
      {result.warnings?.map((text,i)=><p key={i} className='text-sm text-amber-700'>{text}</p>)}
      {result.output_files?.map(file=><a key={file.file_id} href={linkForFile(file.file_id)} className='block break-all text-sm underline'>{file.name}</a>)}
    </CardContent></Card>}
  </div>;
}
