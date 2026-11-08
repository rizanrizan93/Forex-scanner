import unittest
from provision_isolated import tls_server_close,mask_config
class RoutingSafety(unittest.TestCase):
 def test_only_correct_server(self):
  t='server { listen 443 ssl; } server { listen 25345 ssl; location / { proxy_pass http://127.0.0.1:1; } }';self.assertEqual(t[tls_server_close(t)],'}');self.assertGreater(tls_server_close(t),t.index('25345'))
 def test_strings_and_comments_do_not_change_braces(self):
  t='server { listen 25345 ssl; # }\n set $x "{"; location / { } }';self.assertEqual(tls_server_close(t),len(t)-1)
 def test_ambiguous_server_rejected(self):
  with self.assertRaises(RuntimeError):tls_server_close('server { listen 25345; } server { listen 25345; }')
 def test_unrelated_port(self):self.assertIsNone(tls_server_close('server { listen 443; }'))
if __name__=='__main__':unittest.main()
