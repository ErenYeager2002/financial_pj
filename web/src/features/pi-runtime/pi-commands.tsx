"use client";
import {createPortal} from "react-dom";
export type PiCommand={name:string;description?:string;source:"extension"|"prompt"|"skill"};
const labels={extension:"扩展命令",prompt:"提示词模板",skill:"Skill"};
export function PiCommands({commands,query,onChoose,onClose,onRefresh}:{commands:PiCommand[];query:string;onChoose:(command:PiCommand)=>void;onClose:()=>void;onRefresh:()=>void}){
 const matching=commands.filter(command=>`${command.name} ${command.description??""}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
 return createPortal(<section aria-label="Pi 命令列表" className="bg-background fixed right-4 bottom-[min(12rem,30dvh)] z-50 max-h-[60dvh] w-[min(42rem,calc(100vw-2rem))] overflow-y-auto rounded-xl border p-3 shadow-lg">
  <div className="mb-2 flex items-center justify-between gap-2 text-sm"><span>Skill、模板与扩展命令</span><div className="flex gap-3"><button type="button" onClick={onRefresh}>刷新</button><button type="button" onClick={onClose} aria-label="关闭命令列表">关闭</button></div></div>
  <div className="max-h-[min(40dvh,20rem)] overflow-y-auto"><ul className="space-y-1">{matching.map(command=><li key={`${command.source}:${command.name}`}><button type="button" onClick={()=>onChoose(command)} className="hover:bg-muted focus-visible:bg-muted block w-full rounded-lg p-2 text-left"><span className="flex flex-wrap items-center gap-2 text-sm"><span>/{command.name}</span><span className="text-muted-foreground text-xs">{labels[command.source]??command.source}</span></span>{command.description&&<span className="text-muted-foreground mt-1 block text-xs">{command.description}</span>}</button></li>)}</ul>{!matching.length&&<p className="text-muted-foreground py-4 text-sm">没有匹配的命令。启动会话后可读取已加载的命令。</p>}</div>
  <p className="text-muted-foreground mt-2 text-xs">选择后可补充参数，点击发送才会执行。终端专用命令请在辅助终端使用。</p>
 </section>,document.body);
}
