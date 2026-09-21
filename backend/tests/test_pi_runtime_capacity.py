import unittest
from unittest.mock import patch
import httpx
from fastapi import HTTPException
from app import pi_runtime_service as runtime

class CapacityMessageTests(unittest.TestCase):
    def test_capacity_error_remains_actionable_and_private(self):
        with patch.object(runtime.httpx, 'Client') as client:
            client.return_value.__enter__.return_value.post.return_value = httpx.Response(429, json={'detail': 'private container diagnostics'})
            with self.assertRaises(HTTPException) as caught:
                runtime._request_runtime({})
        self.assertEqual(caught.exception.status_code, 429)
        self.assertIn('运行环境名额已满', caught.exception.detail)
        self.assertNotIn('private', caught.exception.detail)

    def test_unknown_error_does_not_leak_manager_details(self):
        with patch.object(runtime.httpx, 'Client') as client:
            client.return_value.__enter__.return_value.post.return_value = httpx.Response(500, json={'detail': 'private diagnostics'})
            with self.assertRaises(HTTPException) as caught:
                runtime._request_runtime({})
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn('private', caught.exception.detail)

if __name__ == '__main__': unittest.main()
