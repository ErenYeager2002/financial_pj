"use client";
import {useEffect,useRef,useState} from "react";

export type PiImageBlock={type:string;data?:string;mimeType?:string};
const rasterTypes=new Set(["image/png","image/jpeg","image/webp","image/gif","image/avif"]);
function ImagePreview({data,mimeType,index}:{data:string;mimeType:string;index:number}){
 const dialog=useRef<HTMLDialogElement>(null);
 const [failed,setFailed]=useState(false);
 useEffect(()=>setFailed(false),[data,mimeType]);
 const source=`data:${mimeType};base64,${data}`;
 const title=`对话图片 ${index+1}`;
 return <figure className="min-w-0 space-y-2">
  {failed?<p className="text-muted-foreground text-xs">图片无法预览，可以下载后查看。</p>:<button type="button" aria-label={`放大${title}`} className="block max-w-full overflow-hidden rounded-lg border focus-visible:outline-2 focus-visible:outline-primary" onClick={()=>dialog.current?.showModal()}>
   {/* Native data images stay in this browser and never reach an image proxy. */}
   {/* eslint-disable-next-line @next/next/no-img-element */}
   <img src={source} alt={title} loading="lazy" decoding="async" onError={()=>setFailed(true)} className="max-h-80 max-w-full object-contain"/>
  </button>}
  <figcaption className="text-muted-foreground flex gap-3 text-xs"><span>{title}</span><a className="underline" href={source} download={`agent-image-${index+1}.${mimeType==='image/jpeg'?'jpg':mimeType.slice(6)}`}>下载图片</a></figcaption>
  <dialog ref={dialog} aria-label={title} className="bg-background text-foreground fixed inset-0 m-auto max-h-[95dvh] max-w-[95vw] rounded-xl border p-4 backdrop:bg-black/60" onClick={event=>{if(event.target===event.currentTarget)dialog.current?.close()}}>
   <div className="mb-3 flex items-center justify-between gap-8"><span>{title}</span><button type="button" className="rounded border px-3 py-1 text-sm" onClick={()=>dialog.current?.close()}>关闭图片</button></div>
   {/* eslint-disable-next-line @next/next/no-img-element */}
   <img src={source} alt={title} className="max-h-[80dvh] max-w-full object-contain"/>
  </dialog>
 </figure>;
}
export function PiMessageImages({blocks}:{blocks:PiImageBlock[]}){
 const images=blocks.filter(block=>block.type==='image');
 if(!images.length)return null;
 return <div className="mt-3 space-y-3">{images.map((block,index)=>typeof block.data==='string'&&block.data.length>0&&typeof block.mimeType==='string'&&rasterTypes.has(block.mimeType)
  ?<ImagePreview key={index} data={block.data} mimeType={block.mimeType} index={index}/>
  :<div key={index} className="text-muted-foreground space-y-1 text-xs"><p>此图片格式暂不支持预览。</p>{typeof block.data==='string'&&block.data.length>0&&<a className="underline" href={`data:application/octet-stream;base64,${block.data}`} download={`agent-image-${index+1}.bin`}>下载原始图片数据</a>}</div>)}</div>;
}
