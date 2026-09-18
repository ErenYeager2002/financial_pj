import {Type} from "@earendil-works/pi-ai";
import {defineTool,type ExtensionAPI} from "@earendil-works/pi-coding-agent";
import {spawn} from "node:child_process";
export default function(pi:ExtensionAPI) {
 pi.registerTool(defineTool({name:"query_platform",label:"查询平台业务",description:"只读查询当前账号授权的平台任务、工具目录、应收核销材料和凭据是否齐备。tasks 可按 query 查询单号/任务号并分页，state 为状态；skills 列出工具和已安装 Skill；ar_materials 必须指定 ar-hexiao-daily 或 ar-hexiao-daily-lab。返回实时平台结果，不启动、不重跑、不核销。不能用该工具查询原始密码或密钥。",
 parameters:Type.Object({resource:Type.Union([Type.Literal("tasks"),Type.Literal("skills"),Type.Literal("ar_materials")]),page:Type.Optional(Type.Integer({minimum:1,maximum:100000})),query:Type.Optional(Type.String({maxLength:128})),state:Type.Optional(Type.Union([Type.Literal("pending"),Type.Literal("running"),Type.Literal("failed"),Type.Literal("succeeded"),Type.Literal("cancelled")])),skill_id:Type.Optional(Type.String({maxLength:128}))}),
 async execute(_id,params,signal) {
  const result=await new Promise<{stdout:string;code:number|null}>((resolve,reject)=>{
   if(signal?.aborted){reject(new Error("查询已取消"));return;}
   const child=spawn("python",["-B","/opt/platform/pi_business_client.py"],{stdio:["pipe","pipe","ignore"]});
   let output="",finished=false;
   const done=(error?:Error,code:number|null=null)=>{if(finished)return;finished=true;clearTimeout(timer);signal?.removeEventListener("abort",abort);if(error){child.kill();reject(error)}else resolve({stdout:output,code})};
   const abort=()=>done(new Error("查询已取消"));
   const timer=setTimeout(()=>done(new Error("平台查询超时，请检查连接后再查询")),50000);
   signal?.addEventListener("abort",abort,{once:true});
   child.stdout.on("data",chunk=>{output+=chunk.toString();if(output.length>2*1024*1024)done(new Error("查询结果过大，请缩小范围"))});
   child.on("error",()=>done(new Error("平台查询进程不可用")));child.on("close",code=>done(undefined,code));
   child.stdin.on("error",()=>done(new Error("平台查询输入失败")));child.stdin.end(JSON.stringify(params));
  });
  let value;try{value=JSON.parse(result.stdout)}catch{value={error:"平台业务查询没有返回有效结果"}}
  return {content:[{type:"text",text:JSON.stringify(value)}],isError:result.code!==0||Boolean(value.error),details:{source:"live_platform"}};
 }}));
}
