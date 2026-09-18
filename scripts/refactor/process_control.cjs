const {spawn} = require('node:child_process');
function runGroup(command,args,{cwd,env,timeout=240000,maxBuffer=8*1024*1024}={}) {
  if(process.platform==='win32') return Promise.reject(Error('POSIX process groups required'));
  return new Promise(resolve=>{
    const child=spawn(command,args,{cwd,env,detached:true,stdio:['ignore','pipe','pipe']});
    let stdout='',stderr='',error,killTimer,finished=false,bytes=0;
    const signal=value=>{if(!child.pid)return;try{process.kill(-child.pid,value);}catch(e){if(e.code!=='ESRCH')throw e;}};
    const stop=code=>{if(error)return;error={code};signal('SIGTERM');killTimer=setTimeout(()=>signal('SIGKILL'),250);};
    const timer=setTimeout(()=>stop('TIMEOUT'),timeout);
    const capture=(key,data)=>{bytes+=data.length;if(bytes>maxBuffer){stop('MAX_BUFFER');return;}if(key==='out')stdout+=data.toString();else stderr+=data.toString();};
    child.stdout.on('data',data=>capture('out',data));child.stderr.on('data',data=>capture('err',data));
    const finish=(status,exitSignal)=>{if(finished)return;finished=true;clearTimeout(timer);clearTimeout(killTimer);signal('SIGKILL');resolve({status,signal:exitSignal,error,stdout,stderr});};
    child.on('error',value=>{error={code:value.code};finish(null,null);});
    child.on('close',finish);
  });
}
module.exports={runGroup};
