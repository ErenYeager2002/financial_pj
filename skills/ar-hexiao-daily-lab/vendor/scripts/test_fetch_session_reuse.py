import io,json,unittest
from unittest.mock import patch
import fetch_secure,fetch_zhiyun

class BatchLoginReuse(unittest.TestCase):
    def invoke(self, account='synthetic-user', fail_day=None, login_error=False):
        payload=dict(account=account,password='synthetic-password',date_from='2026-08-25',date_to='2026-08-26',workspace='/tmp/test-fetch')
        seen=[]
        def day(args):
            parsed=dict(zip(args[::2],args[1::2]))
            if parsed['--date']==fail_day:return 2
            seen.append(fetch_zhiyun.login_with_password('https://example.invalid',account,'synthetic-password'))
            return 0
        original=fetch_zhiyun.login_with_password
        with patch.object(fetch_secure,'_edge_login',side_effect=RuntimeError('test') if login_error else None,return_value=('token','account')) as login, patch.object(fetch_zhiyun,'main',side_effect=day), patch('sys.stdin',io.StringIO(json.dumps(payload))):
            if login_error:
                with self.assertRaises(RuntimeError):fetch_secure.main()
                result=None
            else:result=fetch_secure.main()
        return result,login.call_count,seen,original
    def test_batch_logs_in_once(self):
        result,calls,seen,_=self.invoke();self.assertEqual(result,0);self.assertEqual(calls,1);self.assertEqual(seen,[('token','account')]*2)
    def test_next_invocation_does_not_reuse_prior_login(self):
        a=self.invoke('first');b=self.invoke('second');self.assertEqual((a[1],b[1]),(1,1))
    def test_login_hook_is_restored(self):
        original=fetch_zhiyun.login_with_password;self.invoke();self.assertIs(fetch_zhiyun.login_with_password,original)
    def test_failed_day_stops_batch(self):
        result,calls,seen,_=self.invoke(fail_day='2026-08-26');self.assertEqual(result,2);self.assertEqual(calls,1);self.assertEqual(len(seen),1)
    def test_error_restores_hook_without_retry(self):
        original=fetch_zhiyun.login_with_password;_,calls,_,_=self.invoke(login_error=True);self.assertEqual(calls,1);self.assertIs(fetch_zhiyun.login_with_password,original)
if __name__=='__main__':unittest.main()
