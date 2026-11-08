"""Regression contract for cTrader Cloud's ephemeral LocalStorage semantics.

This is a static safety check; the native build separately checks C# API validity.
"""
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "source"

class CloudStorageGuard(unittest.TestCase):
    def test_cloud_mode_is_explicit_and_fails_closed_on_storage_exception(self):
        host = (SOURCE/"PortfolioHost.cs").read_text()
        self.assertIn("Application.EnvironmentType == EnvironmentType.Cloud", host)
        self.assertIn("if(exception is LocalStorageException)", host)
        self.assertIn("_runtimeStorageFault=true;", host)
        self.assertIn("STORAGE_GUARD_NEW_ENTRIES_BLOCKED", host)
        self.assertIn("!_runtimeStorageFault && Engines.Any()", host)
        self.assertIn("PORTFOLIO_LOCALSTORAGE_START_BLOCK", host)
        self.assertIn("if(IsCloudRuntime)", host)
        # Existing management methods must remain independent of entry guard.
        self.assertIn("return ModifyPosition(p,sl,tp,type);", host)
        self.assertIn("return ClosePosition(p);", host)

    def test_xau_eur_cloud_remotely_acknowledged_before_entries(self):
        for symbol in ("xau", "eur"):
            with self.subTest(symbol=symbol):
                source = (SOURCE/symbol/"RizanRobot.cs").read_text()
                self.assertIn("IsCloudRuntime ? null : LocalStorage.GetString(", source)
                self.assertIn("_localRevision=_state.Revision;", source)
                self.assertIn("if(IsCloudRuntime)", source)
                self.assertIn("if(!UsesBridge){_persistedRevision=_state.Revision;return;}", source)
                self.assertIn("_persistedRevision>=_state.Revision", source)
                self.assertIn("LOCAL_CHECKPOINT_WRITE_FAILED", source)
                self.assertIn("_lastLocalCheckpointJson", source)
                self.assertIn("if(LocalStorage.GetString(_storageKey,LocalStorageScope.Instance)!=json)", source)
                self.assertIn("ReconcileExposure();Changed();Persist();", source)

    def test_btc_cloud_remote_ack_intents_and_exit_management_preserved(self):
        source=(SOURCE/"BtcEngine.cs").read_text()
        host=(SOURCE/"PortfolioHost.cs").read_text()
        lifecycle=(SOURCE/"BtcNativeLifecycle.cs").read_text()
        self.assertIn("if(!IsCloudRuntime){", source)
        self.assertIn("IsCloudRuntime ? null : LocalStorage.GetString(", source)
        self.assertIn("link?.Changed(state.Revision,value);", source)
        self.assertIn("link.Persisted(state.Revision)", source)
        self.assertIn("ReconcileNativeBatch()", source)
        self.assertIn("Btc?.Manage(Server.TimeInUtc)", host)
        self.assertIn("if(!link.Persisted(state.Revision))return false;", lifecycle)

if __name__ == "__main__":
    unittest.main()
