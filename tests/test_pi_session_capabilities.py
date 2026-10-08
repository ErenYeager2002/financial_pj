import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from app import pi_session_capabilities as module

class SessionCapabilityTests(unittest.TestCase):
    def project(self, record, run=(), upload=(), admin=False):
        user=SimpleNamespace(user_id='owner',department_id='dept',is_admin=admin)
        def allowed(db,current,capability='can_run'):
            return set(upload if capability=='can_upload' else run)
        with patch.object(module,'refresh_active_user',return_value=user), patch.object(module,'_session_record_for_owner',return_value=('session',None,record)) as owned, patch.object(module,'allowed_skill_ids',side_effect=allowed):
            result=module.session_capabilities(object(),user,'session')
            owned.assert_called_once_with('owner','dept','session')
            return result

    def test_general_session_does_not_require_all_installed_skills(self):
        result=self.project({})
        self.assertTrue(result['can_send']);self.assertTrue(result['can_upload'])
        self.assertEqual(set(result['rpc_commands']),set(module.RPC_COMMANDS))

    def test_revoked_binding_keeps_inspection_stop_and_negative_dialog_only(self):
        result=self.project({'skill_id':'alpha','skill_commit':'fixed'})
        for field in ('can_send','can_configure','can_start','can_upload','can_approve_input'):
            self.assertFalse(result[field])
        self.assertEqual(set(result['rpc_commands']),{'get_state','get_messages','abort','clear_queue','extension_ui_response'})
        self.assertNotIn('prompt',result['rpc_commands'])

    def test_upload_grant_does_not_imply_execution_and_execution_does_not_imply_upload(self):
        record={'skill_id':'alpha'}
        run=self.project(record,run=['native--alpha'])
        self.assertTrue(run['can_send']);self.assertFalse(run['can_upload'])
        upload=self.project(record,upload=['native--alpha'])
        self.assertFalse(upload['can_send']);self.assertFalse(upload['can_upload'])

    def test_every_explicit_binding_requires_grant(self):
        result=self.project({'mounted_skill_ids':['alpha','beta']},run=['native--alpha'],upload=['native--alpha','native--beta'])
        self.assertFalse(result['can_send']);self.assertFalse(result['can_upload'])

    def test_admin_uses_current_refreshed_identity(self):
        result=self.project({'skill_id':'alpha'},admin=True)
        self.assertTrue(result['can_send']);self.assertTrue(result['can_upload'])

    def test_disabled_account_and_foreign_session_are_not_projected(self):
        user=SimpleNamespace(user_id='owner',department_id='dept',is_admin=True)
        for target,code in (('refresh_active_user',403),('_session_record_for_owner',404)):
            with self.subTest(target=target), patch.object(module,'refresh_active_user',return_value=user), patch.object(module,target,side_effect=HTTPException(code)):
                with self.assertRaises(HTTPException) as raised: module.session_capabilities(object(),user,'session')
                self.assertEqual(raised.exception.status_code,code)

    def test_projection_does_not_export_identity_paths_tokens_or_install_all(self):
        result=self.project({'owner':'private','token':'private','workspace':'/secret','skill_id':'alpha'},admin=True)
        self.assertEqual(set(result),{'protocol','session_id','can_send','can_configure','can_start','can_upload','can_approve_input','rpc_commands','reason'})

if __name__=='__main__':unittest.main()
