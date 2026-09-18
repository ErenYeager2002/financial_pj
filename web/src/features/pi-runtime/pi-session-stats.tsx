'use client';
export type PiStats={totalMessages?:number;toolCalls?:number;tokens?:{input?:number;output?:number;cacheRead?:number;cacheWrite?:number;total?:number};cost?:number;contextUsage?:{tokens:number|null;contextWindow:number;percent:number|null}};
const count=(value:number|undefined|null)=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString():'暂不可用';
export function PiSessionStats({stats,connected,onRefresh}:{stats:PiStats|null;connected:boolean;onRefresh:()=>void}){
 const usage=stats?.contextUsage;
 return <section aria-label='会话用量' className='space-y-3 rounded-lg border p-4 text-sm'>
  <div className='flex items-center justify-between gap-2'><h3 className='font-medium'>会话用量</h3><button disabled={!connected} onClick={onRefresh} className='rounded border px-2 py-1 text-xs disabled:opacity-50'>刷新用量</button></div>
  {!stats?<p className='text-muted-foreground'>连接会话后读取用量。</p>:<>
   <dl className='grid grid-cols-2 gap-x-4 gap-y-2'>
    <dt>消息数</dt><dd>{count(stats.totalMessages)}</dd><dt>工具调用</dt><dd>{count(stats.toolCalls)}</dd>
    <dt>输入 Token</dt><dd>{count(stats.tokens?.input)}</dd><dt>输出 Token</dt><dd>{count(stats.tokens?.output)}</dd>
    <dt>缓存读取</dt><dd>{count(stats.tokens?.cacheRead)}</dd><dt>缓存写入</dt><dd>{count(stats.tokens?.cacheWrite)}</dd>
    <dt>累计 Token</dt><dd>{count(stats.tokens?.total)}</dd>
    <dt>Pi 估算费用</dt><dd>{typeof stats.cost==='number'&&Number.isFinite(stats.cost)?'$'+stats.cost.toFixed(4):'暂不可用'}</dd>
    <dt>当前上下文</dt><dd>{usage?`${count(usage.tokens)} / ${count(usage.contextWindow)}`:'暂不可用'}</dd>
    <dt>上下文占比</dt><dd>{typeof usage?.percent==='number'&&Number.isFinite(usage.percent)?usage.percent.toFixed(1)+'%':'暂不可用'}</dd>
   </dl><p className='text-muted-foreground text-xs'>按 Pi 返回的模型用量和价格统计，费用不代表实际账单。整理上下文后，当前用量需等下一次回复更新。</p>
  </>}
  {!connected&&stats&&<p className='text-muted-foreground text-xs'>会话未连接，以上为上次读取的用量。</p>}
 </section>;
}
