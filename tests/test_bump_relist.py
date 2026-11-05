"""Relisting, bump cooldowns and recovery after a lost response."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

import test_engine as fixtures
from clients import ServiceError
from vault import protect, unprotect


class OwnListingUpdateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowTests(methodName="runTest")
        self.fixture.setUp()
        self.engine = self.fixture.engine
        self.backpack = self.fixture.backpack
        self.remote = [dict(asset_id="100", listing_id="440_100", intent="sell", status="active", source="user",
                            currencies={"keys": 1, "metal": 1}, details="Old description")]
        self.backpack.listings.side_effect = lambda: copy.deepcopy(self.remote)
        self.backpack.update.side_effect = self.update_remotely

    def tearDown(self):
        self.fixture.tearDown()

    def update_remotely(self, listing_id, keys, metal_scrap, details):
        self.remote[0]["currencies"] = {"keys": keys, "metal": metal_scrap * 100 // 9 / 100}
        self.remote[0]["details"] = details
        return copy.deepcopy(self.remote[0])

    def current(self):
        return self.engine.store.get("listings", "100")

    def test_relist_updates_exact_listing_without_delete_create_or_inventory_refresh(self):
        self.engine.relist("100", "2", "1.11", "New description")
        self.backpack.update.assert_called_once_with("440_100", 2, 10, "New description")
        row = self.current()
        self.assertEqual((row["status"], row["keys"], row["metal_scrap"], row["details"]),
                         ("active", 2, 10, "New description"))
        self.assertNotIn("update_target", row)
        self.backpack.delete.assert_not_called()
        self.backpack.create.assert_not_called()
        self.fixture.steam.inventory.assert_not_called()

    def test_patch_response_lost_after_success_recovers_by_one_read_without_repeating_patch(self):
        def lost(*args):
            self.assertEqual(self.current()["status"], "updating")
            self.update_remotely(*args)
            raise ServiceError("lost response", uncertain=True)
        self.backpack.update.side_effect = lost
        self.engine.relist("100", "2", "1", "New description")
        self.assertEqual(self.current()["status"], "active")
        self.assertEqual(self.current()["keys"], 2)
        self.backpack.update.assert_called_once()
        self.assertEqual(self.backpack.listings.call_count, 2)

    def test_unknown_update_survives_restart_then_read_resolves_it_without_replay(self):
        self.backpack.listings.side_effect = [copy.deepcopy(self.remote), ServiceError("read unavailable")]
        with self.assertRaises(ServiceError):
            self.engine.relist("100", "2", "1", "New description")
        self.assertEqual(self.current()["status"], "update_unknown")
        self.fixture.reopen()
        self.engine = self.fixture.engine
        self.backpack.listings.side_effect = lambda: copy.deepcopy(self.remote)
        self.engine.reconcile_listings()
        self.assertEqual(self.current()["status"], "active")
        self.assertEqual(self.current()["keys"], 2)
        self.backpack.update.assert_called_once()

    def test_server_old_price_is_not_reported_as_success(self):
        self.backpack.update.side_effect = ServiceError("rejected")
        with self.assertRaises(ServiceError):
            self.engine.relist("100", "2", "1", "New description")
        self.assertEqual(self.current()["status"], "active")
        self.assertEqual(self.current()["keys"], 1)
        self.backpack.update.assert_called_once()

    def test_explicitly_cleared_description_is_not_restored_from_old_listing(self):
        self.engine.relist("100", "2", "1", "")
        self.backpack.update.assert_called_once_with("440_100", 2, 9, "")
        self.assertEqual(self.current()["details"], "")

    def test_pending_offer_without_legacy_reservation_blocks_all_listing_writes(self):
        self.engine.store.put("offers", "pending", dict(offer_id="pending", status="accept_unknown", asset_ids=["100"]))
        for method, args in ((self.engine.relist, ("100", "2", "1")),
                             (self.engine.publish, ("100", "2", "1")),
                             (self.engine.remove_listing, ("100",))):
            with self.assertRaises(ValueError):
                method(*args)
        self.backpack.listings.assert_not_called()
        self.backpack.update.assert_not_called()
        self.backpack.delete.assert_not_called()
        self.backpack.create.assert_not_called()

    def test_removed_item_is_explicitly_published_again_with_fresh_inventory(self):
        self.remote.clear()
        self.fixture.steam.inventory.return_value = {"success": 1, "assets": [fixtures.asset(100)],
                                                    "descriptions": [fixtures.description(200)]}
        self.backpack.create.return_value = dict(listing_id="440_100", asset_id="100")
        self.engine.relist("100", "2", "1", "New description")
        self.backpack.create.assert_called_once()
        self.fixture.steam.inventory.assert_called_once()
        self.backpack.update.assert_not_called()


class BumpAndPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowTests(methodName="runTest")
        self.fixture.setUp()
        self.engine = self.fixture.engine
        self.backpack = self.fixture.backpack
        self.backpack.pulse.return_value = {}

    def tearDown(self):
        self.fixture.tearDown()

    def test_disabled_bump_is_read_only_and_does_not_start_other_services(self):
        self.engine._bump_tick()
        self.backpack.listings.assert_not_called()
        self.backpack.pulse.assert_not_called()
        self.fixture.steam.inventory.assert_not_called()

    def test_cooldown_is_written_before_post_and_manual_click_cannot_repeat_it(self):
        def pulse():
            state = self.engine.bump_status()
            self.assertEqual(state["status"], "sending")
            self.assertEqual(state["next_allowed_at"], 11800)
            return {}
        self.backpack.pulse.side_effect = pulse
        with patch("engine.time.time", return_value=10000):
            result = self.engine.bump_now()
            with self.assertRaises(ServiceError) as caught:
                self.engine.bump_now()
        self.assertIn("Запрос бампа", result)
        self.assertEqual(caught.exception.retry_after, 1801)
        self.backpack.pulse.assert_called_once()
        self.backpack.listings.assert_called_once()
        self.assertFalse(self.engine.monitoring)

    def test_automatic_bump_only_repeats_after_due_and_never_loads_inventory(self):
        self.engine.save_settings(dict(bump_enabled=True, bump_interval=30))
        with patch("engine.time.time", return_value=10000):
            self.engine._bump_tick()
        with patch("engine.time.time", return_value=11799):
            self.engine._bump_tick()
        self.backpack.pulse.assert_called_once()
        with patch("engine.time.time", return_value=11800):
            self.engine._bump_tick()
        self.assertEqual(self.backpack.pulse.call_count, 2)
        self.fixture.steam.inventory.assert_not_called()
        self.fixture.steam.offers.assert_not_called()

    def test_steam_api_error_does_not_prevent_due_automatic_bump(self):
        self.engine.save_settings(dict(bump_enabled=True, bump_interval=30))
        self.engine.monitoring = True
        self.fixture.steam.offers.side_effect = ServiceError("Steam temporarily unavailable")
        engine = self.engine
        class TwoWakeups:
            count = 0
            def wait(self, timeout=None):
                self.count += 1
                if self.count > 1:
                    engine.closed = True
            def clear(self):
                pass
            def set(self):
                pass
        engine.wakeup = TwoWakeups()
        with patch("engine.time.time", return_value=10000):
            fixtures.ENGINE_RUN(engine)
        self.backpack.pulse.assert_called_once()
        self.assertTrue(engine.monitoring)

    def test_429_retry_after_is_persisted_across_restart(self):
        self.engine.save_settings(dict(bump_enabled=True, bump_interval=30))
        self.backpack.pulse.side_effect = ServiceError("backpack.tf: HTTP 429", status_code=429, retry_after=7200)
        with patch("engine.time.time", return_value=10000):
            with self.assertRaises(ServiceError):
                self.engine.bump_now()
        self.assertEqual(self.engine.bump_status()["next_allowed_at"], 17200)
        self.fixture.reopen()
        self.engine = self.fixture.engine
        with patch("engine.time.time", return_value=15000):
            self.engine._bump_tick()
        self.backpack.pulse.assert_called_once()

    def test_empty_account_waits_between_reads_instead_of_polling_each_second(self):
        self.engine.save_settings(dict(bump_enabled=True, bump_interval=30))
        self.backpack.listings.side_effect = None
        self.backpack.listings.return_value = []
        with patch("engine.time.time", return_value=10000):
            self.engine._bump_tick()
        with patch("engine.time.time", return_value=10001):
            self.engine._bump_tick()
        self.backpack.listings.assert_called_once()
        self.backpack.pulse.assert_not_called()

    def test_uncertain_post_retains_cooldown_and_cannot_replay_on_restart(self):
        self.engine.save_settings(dict(bump_enabled=True, bump_interval=30))
        self.backpack.pulse.side_effect = ServiceError("network unavailable", uncertain=True)
        with patch("engine.time.time", return_value=10000):
            with self.assertRaises(ServiceError):
                self.engine.bump_now()
        self.assertEqual(self.engine.bump_status()["status"], "unknown")
        self.fixture.reopen()
        self.engine = self.fixture.engine
        with patch("engine.time.time", return_value=10001):
            self.engine._bump_tick()
        self.backpack.pulse.assert_called_once()

    def test_preference_changes_preserve_clients_and_unrelated_configuration(self):
        self.engine._config["steam_api_key"] = "an unrelated unsaved value"
        self.engine._agent_registered = True
        self.engine.on_event = Mock()
        self.fixture.steam.close.reset_mock()
        self.backpack.close.reset_mock()
        result = self.engine.set_preferences(language="en", theme="dark")
        self.assertEqual(result, dict(language="en", theme="dark"))
        self.assertEqual(self.engine.settings()["steam_api_key"], "an unrelated unsaved value")
        self.fixture.steam.close.assert_not_called()
        self.backpack.close.assert_not_called()
        self.backpack.stop.assert_not_called()
        saved = json.loads(unprotect((self.engine.root / "settings.bin").read_bytes()))
        self.assertEqual(saved["language"], "en")
        self.assertEqual(saved["theme"], "dark")
        self.engine.on_event.assert_called_once_with("preferences_changed", dict(language="en", theme="dark"))

    def test_disabling_auto_bump_unregisters_only_the_running_agent(self):
        self.engine.save_settings(dict(bump_enabled=True))
        with patch("engine.time.time", return_value=10000):
            self.engine.bump_now()
        self.engine.save_settings(dict(bump_enabled=False))
        self.backpack.stop.assert_called_once()
        self.assertFalse(self.engine._agent_registered)

    def test_bad_preference_never_changes_persisted_settings(self):
        before = (self.engine.root / "settings.bin").read_bytes()
        for values in (dict(language="xx"), dict(theme="system")):
            with self.assertRaises(ValueError):
                self.engine.set_preferences(**values)
        self.assertEqual((self.engine.root / "settings.bin").read_bytes(), before)

    def test_old_competition_preferences_and_cached_results_are_removed(self):
        cfg = self.engine.settings()
        cfg.update(market_enabled=True, market_interval=1, inventory_proxy1="old-value")
        (self.engine.root / "settings.bin").write_bytes(protect(json.dumps(cfg).encode()))
        self.engine.store.put("meta", "market:100", dict(undercut=True))
        self.fixture.reopen()
        self.engine = self.fixture.engine
        self.assertNotIn("market_enabled", self.engine.settings())
        self.assertNotIn("inventory_proxy1", self.engine.settings())
        self.assertIsNone(self.engine.store.get("meta", "market:100"))
        self.assertFalse(hasattr(self.engine, "market_feed"))
        self.assertFalse(hasattr(self.engine, "refresh_market"))

    def test_telegram_is_translated_only_when_sent_keeping_canonical_storage(self):
        self.engine.set_preferences(language="en")
        self.engine._queue_notice("test-locale", "Обмен успешно завершён в Steam.",
                                  [[dict(text="Открыть обмен в Steam", url="https://steamcommunity.com/tradeoffer/1/")]])
        self.engine._flush_notices()
        self.assertEqual(self.engine.store.get("outbox", "test-locale")["text"], "Обмен успешно завершён в Steam.")
        text, buttons = self.fixture.telegram.send.call_args.args
        self.assertNotIn("Обмен", text)
        self.assertNotIn("Открыть", buttons[0][0]["text"])
        self.assertEqual(buttons[0][0]["url"], "https://steamcommunity.com/tradeoffer/1/")
