import unittest
from remote_deploy import server_blocks,parse_env
class ConfigTests(unittest.TestCase):
 def test_only_matching_tls_server(self):
  conf='server { listen 443 ssl; server_name rizan-bridge.duckdns.org; }\nserver { listen 25345 ssl; server_name rizan-bridge.duckdns.org; location / { proxy_pass http://127.0.0.1:25346; } }'
  blocks=server_blocks(conf);self.assertEqual(len(blocks),1);pos=blocks[0][1];new=conf[:pos]+' include /etc/nginx/rizan-r3-locations.conf;\n'+conf[pos:];self.assertEqual(new.replace(' include /etc/nginx/rizan-r3-locations.conf;\n',''),conf)
 def test_comment_and_quoted_braces_do_not_confuse_parser(self):
  conf='# server { listen 25345; }\nserver { listen [::]:25345 ssl; server_name rizan-bridge.duckdns.org; add_header X "{braces}"; location / { return 200 "}"; } }'
  self.assertEqual(len(server_blocks(conf)),1)
 def test_wrong_host_not_selected(self):self.assertFalse(server_blocks('server { listen 25345 ssl; server_name other.example; }'))
 def test_no_shell_evaluation_of_env(self):
  env=parse_env('RIZAN_BRIDGE_TOKEN="literal$(must-not-execute)"\n# comment\nRIZAN_STATE_DB=state/file.sqlite # trailing comment\n')
  self.assertEqual(env['RIZAN_BRIDGE_TOKEN'],'literal$(must-not-execute)');self.assertEqual(env['RIZAN_STATE_DB'],'state/file.sqlite')
if __name__=='__main__':unittest.main()
