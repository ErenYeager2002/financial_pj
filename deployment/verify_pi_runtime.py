"""Synthetic smoke check; run only in a disposable Pi container with tmpfs home/workspace."""
import importlib.util,time,json
s=importlib.util.spec_from_file_location('bridge','/opt/platform/pi_runtime_server.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
p=m.PiProcess()
def command(value): p.send({'command':value})
def response(rid,timeout=15):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  for item in p.poll({'after':0})['events']:
   r=item.get('event',{})
   if r.get('id')==rid and r.get('type')=='response': return r
  time.sleep(.05)
 raise AssertionError('Response missing '+rid)
p.start('rpc');command({'id':'new','type':'new_session'});assert response('new')['success']
command({'id':'state1','type':'get_state'});newid=response('state1')['data']['sessionId']
p.stop();p.start('rpc');command({'id':'state2','type':'get_state'});assert response('state2')['data']['sessionId']==newid
print('PASS official empty new session resumed after restart',flush=True)
command({'id':'long','type':'bash','command':'sleep 140; printf unexpected-completion'})
started=time.monotonic()
for until in [65,123]:
 while time.monotonic()-started<until: time.sleep(.5)
 assert p.live()
 assert not any(e.get('event',{}).get('id')=='long' and e.get('event',{}).get('type')=='response' for e in p.poll({'after':0})['events'])
 print('Long task still running after',until,'seconds',flush=True)
command({'id':'abort','type':'abort_bash'});assert response('abort')['success'];r=response('long')
assert 'unexpected-completion' not in r['data'].get('output',''),r
assert time.monotonic()-started<139
print('PASS long task cancelled through official RPC',flush=True)
p.stop();p.start('terminal');time.sleep(2)
assert any(e['kind']=='terminal' for e in p.poll({'after':0})['events']);p.stop()
print('PASS interactive terminal after RPC lifecycle',flush=True)
