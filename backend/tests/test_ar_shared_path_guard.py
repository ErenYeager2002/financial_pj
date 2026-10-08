"""A writable AR workbook is occupied by path identity across Skill aliases."""

import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ar_execution_safety import current_material_blocker
from app.models import Base, FileRecord, WorkflowMaterialSet, WorkflowMaterialSetFile, WorkflowSession


class SharedPathGuardTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        for identity, path in (('current-file', '/controlled/shared.xlsx'),
                               ('alias-file', '/controlled/shared.xlsx')):
            self.db.add(FileRecord(
                id=identity, owner_id='owner', department_id='finance',
                kind='input', original_name=identity + '.xlsx', stored_path=path,
                size_bytes=1, sha256='a' * 64,
            ))
        self.current = WorkflowMaterialSet(
            id='current', owner_id='owner', department_id='finance',
            skill_id='ar-hexiao-daily-lab', version=1, source_workflow_id='', state='current',
        )
        self.alias = WorkflowMaterialSet(
            id='alias', owner_id='owner', department_id='finance',
            skill_id='ar-hexiao-daily', version=1, source_workflow_id='', state='current',
        )
        self.db.add_all([
            self.current,
            self.alias,
            WorkflowMaterialSetFile(id='current-member', material_set=self.current,
                role='receipt_flow_table', year=0, file_id='current-file', sha256='a' * 64),
            WorkflowMaterialSetFile(id='alias-member', material_set=self.alias,
                role='receipt_flow_table', year=0, file_id='alias-file', sha256='a' * 64),
        ])
        self.workflow = WorkflowSession(
            id='alias-workflow', display_id='AR-Alias', owner_id='owner',
            owner_name='Tester', department_id='finance', skill_id='ar-hexiao-daily',
            skill_name='AR', skill_version='1', execution_mode='workflow',
            skill_hash='hash', model_connection_id='', model_provider='', model_name='',
            state='failed', stage='failed', reconciliation_date='2026-08-30',
            material_set_id=self.alias.id,
            context_json=json.dumps({'ar_execution': {
                'material_set_id': self.alias.id, 'material_version': 1,
                'publication': 'not_published', 'completed': ['write_ledger'],
            }}),
        )
        self.db.add(self.workflow)
        self.db.commit()

    def blocker(self):
        return current_material_blocker(self.db, 'owner', 'finance', self.current.skill_id)

    def test_same_path_different_file_records_blocks_unpublished_write(self):
        self.assertEqual(self.blocker()['workflow_id'], self.workflow.id)
        self.db.get(FileRecord, 'alias-file').stored_path = '/controlled/different.xlsx'
        self.db.commit()
        self.assertIsNone(self.blocker())

    def test_missing_current_file_identity_fails_closed(self):
        self.db.get(FileRecord, 'current-file').stored_path = ''
        self.db.commit()
        self.assertEqual(self.blocker()['reason'], 'material_file_identity_incomplete')


if __name__ == '__main__':
    unittest.main()
