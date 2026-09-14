"""PostgreSQL guard tests, only in a disposable container with synthetic schema."""
import os
import threading
import time
import unittest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

class RetentionGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('FILE_RETENTION_ISOLATED_TEST') != '1':
            raise RuntimeError('Disposable PostgreSQL test required')
        cls.engine=create_engine('postgresql+psycopg://retention_test:retention_test@127.0.0.1:5432/retention_test')
        with cls.engine.begin() as db:
            for table,cols in [('task_drafts','files_json text, parameters_json text'),('runs','files_json text, parameters_json text'),('workflow_batches','files_json text'),('workflow_sessions','files_json text, context_json text'),('workflow_actions','input_json text'),('files',"stored_path text, kind text DEFAULT 'input'")]:
                db.exec_driver_sql(f"CREATE TABLE {table} (id text PRIMARY KEY, state text DEFAULT 'ready', {cols})")
            db.exec_driver_sql(GUARD_SQL)

    def setUp(self):
        with self.engine.begin() as db:
            for table in ('task_drafts','runs','workflow_batches','workflow_sessions','workflow_actions','files','file_retention_receipts'):
                db.exec_driver_sql('TRUNCATE '+table)
            db.exec_driver_sql("INSERT INTO files(id,stored_path) VALUES ('old','/old'),('current','/current')")

    def retire(self, db):
        self.assertTrue(db.scalar(text('SELECT pg_try_advisory_xact_lock(7816091001)')))
        db.exec_driver_sql("INSERT INTO file_retention_receipts(file_id,stored_path) VALUES ('old','/old')")
        db.exec_driver_sql("DELETE FROM files WHERE id='old'")

    def test_recursive_json_and_escaped_values(self):
        with self.engine.begin() as db:
            values=db.scalar(text('SELECT file_retention_strings(:raw)'),{'raw':'{"a":[{"b":"o\\u006cd"},"current"],"number":1}'})
            self.assertEqual(set(values),{'old','current'})

    def test_late_reference_waits_then_rejects_retired_file(self):
        deleting=self.engine.connect();tx=deleting.begin();self.retire(deleting)
        started=threading.Event();done=threading.Event();result=[]
        def writer():
            started.set()
            try:
                with self.engine.begin() as db:
                    db.execute(text('INSERT INTO task_drafts(id,files_json) VALUES (:id,:files)'),{'id':'draft','files':'{"file_id":"old"}'})
                result.append('accepted')
            except IntegrityError: result.append('rejected')
            finally: done.set()
        thread=threading.Thread(target=writer);thread.start();started.wait(2)
        self.assertFalse(done.wait(.2))
        tx.commit();deleting.close();thread.join(3)
        self.assertEqual(result,['rejected'])
        with self.engine.connect() as db:self.assertEqual(db.scalar(text('SELECT count(*) FROM task_drafts')),0)

    def test_active_reference_writer_defers_cleanup(self):
        writing=self.engine.connect();tx=writing.begin()
        writing.exec_driver_sql("INSERT INTO task_drafts(id,files_json) VALUES ('draft','{\"file_id\":\"old\"}')")
        with self.engine.begin() as db:self.assertFalse(db.scalar(text('SELECT pg_try_advisory_xact_lock(7816091001)')))
        tx.commit();writing.close()

    def test_all_reference_tables_reject_new_retired_references(self):
        with self.engine.begin() as db:self.retire(db)
        for table,col in [('task_drafts','files_json'),('runs','files_json'),('workflow_batches','files_json'),('workflow_sessions','context_json'),('workflow_actions','input_json')]:
            with self.subTest(table=table), self.assertRaises(IntegrityError), self.engine.begin() as db:
                db.execute(text(f'INSERT INTO {table}(id,{col}) VALUES (:id,:raw)'),{'id':'test','raw':'{"nested":["old"]}'})

    def test_historical_reference_can_remain_while_new_current_file_added(self):
        with self.engine.begin() as db:
            db.exec_driver_sql("INSERT INTO task_drafts(id,files_json) VALUES ('draft','{\"file_id\":\"old\"}')")
            self.retire(db)
        with self.engine.begin() as db:
            db.exec_driver_sql("UPDATE task_drafts SET files_json='[\"old\",\"current\"]' WHERE id='draft'")

    def test_retired_storage_path_cannot_be_reused(self):
        with self.engine.begin() as db:self.retire(db)
        with self.assertRaises(IntegrityError), self.engine.begin() as db:
            db.exec_driver_sql("INSERT INTO files(id,stored_path) VALUES ('new','/old')")

    def test_legacy_delete_creates_receipt(self):
        with self.engine.begin() as db:
            db.exec_driver_sql("DELETE FROM files WHERE id='old'")
            self.assertEqual(db.scalar(text("SELECT count(*) FROM file_retention_receipts WHERE file_id='old'")),1)
        with self.assertRaises(IntegrityError),self.engine.begin() as db:
            db.exec_driver_sql("INSERT INTO task_drafts(id,files_json) VALUES ('late','{\"file_id\":\"old\"}')")

    def test_legacy_delete_cannot_ignore_draft_parameters(self):
        with self.engine.begin() as db:
            db.exec_driver_sql("INSERT INTO task_drafts(id,parameters_json) VALUES ('draft','{\"file_id\":\"old\"}')")
        with self.assertRaises(IntegrityError),self.engine.begin() as db:
            db.exec_driver_sql("DELETE FROM files WHERE id='old'")
        with self.engine.connect() as db:self.assertEqual(db.scalar(text("SELECT count(*) FROM files WHERE id='old'")),1)

    def test_old_task_with_retired_input_cannot_be_reactivated(self):
        with self.engine.begin() as db:
            db.exec_driver_sql("INSERT INTO runs(id,state,files_json) VALUES ('run','failed','{\"file_id\":\"old\"}')")
            self.retire(db)
        with self.assertRaises(IntegrityError),self.engine.begin() as db:
            db.exec_driver_sql("UPDATE runs SET state='queued' WHERE id='run'")

    def test_outputs_require_the_unified_verified_replacement(self):
        with self.engine.begin() as db:db.exec_driver_sql("UPDATE files SET kind='output' WHERE id='old'")
        with self.assertRaises(IntegrityError),self.engine.begin() as db:
            db.exec_driver_sql("DELETE FROM files WHERE id='old'")
        with self.engine.begin() as db:self.retire(db)
