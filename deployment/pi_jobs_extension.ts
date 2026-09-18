import { Type } from '@earendil-works/pi-ai';
import { defineTool, type ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { spawn } from 'node:child_process';

export default function(pi: ExtensionAPI) {
  pi.registerTool(defineTool({
    name: 'platform_job', label: 'Background job',
    description: 'Start, list, poll or cancel persistent shell jobs in your isolated workspace. Start returns job_id immediately. For long commands use this tool, then poll with the returned byte offset. An observation timeout means the job is still running; never start it again merely because a poll returned no output. Jobs survive Pi conversation restarts; stopping the whole environment interrupts them and does not rerun them. Output is capped at 64 MiB with an explicit truncation flag; save large artifacts as workspace files.',
    parameters: Type.Object({
      operation: Type.Union([Type.Literal('start'),Type.Literal('list'),Type.Literal('poll'),Type.Literal('cancel')]),
      command: Type.Optional(Type.String()), cwd: Type.Optional(Type.String()),
      job_id: Type.Optional(Type.String()), after: Type.Optional(Type.Integer({minimum:0})),
      wait_seconds: Type.Optional(Type.Number({minimum:0,maximum:10}))
    }),
    async execute(_id, params, _signal) {
      // Aborting an observation does not implicitly cancel the durable job.
      const result = await new Promise<string>((resolve,reject)=>{
        const child=spawn('python',['-B','/opt/platform/pi_jobs.py'],{stdio:['pipe','pipe','pipe']});
        let output=''; child.stdout.on('data',chunk=>{output+=chunk.toString()});
        child.on('error',reject); child.on('close',code=>code===0?resolve(output):reject(new Error('Background job request failed')));
        child.stdin.on('error', reject); child.stdin.end(JSON.stringify(params));
      });
      const value=JSON.parse(result); delete value.output_base64;
      return {content:[{type:'text',text:JSON.stringify(value)}],details:value};
    }
  }));
}
