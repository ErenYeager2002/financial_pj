import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

source=Path(__file__).resolve().parents[1]/'deployment/pi_history.py'
spec=importlib.util.spec_from_file_location('pi_history',source)
history=importlib.util.module_from_spec(spec);spec.loader.exec_module(history)

class CustomHistoryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);self.owner='a'*64;self.session='7089fbdc-6ca0-40e0-aabc-3775092e86d9'
  self.directory=self.root/'owners'/self.owner/'home/.pi/agent/sessions/platform'/self.session
  self.directory.mkdir(parents=True)
 def read(self,entries):
  (self.directory/'one.jsonl').write_text(''.join(json.dumps(item)+'\n' for item in entries))
  return history.read_history(self.root,self.owner,self.session)['messages']
 def entry(self,**changes):
  return dict({'type':'custom_message','id':'c1','parentId':None,'customType':'fixture','content':'visible result','display':True,'details':{'internal':'not for UI'},'timestamp':'2026-09-29T08:00:00.000Z'},**changes)
 def test_visible_result_is_preserved_in_same_wire_shape_as_live_pi(self):
  messages=self.read([self.entry()])
  self.assertEqual(len(messages),1)
  self.assertEqual(messages[0],{'role':'custom','customType':'fixture','content':'visible result','display':True,'timestamp':1790668800000})
 def test_hidden_and_internal_entries_are_not_disclosed(self):
  for flag in [False,None,'true',1]:
   self.assertEqual(self.read([self.entry(display=flag)]),[])
  self.assertEqual(self.read([self.entry(type='custom')]),[])
 def test_only_selected_branch_custom_messages_appear(self):
  entries=[self.entry(id='base'),self.entry(id='other',parentId='base',content='other branch'),self.entry(id='chosen',parentId='base',content='chosen branch')]
  self.assertEqual([m['content'] for m in self.read(entries)],['visible result','chosen branch'])
 def test_custom_messages_obey_existing_history_limit(self):
  history.MAX_MESSAGES=2
  try:
   messages=self.read([self.entry(id=str(i),parentId=str(i-1) if i else None,content=str(i)) for i in range(3)])
   self.assertEqual([m['content'] for m in messages],['1','2'])
  finally:history.MAX_MESSAGES=500
 def test_missing_or_invalid_visible_content_does_not_return_partial_success(self):
  for changes in [{'content':None},{'timestamp':'not-a-date'},{'timestamp':'2026-09-29T08:00:00'}]:
   with self.assertRaises(history.HistoryError):self.read([self.entry(**changes)])
 def test_incomplete_tail_is_ignored_and_symlink_pointer_is_rejected(self):
  self.read([self.entry()])
  with (self.directory/'one.jsonl').open('a') as f:f.write('{unfinished')
  self.assertEqual(len(history.read_history(self.root,self.owner,self.session)['messages']),1)
  external=self.root/'pointer.json';external.write_text('{}')
  (self.directory/'active.json').symlink_to(external)
  with self.assertRaises(history.HistoryError):history.read_history(self.root,self.owner,self.session)
 def test_duplicate_identity_is_rejected(self):
  with self.assertRaises(history.HistoryError):self.read([self.entry(),self.entry()])
if __name__=='__main__':unittest.main()
