import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('collector',Path(__file__).with_name('collect_broker.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class GuardTests(unittest.TestCase):
    def test_all_trading_and_refresh_requests_denied(self):
        for name in ['ProtoOANewOrderReq','ProtoOAClosePositionReq','ProtoOACancelOrderReq',
                     'ProtoOAAmendOrderReq','ProtoOAAmendPositionSLTPReq','ProtoOARefreshTokenReq']:
            with self.subTest(name=name),self.assertRaisesRegex(RuntimeError,'NON_READ_REQUEST_BLOCKED'):
                module.guard(type(name,(),{})())
    def test_read_requests_allowed(self):
        for name in ['ProtoOAGetTrendbarsReq','ProtoOAOrderListReq','ProtoOADealListReq']:
            module.guard(type(name,(),{})())
    def test_recursive_account_identifier_removal(self):
        self.assertEqual(module.sanitize({'nested':[{'ctidTraderAccountId':'123','orderId':'456'}]}),
                         {'nested':[{'orderId':'456'}]})
if __name__=='__main__':unittest.main()
