"""Saved sessions, inventory refresh and settings migration."""
import unittest
from unittest.mock import patch
import test_engine as fixtures


class SessionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowTests(methodName="runTest")
        self.fixture.setUp()
        self.engine, self.steam = self.fixture.engine, self.fixture.steam
        self.steam.inventory.return_value = {"success": 1, "assets": [fixtures.asset(100)],
                                            "descriptions": [fixtures.description(200)]}

    def tearDown(self):
        self.fixture.tearDown()

    def test_login_loads_inventory_once(self):
        self.steam.login.return_value = {"ok": True, "steam_id": fixtures.OWNER}
        self.assertTrue(self.engine.login()["inventory_loaded"])
        self.assertEqual(len(self.engine.store.inventory_rows()), 1)
        self.steam.inventory.assert_called_once_with()

    def test_startup_without_session_never_fetches_inventory(self):
        self.steam.has_session.return_value = False
        self.assertFalse(self.engine.ensure_inventory())
        self.steam.inventory.assert_not_called()

    def test_monitor_wakeups_do_not_refresh_inventory(self):
        engine = self.engine
        class Wakeups:
            count = 0
            def wait(self, timeout=None):
                self.count += 1
                if self.count > 2:
                    engine.closed = True
            def clear(self):
                pass
            def set(self):
                pass
        engine.wakeup = Wakeups()
        with patch.object(engine, "ensure_inventory") as load:
            fixtures.ENGINE_RUN(engine)
        load.assert_not_called()
        self.steam.inventory.assert_not_called()

    def test_sold_item_hidden_even_if_steam_inventory_cache_lags(self):
        row = self.engine.store.get("listings", "100")
        row["status"] = "sold"
        self.engine.store.put("listings", "100", row)
        self.engine.refresh_inventory()
        self.assertFalse(self.engine.store.inventory_rows())

    def test_completed_trade_removes_local_item_without_loading_inventory(self):
        self.engine.monitoring = True
        self.steam.accept.side_effect = self.fixture.complete_accept
        self.fixture.record()
        self.assertIsNone(self.engine.store.get("inventory", "100"))
        self.steam.inventory.assert_not_called()

    def test_payment_summary_counts_refined_and_keys(self):
        offer = fixtures.offer()
        offer["items_to_receive"] = [fixtures.asset(500, "5021")] + [fixtures.asset(600+i, "5002") for i in range(15)]
        summary = self.engine._summary(offer, offer["_descriptions"])
        self.assertIn("Mann Co. Supply Crate Key × 1", summary)
        self.assertIn("Refined Metal × 15", summary)
        self.assertEqual(summary.count("Refined Metal"), 1)
        self.assertNotIn("AssetID", summary)

    def test_visible_legacy_messages_migrate_without_changing_decision(self):
        old = self.fixture.record()
        self.engine.store.log("Предмет AssetID 100 выставлен; 9 scrap")
        listing = self.engine.store.get("listings", "100")
        listing["details"] = "Selling hat. AssetID: 100"
        self.engine.store.put("listings", "100", listing)
        self.fixture.reopen()
        self.engine = self.fixture.engine
        self.assertEqual(self.engine.store.get("offers", "9988")["fingerprint"], old["fingerprint"])
        visible = str(self.engine.store.logs()) + self.engine.store.get("listings", "100")["details"] + self.engine.store.get("offers", "9988")["summary"]
        self.assertNotIn("AssetID", visible)
        self.assertNotIn("scrap", visible)
