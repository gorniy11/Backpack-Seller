"""Trade workflows with a temporary database and mocked services."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clients import ServiceError
from domain import offer_fingerprint
from engine import SellerEngine
from vault import unprotect, protect

OWNER = "76561198000000000"
ENGINE_RUN = SellerEngine._run


def asset(asset_id, class_id="200"):
    return {"assetid": str(asset_id), "classid": str(class_id), "instanceid": "0",
            "appid": 440, "contextid": "2", "amount": "1"}


def description(defindex, class_id=None):
    return {"appid": 440, "classid": str(class_id or defindex), "instanceid": "0", "tradable": 1,
            "app_data": {"def_index": str(defindex), "quality": "6"}, "descriptions": [],
            "name": {5021: "Mann Co. Supply Crate Key", 5002: "Refined Metal"}.get(defindex, "Hat")}


def offer(offer_id="9988", state=2):
    return {"tradeofferid": offer_id, "accountid_other": 1234, "is_our_offer": False,
            "trade_offer_state": state, "items_to_give": [asset(100)],
            "items_to_receive": [asset(500, "5021"), asset(501, "5002")],
            "_descriptions": [description(200), description(5021), description(5002)]}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.steam = MagicMock()
        self.backpack = MagicMock()
        self.telegram = MagicMock()
        self.patchers = [patch("engine.SteamClient", return_value=self.steam),
                         patch("engine.BackpackClient", return_value=self.backpack),
                         patch("engine.TelegramClient", return_value=self.telegram),
                         patch.object(SellerEngine, "_run", return_value=None)]
        for patcher in self.patchers:
            patcher.start()
        self.engine = SellerEngine(self.root)
        self.engine.worker.join(2)
        self.engine.save_settings({"steam_id": OWNER, "steam_api_key": "A" * 32,
                                   "backpack_token": "private-backpack-token", "telegram_token": "123:abc",
                                   "telegram_chat_id": "1234", "telegram_user_id": "1234"})
        self.engine.store.put("inventory", "100", {"asset_id": "100", "name": "Painted Hat", "tradable": True, "amount": "1"})
        self.engine.store.put("listings", "100", {"asset_id": "100", "name": "Painted Hat", "status": "active",
                                                   "keys": 1, "metal_scrap": 9, "version": 1,
                                                   "listing_id": "440_100"})
        self.live_offers = {"9988": offer()}
        self.steam.offer.side_effect = lambda value: copy.deepcopy(self.live_offers[str(value)])
        self.steam.offers.side_effect = lambda: [copy.deepcopy(value) for value in self.live_offers.values()]
        self.steam.accept.return_value = {}
        self.steam.inventory.return_value = {"assets": [], "descriptions": [description(200), description(5021), description(5002)]}
        self.backpack.listings.side_effect = self.remote_listings
        self.telegram.send.return_value = {"message_id": 555}
        self.telegram.poll.return_value = []

    def tearDown(self):
        self.engine.close()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def remote_listings(self):
        return [{"listing_id": row["listing_id"], "asset_id": row["asset_id"], "intent": "sell",
                 "currencies": {"keys": row["keys"], "metal": row["metal_scrap"] // 9}}
                for row in self.engine.store.listings() if row["status"] in {"active", "external_change"}]

    def record(self, offer_id="9988"):
        self.engine._record_offer(copy.deepcopy(self.live_offers[offer_id]))
        return self.engine.store.get("offers", offer_id)

    def complete_accept(self, fresh):
        self.live_offers[str(fresh["tradeofferid"])]["trade_offer_state"] = 3
        return {"tradeid": "123456"}

    def request_confirmation(self, fresh):
        self.live_offers[str(fresh["tradeofferid"])]["trade_offer_state"] = 9
        return {"needs_mobile_confirmation": True}

    def reopen(self):
        self.engine.close()
        self.engine = SellerEngine(self.root)
        self.engine.worker.join(2)

    def test_settings_use_windows_user_encryption(self):
        raw = (self.root / "settings.bin").read_bytes()
        self.assertNotIn(b"private-backpack-token", raw)
        self.assertNotIn(b"123:abc", raw)
        decoded = json.loads(unprotect(raw))
        self.assertEqual(decoded["steam_id"], OWNER)
        self.assertEqual(decoded["backpack_token"], "private-backpack-token")

    def test_retired_guard_and_item_controls_are_removed_from_saved_data(self):
        cfg = self.engine.settings()
        cfg.update(identity_secret="old-private-value", device_id="old-device", confirmation_mode="secret", global_auto_accept=True, telegram_enabled=False)
        (self.root / "settings.bin").write_bytes(protect(json.dumps(cfg).encode()))
        listing = self.engine.store.get("listings", "100")
        listing["auto_accept"] = True
        self.engine.store.put("listings", "100", listing)
        self.engine.store.put("meta", "item_auto:100", True)
        row = self.record()
        row.update(token="old-button-token", expires=99999999999, message_id=2)
        self.engine.store.put("offers", "9988", row)
        self.reopen()
        cfg = json.loads(unprotect((self.root / "settings.bin").read_bytes()))
        self.assertFalse({"identity_secret", "device_id", "confirmation_mode", "global_auto_accept", "telegram_enabled"} & cfg.keys())
        self.assertNotIn("auto_accept", self.engine.store.get("listings", "100"))
        self.assertIsNone(self.engine.store.get("meta", "item_auto:100"))
        self.assertNotIn("token", self.engine.store.get("offers", "9988"))
        self.assertFalse(hasattr(self.engine, "import_mafile"))
        self.assertFalse(hasattr(self.engine, "set_item_auto"))
        self.assertFalse(hasattr(self.engine, "_callback"))

    def test_monitored_valid_offer_accepts_and_requests_manual_steam_confirmation(self):
        self.engine.monitoring = True
        self.steam.accept.side_effect = self.request_confirmation
        row = self.record()
        self.assertEqual(row["status"], "needs_confirmation")
        self.steam.accept.assert_called_once()
        self.assertGreaterEqual(self.backpack.listings.call_count, 2)
        args = self.telegram.send.call_args.args
        self.assertIn("Painted Hat", args[0])
        self.assertIn("Mann Co. Supply Crate Key × 1", args[0])
        self.assertIn("Refined Metal × 1", args[0])
        self.assertIn("backpack.tf", args[0])
        self.assertIn("Подтвердите обмен вручную в Steam", args[0])
        self.assertNotIn("SDA", args[0])
        self.assertEqual(args[1][0][0]["text"], "Открыть обмен в Steam")
        self.assertTrue(args[1][0][0]["url"].endswith("/9988/"))
        self.assertNotIn("callback_data", args[1][0][0])
        self.steam.confirm.assert_not_called()
        self.record()
        self.assertEqual(self.telegram.send.call_count, 1)
        self.assertEqual(self.steam.accept.call_count, 1)

    def test_stopped_monitor_never_submits_new_acceptance(self):
        row = self.record()
        self.assertEqual(row["status"], "waiting")
        with self.assertRaises(ValueError):
            self.engine.accept("9988")
        self.steam.accept.assert_not_called()
        self.telegram.send.assert_not_called()

    def test_invalid_payment_not_accepted_or_declined_but_explained_in_telegram(self):
        self.engine.monitoring = True
        self.live_offers["9988"]["items_to_receive"].pop()
        row = self.record()
        self.assertEqual(row["status"], "blocked")
        self.steam.accept.assert_not_called()
        self.steam.decline.assert_not_called()
        self.assertIn("Обмен не принят", self.telegram.send.call_args.args[0])
        self.assertIn("Mann Co. Supply Crate Key × 1", self.telegram.send.call_args.args[0])
        self.assertIn(row["reason"], self.telegram.send.call_args.args[0])
        self.record()
        self.assertEqual(self.telegram.send.call_count, 1)

    def test_remote_listing_price_change_never_accepts_old_price(self):
        self.engine.monitoring = True
        self.backpack.listings.side_effect = None
        self.backpack.listings.return_value = [{"listing_id": "440_100", "asset_id": "100", "intent": "sell", "currencies": {"keys": 2, "metal": 1}}]
        row = self.record()
        self.assertEqual(row["status"], "blocked")
        self.steam.accept.assert_not_called()
        current = self.engine.store.get("listings", "100")
        self.assertEqual(current["status"], "active")
        self.assertEqual(current["keys"], 2)

    def test_removed_remote_listing_blocks_acceptance(self):
        self.engine.monitoring = True
        self.backpack.listings.side_effect = None
        self.backpack.listings.return_value = []
        self.assertEqual(self.record()["status"], "blocked")
        self.steam.accept.assert_not_called()

    def test_backpack_failure_does_not_trust_cached_listing(self):
        self.engine.monitoring = True
        self.backpack.listings.side_effect = ServiceError("backpack unavailable")
        row = self.record()
        self.assertEqual(row["status"], "blocked")
        self.assertIn("Не удалось сверить", row["reason"])
        self.steam.accept.assert_not_called()
        self.telegram.send.assert_called_once()

    def test_changed_steam_items_between_read_and_accept_never_accept(self):
        initial = copy.deepcopy(self.live_offers["9988"])
        self.engine.monitoring = True
        self.live_offers["9988"]["items_to_give"].append(asset(101))
        self.engine._record_offer(initial)
        self.assertEqual(self.engine.store.get("offers", "9988")["status"], "blocked")
        self.steam.accept.assert_not_called()

    def test_remote_change_during_final_accept_recheck_never_accepts(self):
        self.engine.monitoring = True
        correct = self.remote_listings()
        changed = copy.deepcopy(correct)
        changed[0]["currencies"]["keys"] = 2
        self.backpack.listings.side_effect = [correct, changed]
        self.assertEqual(self.record()["status"], "blocked")
        self.steam.accept.assert_not_called()

    def test_monitor_stopped_during_network_check_cancels_new_acceptance(self):
        self.engine.monitoring = True
        original = self.steam.offer.side_effect
        def stop_then_offer(offer_id):
            self.engine.monitoring = False
            return original(offer_id)
        self.steam.offer.side_effect = stop_then_offer
        self.record()
        self.steam.accept.assert_not_called()

    def test_reserved_asset_blocks_overlapping_sale(self):
        self.engine.monitoring = True
        self.record()
        self.assertEqual(self.engine.store.get("listings", "100")["reserved_by"], "9988")
        self.live_offers["9989"] = offer("9989")
        row = self.record("9989")
        self.assertEqual(row["status"], "blocked")
        self.assertIn("зарезервирован", row["reason"])
        self.assertEqual(self.steam.accept.call_count, 1)

    def test_uncertain_accept_never_retried_after_restart(self):
        self.engine.monitoring = True
        self.steam.accept.side_effect = ServiceError("Steam response lost", uncertain=True)
        self.assertEqual(self.record()["status"], "accept_unknown")
        self.reopen()
        self.engine.monitoring = True
        self.record()
        self.steam.accept.assert_called_once()
        self.assertEqual(self.engine.store.get("listings", "100")["reserved_by"], "9988")
        self.steam.confirm.assert_not_called()

    def test_crash_between_decision_and_post_recovers_without_resending(self):
        row = self.record()
        row.update(status="accepting")
        self.engine.store.put("offers", "9988", row)
        self.reopen()
        self.engine.monitoring = True
        self.assertEqual(self.record()["status"], "accept_unknown")
        self.steam.accept.assert_not_called()

    def test_manual_confirmation_required_state9_never_calls_confirmation_api(self):
        self.engine.monitoring = True
        self.record()
        self.live_offers["9988"]["trade_offer_state"] = 9
        self.record()
        self.record()
        self.steam.confirm.assert_not_called()
        self.assertEqual(self.engine.store.get("offers", "9988")["status"], "needs_confirmation")
        self.assertIsNone(self.engine.store.get("outbox", "success:9988"))
        self.assertIsNotNone(self.engine.store.get("outbox", "manual-confirm:9988"))

    def test_success_requires_state3_and_notice_is_idempotent(self):
        self.engine.monitoring = True
        self.record()
        self.assertIsNone(self.engine.store.get("outbox", "success:9988"))
        self.live_offers["9988"]["trade_offer_state"] = 11
        self.assertEqual(self.record()["status"], "in_escrow")
        self.assertIsNone(self.engine.store.get("outbox", "success:9988"))
        self.live_offers["9988"]["trade_offer_state"] = 3
        self.record()
        self.record()
        self.assertTrue(self.engine.store.get("offers", "9988")["success_recorded"])
        self.assertEqual(self.engine.store.get("listings", "100")["status"], "sold")
        notices = [r for r in self.engine.store.rows("outbox") if "успешно" in r["text"]]
        self.assertEqual(len(notices), 1)
        self.steam.accept.assert_called_once()
        self.steam.confirm.assert_not_called()

    def test_canceled_pending_trade_releases_reserved_asset_without_success(self):
        self.engine.monitoring = True
        self.record()
        self.live_offers["9988"]["trade_offer_state"] = 6
        self.record()
        self.assertEqual(self.engine.store.get("offers", "9988")["status"], "canceled")
        self.assertNotIn("reserved_by", self.engine.store.get("listings", "100"))
        self.assertIsNone(self.engine.store.get("outbox", "success:9988"))

    def test_stopped_monitor_still_finishes_pending_trade_without_new_decision(self):
        self.engine.monitoring = True
        self.record()
        self.live_offers["9988"]["trade_offer_state"] = 3
        self.engine.monitoring = False
        self.telegram.send.reset_mock()
        self.steam.offers.reset_mock()
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
        ENGINE_RUN(engine)
        self.assertEqual(engine.store.get("offers", "9988")["status"], "accepted")
        self.steam.offers.assert_not_called()
        self.steam.accept.assert_called_once()
        self.telegram.send.assert_called_once()

    def test_completed_trade_cancels_unsent_confirmation_notice(self):
        self.engine.monitoring = True
        self.telegram.send.side_effect = ServiceError("offline")
        self.steam.accept.side_effect = self.request_confirmation
        self.record()
        self.assertFalse(self.engine.store.get("outbox", "manual-confirm:9988")["sent"])
        self.live_offers["9988"]["trade_offer_state"] = 3
        self.record()
        self.assertTrue(self.engine.store.get("outbox", "manual-confirm:9988")["sent"])
        self.assertTrue(self.engine.store.get("outbox", "manual-confirm:9988")["canceled"])
        self.assertFalse(self.engine.store.get("outbox", "success:9988")["sent"])

    def test_acceptance_cancels_stale_blocked_notice_before_telegram_recovers(self):
        self.engine.monitoring = True
        self.telegram.send.side_effect = ServiceError("offline")
        complete_offer = copy.deepcopy(self.live_offers["9988"])
        self.live_offers["9988"]["items_to_receive"].pop()
        self.record()
        blocked = [row for row in self.engine.store.rows("outbox") if row["text"].startswith("Обмен не принят")]
        self.assertEqual(len(blocked), 1)
        self.assertFalse(blocked[0]["sent"])
        self.live_offers["9988"] = complete_offer
        self.steam.accept.side_effect = self.request_confirmation
        self.record()
        canceled = [row for row in self.engine.store.rows("outbox") if row["text"].startswith("Обмен не принят")]
        self.assertTrue(canceled[0]["canceled"])
        self.assertTrue(canceled[0]["sent"])
        self.telegram.send.side_effect = None
        self.telegram.send.reset_mock()
        self.engine._flush_notices()
        self.assertEqual(self.telegram.send.call_count, 1)
        self.assertIn("Подтвердите обмен вручную", self.telegram.send.call_args.args[0])

    def test_terminal_offer_cancels_stale_blocked_notice(self):
        self.engine.monitoring = True
        self.telegram.send.side_effect = ServiceError("offline")
        self.live_offers["9988"]["items_to_receive"].pop()
        self.record()
        self.live_offers["9988"]["trade_offer_state"] = 6
        self.record()
        blocked = [row for row in self.engine.store.rows("outbox") if row["text"].startswith("Обмен не принят")]
        self.assertTrue(blocked[0]["canceled"])
        self.assertEqual(self.engine.store.get("offers", "9988")["status"], "canceled")

    def test_escrow_notice_contains_items_checked_price_and_is_not_success(self):
        self.engine.monitoring = True
        def held(fresh):
            self.live_offers["9988"]["trade_offer_state"] = 11
            return {}
        self.steam.accept.side_effect = held
        self.record()
        notice = self.engine.store.get("outbox", "escrow:9988")
        self.assertIn("удержании", notice["text"])
        self.assertIn("Сверенная цена: 1 Mann Co. Key + 1 Refined Metal", notice["text"])
        self.assertIn("Painted Hat", notice["text"])
        self.assertIn("Refined Metal × 1", notice["text"])
        self.assertTrue(notice["buttons"][0][0]["url"].endswith("/9988/"))
        self.assertIsNone(self.engine.store.get("outbox", "success:9988"))
        self.assertEqual(self.engine.store.get("offers", "9988")["status"], "in_escrow")
        self.record()
        self.assertEqual(self.telegram.send.call_count, 1)

    def test_terminal_offer_cancels_unsent_escrow_notice(self):
        self.engine.monitoring = True
        self.telegram.send.side_effect = ServiceError("offline")
        self.record()
        self.live_offers["9988"]["trade_offer_state"] = 11
        self.record()
        self.assertFalse(self.engine.store.get("outbox", "escrow:9988")["sent"])
        self.live_offers["9988"]["trade_offer_state"] = 3
        self.record()
        self.assertTrue(self.engine.store.get("outbox", "escrow:9988")["canceled"])
        self.assertTrue(self.engine.store.get("outbox", "accept-unknown:9988")["canceled"])
        self.assertFalse(self.engine.store.get("outbox", "success:9988")["sent"])

    def test_confirmation_state_supersedes_unsent_unknown_accept_notice(self):
        self.engine.monitoring = True
        self.telegram.send.side_effect = ServiceError("offline")
        self.record()
        self.assertFalse(self.engine.store.get("outbox", "accept-unknown:9988")["sent"])
        self.live_offers["9988"]["trade_offer_state"] = 9
        self.record()
        self.assertTrue(self.engine.store.get("outbox", "accept-unknown:9988")["canceled"])
        self.assertFalse(self.engine.store.get("outbox", "manual-confirm:9988")["sent"])

    def test_failed_notification_does_not_undo_completed_trade_or_repeat_accept(self):
        self.engine.monitoring = True
        self.steam.accept.side_effect = self.complete_accept
        self.telegram.send.side_effect = ServiceError("Telegram unavailable", uncertain=True)
        self.record()
        self.assertEqual(self.engine.store.get("offers", "9988")["status"], "accepted")
        self.assertFalse(self.engine.store.get("outbox", "success:9988")["sent"])
        self.telegram.send.side_effect = None
        self.engine._flush_notices()
        self.assertTrue(self.engine.store.get("outbox", "success:9988")["sent"])
        self.steam.accept.assert_called_once()

    def test_pending_active_unknown_does_not_record_false_success(self):
        self.engine.monitoring = True
        self.record()
        self.record()
        self.assertEqual(self.engine.store.get("offers", "9988")["status"], "accept_unknown")
        self.assertIsNone(self.engine.store.get("outbox", "success:9988"))
        self.steam.accept.assert_called_once()

    def test_accepted_offer_is_not_reopened_by_stale_active_snapshot(self):
        self.engine.monitoring = True
        self.steam.accept.side_effect = self.complete_accept
        self.record()
        self.live_offers["9988"]["trade_offer_state"] = 2
        self.assertEqual(self.record()["status"], "accepted")
        self.steam.accept.assert_called_once()

    def test_listing_cleanup_only_after_completed_trade(self):
        self.engine.monitoring = True
        self.steam.accept.side_effect = self.request_confirmation
        self.record()
        self.engine._cleanup()
        self.backpack.delete.assert_not_called()
        self.live_offers["9988"]["trade_offer_state"] = 3
        self.record()
        self.engine._cleanup()
        self.backpack.delete.assert_called_once_with("440_100")

    def test_telegram_setup_required_before_monitor_start(self):
        self.engine._config["telegram_token"] = ""
        with self.assertRaisesRegex(ValueError, "Telegram"):
            self.engine.start()
        self.steam.accept.assert_not_called()

    def test_partial_trade_api_metadata_falls_back_to_partner_inventory(self):
        for row in self.live_offers["9988"]["_descriptions"]:
            row["app_data"] = {"quality": "6"}
        result = self.record()
        self.assertEqual(result["status"], "waiting")
        self.steam.inventory.assert_called_once_with(str(76561197960265728 + 1234))


if __name__ == "__main__":
    unittest.main()
