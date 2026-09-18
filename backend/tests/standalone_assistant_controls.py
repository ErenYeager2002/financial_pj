import unittest
from datetime import UTC,datetime,timedelta
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import create_engine,select,update
from sqlalchemy.orm import Session
from app.auth import UserContext
from app.auth_models import User,UserSkillPermission
from app.models import AssistantTurn,AssistantMessage,RunRecord
from app.native_skill_policy import require_native_skill,visible_native_skills
from app.assistant_turn_service import TurnMutation,mutate_turn,turn_status,require_turn_command

class Controls(unittest.TestCase):
 def setUp(self):
  self.engine=create_engine("sqlite://")
  for m in [User,UserSkillPermission,AssistantTurn,AssistantMessage,RunRecord]:m.__table__.create(self.engine)
  self.db=Session(self.engine)
  self.db.add_all([User(id=x,username=x,password_hash="unused",department_id="d",role="finance_user") for x in ['a','b']]);self.db.commit()
  self.user=UserContext(user_id="a",display_name="a",department_id="d",role="finance_user")
 def tearDown(self):self.db.close();self.engine.dispose()
 def begin(self):return mutate_turn(self.db,self.user,"session",TurnMutation(action="begin"))
 def test_default_deny_and_separate_namespace(self):
  self.db.add(UserSkillPermission(id="p",user_id="a",skill_id="pdf",can_run=True));self.db.commit()
  with self.assertRaises(HTTPException):require_native_skill(self.db,self.user,"pdf")
  self.db.get(UserSkillPermission,"p").skill_id="native--pdf";self.db.commit()
  require_native_skill(self.db,self.user,"pdf")
  self.db.get(UserSkillPermission,"p").can_run=False;self.db.commit()
  with self.assertRaises(HTTPException):require_native_skill(self.db,self.user,"pdf")
 def test_revocation_reloads_cached_permission(self):
  permission=UserSkillPermission(id="cached",user_id="a",skill_id="native--pdf",can_run=True)
  self.db.add(permission);self.db.commit();require_native_skill(self.db,self.user,"pdf")
  with Session(self.engine) as second:
   second.execute(update(UserSkillPermission).where(UserSkillPermission.id=="cached").values(can_run=False));second.commit()
  with self.assertRaises(HTTPException):require_native_skill(self.db,self.user,"pdf")
 def test_disabled_admin_rechecked(self):
  self.db.get(User,"a").status="disabled";self.db.commit()
  with self.assertRaises(HTTPException):require_native_skill(self.db,self.user,"pdf")
 def test_list_filtered(self):
  self.assertEqual(visible_native_skills(self.db,self.user,[SimpleNamespace(id="pdf")]),[])
 def test_duplicate_begin_rejected(self):
  self.begin()
  with self.assertRaises(HTTPException):self.begin()
 def test_state_survives_new_session(self):
  entry=self.begin();self.db.close();self.db=Session(self.engine)
  self.assertEqual(turn_status(self.db,self.user,"session")["id"],entry["id"])
 def test_partial_reply_recovered_on_expiry(self):
  e=self.begin();mutate_turn(self.db,self.user,"session",TurnMutation(action="touch",turn_id=e['id'],text="partial"))
  self.db.execute(update(AssistantTurn).values(lease_expires_at=datetime.now(UTC)-timedelta(seconds=1)));self.db.commit()
  self.assertEqual(turn_status(self.db,self.user,"session")['state'],'interrupted')
  self.assertIn('partial',self.db.get(AssistantMessage,e['id']).content)
  with self.assertRaises(HTTPException):mutate_turn(self.db,self.user,"session",TurnMutation(action="finish",turn_id=e['id'],text="late success"))
 def test_stop_rejects_next_command(self):
  e=self.begin();mutate_turn(self.db,self.user,"session",TurnMutation(action="stop"))
  with self.assertRaises(HTTPException):require_turn_command(self.db,self.user,"session",e['id'])
 def test_missing_turn_id_cannot_bypass_stop(self):
  self.begin();mutate_turn(self.db,self.user,"session",TurnMutation(action="stop"))
  with self.assertRaises(HTTPException):require_turn_command(self.db,self.user,"session","")
 def test_other_user_cannot_observe_turn(self):
  self.begin();b=UserContext(user_id="b",display_name="b",department_id="d",role="finance_user")
  self.assertEqual(turn_status(self.db,b,"session")['state'],'unknown')
 def test_stop_unknown_and_repeat(self):
  self.assertEqual(mutate_turn(self.db,self.user,"missing",TurnMutation(action="stop"))["state"],"unknown")
  self.begin()
  for _ in range(2):self.assertTrue(mutate_turn(self.db,self.user,"session",TurnMutation(action="stop"))["stopped"])
 def test_actual_failed_run_overrides_claimed_success(self):
  self.db.add(RunRecord(id="failed",owner_id="a",department_id="d",skill_id="native--pdf",skill_name="pdf",skill_version="1",skill_hash="h",manifest_path="",manifest_snapshot="{}",adapter="native",worker_pool="native",state="failed"));self.db.commit()
  e=self.begin()
  result=mutate_turn(self.db,self.user,"session",TurnMutation(action="finish",turn_id=e['id'],text="claimed success",data={"native_run_ids":["failed"]}))
  self.assertEqual(result["state"],"failed");self.assertIn("未成功",self.db.get(AssistantMessage,e['id']).content)
 def test_finish_atomic_message(self):
  e=self.begin();mutate_turn(self.db,self.user,"session",TurnMutation(action="finish",turn_id=e['id'],error="failed",text="failed"))
  self.assertEqual(self.db.get(AssistantMessage,e['id']).content,'failed')
  self.assertEqual(turn_status(self.db,self.user,"session")['state'],'failed')
if __name__=="__main__":unittest.main()
