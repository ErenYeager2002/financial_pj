"""Public route regression: reject malformed controls before provisioning or dispatch."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers import pi_runtime as route

class PublicOperationRouteTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(route.router)
        app.dependency_overrides[route.get_current_user] = lambda: SimpleNamespace(user_id='synthetic', department_id='synthetic', is_admin=False)
        app.dependency_overrides[route.get_db] = lambda: object()
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_invalid_jobs_discriminator_is_validation_error_not_server_error(self):
        for value in ([], {}, ['cancel'], {'operation':'cancel'}):
            with self.subTest(value=value), patch.object(route.runtime, 'operate') as dispatch:
                response = self.client.post('/api/pi-runtime/sessions/synthetic/operate',json={'operation':'jobs','payload':{'operation':value}})
                self.assertEqual(response.status_code,422,response.text)
                dispatch.assert_not_called()

    def test_invalid_start_is_rejected_before_any_provisioning(self):
        with patch.object(route.runtime,'require_session') as owner, patch.object(route.runtime,'operate') as dispatch:
            response = self.client.post('/api/pi-runtime/sessions/synthetic/operate',json={'operation':'start','payload':{'owner':'forged','mode':'rpc'}})
            self.assertEqual(response.status_code,422,response.text)
            owner.assert_not_called()
            dispatch.assert_not_called()

    def test_supported_read_only_operation_uses_same_service(self):
        with patch.object(route.runtime,'operate',return_value={'items':[]}) as dispatch:
            response=self.client.post('/api/pi-runtime/sessions/synthetic/operate',json={'operation':'jobs','payload':{'operation':'list'}})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json(),{'items':[]})
            self.assertEqual(dispatch.call_args.args[1:4],('synthetic','jobs',{'operation':'list'}))

    def test_capability_route_uses_authenticated_context_and_preserves_denial(self):
        from app import pi_session_capabilities as capabilities
        expected={'protocol':'pi-session-capabilities-v1','session_id':'synthetic','can_send':False}
        with patch.object(capabilities,'session_capabilities',return_value=expected) as project:
            response=self.client.get('/api/pi-runtime/sessions/synthetic/capabilities')
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json(),expected)
            self.assertEqual(project.call_args.args[1].user_id,'synthetic')
            self.assertEqual(project.call_args.args[2],'synthetic')
        with patch.object(capabilities,'session_capabilities',side_effect=__import__('fastapi').HTTPException(404)):
            self.assertEqual(self.client.get('/api/pi-runtime/sessions/other/capabilities').status_code,404)

if __name__ == '__main__': unittest.main()
