"""Synthetic, isolated file-retention checks; no production file/DB access."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app import file_retention as retention
from app import models
from app.settings import settings
from app.resource_policy import upload_root, run_root, workflow_root

BASE = datetime(2026, 1, 1, tzinfo=UTC)

class FileRetentionTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get('FILE_RETENTION_ISOLATED_TEST') != '1' or str(settings.data_dir) != '/tmp/file-retention-test-data':
            raise RuntimeError('Isolated test environment required')
        self.engine = create_engine('sqlite://')
        models.Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.patch = patch.object(retention, 'SessionLocal', self.Session)
        self.patch.start()
        settings.data_dir.mkdir(exist_ok=True)

    def tearDown(self):
        self.patch.stop(); self.db.close(); self.engine.dispose()
        shutil.rmtree(settings.data_dir)

    def run_record(self, day, *, state='succeeded', owner='owner-a', skill='tool-a', files=None, finished=None):
        row = models.RunRecord(id=str(uuid.uuid4()), owner_id=owner, department_id='finance',
            skill_id=skill, skill_name=skill, skill_version='1.0.0', skill_hash='0'*64,
            manifest_path='/unused', manifest_snapshot='{}', adapter='python', worker_pool='standard',
            state=state, created_at=BASE+timedelta(days=day), finished_at=BASE+timedelta(days=finished if finished is not None else day),
            files_json=json.dumps(files or {}))
        self.db.add(row); self.db.commit(); return row

    def file(self, day, *, kind='input', run=None, workflow=None, owner='owner-a', skill='tool-a', content=None):
        file_id = str(uuid.uuid4())
        if run:
            owner=run.owner_id;skill=run.skill_id
        if workflow:
            owner=workflow.owner_id;skill=workflow.skill_id
        root = run_root(owner, run.id) if kind=='output' and run else workflow_root(owner, workflow.id)/'outputs' if workflow else upload_root(owner,file_id)
        root.mkdir(parents=True,exist_ok=True)
        path=root/(file_id+'.txt')
        payload=(content or file_id).encode();path.write_bytes(payload)
        row=models.FileRecord(id=file_id,owner_id=owner,department_id='finance',kind=kind,
            original_name='same-name.txt',stored_path=str(path),content_type='text/plain',size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),run_id=run.id if kind=='output' and run else None,
            workflow_id=workflow.id if workflow else '',skill_id=skill,created_at=BASE+timedelta(days=day))
        self.db.add(row);self.db.commit();return row

    def candidates(self): return {e['file_id'] for e in retention.plan(self.db)['entries']}

    def two_runs(self):
        old_input=self.file(0)
        old=self.run_record(1,files={'file_id':old_input.id});old_output=self.file(1,kind='output',run=old)
        new_input=self.file(2)
        new=self.run_record(3,files={'file_id':new_input.id});new_output=self.file(3,kind='output',run=new)
        return old_input,old_output,new_input,new_output

    def test_replaces_both_inputs_and_outputs_independent_of_filename(self):
        old_input,old_output,new_input,new_output=self.two_runs()
        self.assertEqual(self.candidates(),{old_input.id,old_output.id})

    def test_failed_new_task_does_not_replace_success(self):
        old_input,old_output,new_input,new_output=self.two_runs()
        failed=self.run_record(5,state='failed');failed_output=self.file(5,kind='output',run=failed)
        self.assertNotIn(new_output.id,self.candidates())
        self.assertNotIn(new_input.id,self.candidates())
        self.assertNotIn(failed_output.id,self.candidates())

    def test_owner_and_tool_scopes_are_separate(self):
        old_input,old_output,_,_=self.two_runs()
        another=self.run_record(10,owner='owner-b');other=self.file(10,kind='output',run=another)
        other_tool=self.run_record(11,skill='tool-b');other_file=self.file(11,kind='output',run=other_tool)
        self.assertEqual(self.candidates(),{old_input.id,old_output.id})

    def test_active_task_reusing_old_input_protects_it(self):
        old_input,old_output,_,_=self.two_runs()
        self.run_record(5,state='running',files={'file_id':old_input.id})
        self.assertNotIn(old_input.id,self.candidates())
        self.assertIn(old_output.id,self.candidates())

    def test_latest_reused_input_is_preserved(self):
        old_input,old_output,_,_=self.two_runs()
        newest=self.run_record(7,files={'file_id':old_input.id});self.file(7,kind='output',run=newest)
        self.assertNotIn(old_input.id,self.candidates())

    def test_new_unsubmitted_upload_is_preserved(self):
        self.two_runs();pending=self.file(10)
        self.assertNotIn(pending.id,self.candidates())

    def test_no_successful_output_keeps_existing_files(self):
        old=self.run_record(1,state='failed');out=self.file(1,kind='output',run=old)
        self.run_record(3)
        self.assertEqual(self.candidates(),set())

    def test_broken_latest_output_blocks_deletion(self):
        _,_,_,latest=self.two_runs();Path(latest.stored_path).write_text('corrupt')
        self.assertEqual(self.candidates(),set())

    def test_changed_old_bytes_are_not_deleted(self):
        old_input,old_output,_,_=self.two_runs();Path(old_input.stored_path).write_text('changed')
        self.assertNotIn(old_input.id,self.candidates());self.assertIn(old_output.id,self.candidates())

    def test_symlink_path_is_not_deleted(self):
        old_input,_,_,_=self.two_runs();path=Path(old_input.stored_path)
        saved=path.with_name('saved.txt');path.rename(saved);path.symlink_to(saved)
        self.assertNotIn(old_input.id,self.candidates())

    def test_unassigned_but_task_linked_input_is_grouped(self):
        old_input,old_output,_,_=self.two_runs();old_input.skill_id='';self.db.commit()
        self.assertEqual(self.candidates(),{old_input.id,old_output.id})

    def test_malformed_task_json_blocks_scope(self):
        self.two_runs();broken=self.run_record(0);broken.files_json='{invalid';self.db.commit()
        self.assertEqual(self.candidates(),set())

    def test_financial_material_fk_is_preserved(self):
        old_input,old_output,_,_=self.two_runs()
        material=models.WorkflowMaterialSet(id=str(uuid.uuid4()),owner_id='owner-a',department_id='finance',skill_id='tool-a',version=1,state='current')
        self.db.add(material);self.db.flush()
        self.db.add(models.WorkflowMaterialSetFile(id=str(uuid.uuid4()),material_set_id=material.id,role='receipt_flow_table',year=0,file_id=old_input.id,sha256=old_input.sha256));self.db.commit()
        self.assertNotIn(old_input.id,self.candidates())

    def test_cleanup_removes_records_and_files_and_is_idempotent(self):
        old_input,old_output,new_input,new_output=self.two_runs()
        result=retention.cleanup(dry_run=False)
        self.assertEqual(len(result['entries']),2)
        self.assertFalse(Path(old_input.stored_path).exists());self.assertFalse(Path(old_output.stored_path).exists())
        self.assertTrue(Path(new_input.stored_path).exists());self.assertTrue(Path(new_output.stored_path).exists())
        self.assertEqual(retention.cleanup(dry_run=False)['entries'],[])

    def test_dry_run_has_no_writes(self):
        old_input,_,_,_=self.two_runs()
        retention.cleanup(dry_run=True)
        self.assertTrue(Path(old_input.stored_path).exists())
        self.assertEqual(len(list(self.db.scalars(select(models.FileRecord)))),4)
        self.assertFalse((settings.data_dir/'maintenance').exists())

    def test_batch_keeps_all_date_outputs(self):
        old=self.run_record(1);old_output=self.file(1,kind='output',run=old)
        batch=models.WorkflowBatch(id=str(uuid.uuid4()),owner_id='owner-a',department_id='finance',skill_id='tool-a',skill_name='tool-a',skill_version='1.0.0',model_connection_id='test',model_provider='test',model_name='test',state='succeeded',created_at=BASE+timedelta(days=3),updated_at=BASE+timedelta(days=4))
        self.db.add(batch);self.db.commit();outputs=[]
        for day in (3,4):
            wf=models.WorkflowSession(id=str(uuid.uuid4()),owner_id='owner-a',department_id='finance',skill_id='tool-a',skill_name='tool-a',skill_version='1.0.0',skill_hash='0'*64,model_connection_id='test',model_provider='test',model_name='test',state='succeeded',batch_id=batch.id,created_at=BASE+timedelta(days=day),updated_at=BASE+timedelta(days=day))
            self.db.add(wf);self.db.commit();outputs.append(self.file(day,kind='output',workflow=wf))
        self.assertEqual(self.candidates(),{old_output.id})
        self.assertTrue(all(x.id not in self.candidates() for x in outputs))

    def test_shared_physical_path_is_not_unlinked(self):
        old_input,old_output,_,_=self.two_runs()
        other=self.file(10,owner='owner-b',skill='tool-b')
        other.stored_path=old_input.stored_path;other.sha256=old_input.sha256;other.size_bytes=old_input.size_bytes;self.db.commit()
        result=retention.cleanup(dry_run=False)
        self.assertTrue(Path(old_input.stored_path).exists());self.assertNotIn(old_input.id,{e['file_id'] for e in result['entries']})

    def test_last_completion_wins_even_when_started_earlier(self):
        first=self.run_record(1,finished=8);out1=self.file(8,kind='output',run=first)
        second=self.run_record(3,finished=5);out2=self.file(5,kind='output',run=second)
        self.assertEqual(self.candidates(),{out2.id})

    def test_state_change_during_hashing_defers_cleanup(self):
        old_input,_,_,_=self.two_runs()
        original=retention.plan
        def changed(db, **kwargs):
            result=original(db,**kwargs)
            if kwargs.get('check_files') is False: result['fingerprint']='changed'
            return result
        with patch.object(retention,'plan',side_effect=changed):
            result=retention.cleanup(dry_run=False)
        self.assertEqual(result['entries'],[])
        self.assertTrue(Path(old_input.stored_path).exists())

if __name__=='__main__':unittest.main()
