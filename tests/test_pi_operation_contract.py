import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace
from uuid import uuid4
from fastapi import HTTPException
from app.pi_operation_contract import validate_operation

class OperationContractTests(unittest.TestCase):
 def reject(self,operation,payload):
  with self.assertRaises(HTTPException) as error: validate_operation(operation,payload)
  self.assertEqual(error.exception.status_code,422)
 def test_current_ui_controls_remain_available(self):
  for kind in ['get_state','get_messages','get_available_models','get_commands','abort','clear_queue','compact']:
   with self.subTest(kind=kind): validate_operation('send',{'command':{'type':kind,'id':'test'}})
  for kind in ['prompt','steer','follow_up']:
   validate_operation('send',{'command':{'type':kind,'message':'test','id':'test'},'client_request_id':str(uuid4())})
  validate_operation('send',{'command':{'type':'set_model','provider':'platform','modelId':'model'}})
  validate_operation('send',{'command':{'type':'set_thinking_level','level':'high'}})
  for answer in [{'confirmed':False},{'cancelled':True},{'value':''}]:
   validate_operation('send',{'command':{'type':'extension_ui_response','id':'dialog',**answer}})
 def test_invalid_utf8_and_oversized_encoded_command_rejected_before_transport(self):
  for message in ['\ud800', '"' * (4 * 1024 * 1024), '财' * (3 * 1024 * 1024)]:
   with self.subTest(characters=len(message)): self.reject('send',{'command':{'type':'prompt','message':message}})
 def test_identity_and_path_injection_rejected_for_every_rpc(self):
  for extra in [{'owner':'other'},{'approved':True},{'session_id':'other'},{'path':'/etc/passwd'},{'sql':'select 1'}]:
   with self.subTest(extra=extra):
    self.reject('send',{'command':{'type':'prompt','message':'test',**extra}})
    self.reject('send',{'command':{'type':'abort'},**extra})
 def test_unadapted_rpc_and_malformed_discriminators_return_422(self):
  for kind in ['bash','new_session','fork','export_html','unknown',[],{},None,True]:
   with self.subTest(kind=kind): self.reject('send',{'command':{'type':kind}})
  for bad in [[],{},True,1]:
   self.reject('send',{'command':{'type':'set_thinking_level','level':bad}})
   self.reject('start',{'mode':bad})
   self.reject('jobs',{'operation':bad})
 def test_legacy_terminal_and_lifecycle_contract_preserved(self):
  validate_operation('start',{'mode':'terminal'});validate_operation('start',{'mode':'rpc'})
  validate_operation('send',{'data':'YQ=='});validate_operation('resize',{'rows':32,'cols':120})
  validate_operation('poll',{'after':0});validate_operation('stop',{})
  for op,value in [('send',{'data':'invalid!'}),('send',{'data':'YQ==','command':{'type':'abort'}}),('resize',{'rows':True}),('poll',{'after':-1}),('stop',{'owner':'other'}),('send',{'command':{'type':'abort'},'client_request_id':str(uuid4())})]: self.reject(op,value)
 def test_job_api_cannot_start_arbitrary_process_and_retains_cancel(self):
  job=str(uuid4());validate_operation('jobs',{'operation':'list'})
  validate_operation('jobs',{'operation':'poll','job_id':job,'after':0,'wait_seconds':1.5})
  validate_operation('jobs',{'operation':'cancel','job_id':job})
  for payload in [{'operation':'start','command':'sh'},{'operation':'cancel','job_id':'../other'},{'operation':'poll','job_id':job,'wait_seconds':float('nan')},{'operation':'cancel','job_id':job,'approved':True}]: self.reject('jobs',payload)
 def test_dialog_shape_does_not_replace_pending_dialog_authority(self):
  for answer in [{'confirmed':'true'},{'cancelled':False},{'value':[]},{'confirmed':True,'value':'x'},{'approved':True}]:
   self.reject('send',{'command':{'type':'extension_ui_response','id':'dialog',**answer}})
 def test_invalid_request_rejected_before_host_transport(self):
  from app import pi_runtime_service as service
  with TemporaryDirectory() as directory, patch.object(service,'require_session',side_effect=lambda user,session_id,**kw:session_id),patch.object(service,'catalog',return_value=Path(directory)),patch.object(service,'_request_runtime') as transport:
   with self.assertRaises(HTTPException):service.operate(SimpleNamespace(),str(uuid4()),'send',{'command':{'type':'prompt','message':'test','approved':True}})
   transport.assert_not_called()

class RevokedSkillControlTests(unittest.TestCase):
 def invoke(self,operation,payload,allowed):
  from app import pi_runtime_service as service
  calls=[]
  def owner_check(user,session_id,**kwargs):
   calls.append(kwargs['check_skill'])
   if kwargs['check_skill']: raise HTTPException(403,'Skill revoked')
   return session_id
  with TemporaryDirectory() as directory,patch.object(service,'require_session',side_effect=owner_check),patch.object(service,'catalog',return_value=Path(directory)),patch.object(service,'owner_scope',return_value='trusted-owner'),patch.object(service,'_request_runtime',return_value={'observed':True}) as host:
   if allowed:
    self.assertEqual(service.operate(SimpleNamespace(),str(uuid4()),operation,payload),{'observed':True})
    host.assert_called_once();self.assertEqual(calls,[False,False])
    self.assertEqual(host.call_args[0][0]['owner'],'trusted-owner')
   else:
    with self.assertRaises(HTTPException) as error:service.operate(SimpleNamespace(),str(uuid4()),operation,payload)
    self.assertEqual(error.exception.status_code,403);host.assert_not_called()
 def test_revoked_skill_preserves_owner_observation_and_abort(self):
  self.invoke('poll',{'after':0},True)
  for kind in ['get_state','get_messages','abort','clear_queue']:self.invoke('send',{'command':{'type':kind}},True)
  for kind in ['list','poll','cancel']:self.invoke('jobs',{'operation':kind,**({'job_id':str(uuid4())} if kind!='list' else {})},True)
 def test_revoked_skill_cannot_resume_or_approve_work(self):
  for command in [{'type':'prompt','message':'test'},{'type':'steer','message':'test'},{'type':'follow_up','message':'test'},{'type':'set_model','provider':'p','modelId':'m'},{'type':'extension_ui_response','id':'dialog','confirmed':True},{'type':'extension_ui_response','id':'dialog','value':'execute'}]:self.invoke('send',{'command':command},False)
 def test_revoked_skill_can_reject_or_cancel_pending_dialog(self):
  for response in [{'cancelled':True},{'confirmed':False}]:self.invoke('send',{'command':{'type':'extension_ui_response','id':'dialog',**response}},True)

if __name__=='__main__':unittest.main()
