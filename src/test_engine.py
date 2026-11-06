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



























    def test_telegram_setup_required_before_monitor_start(self):
        self.engine._config["telegram_token"] = ""
        with self.assertRaisesRegex(ValueError, "Telegram"):
            self.engine.start()
        self.steam.accept.assert_not_called()



if __name__ == "__main__":
    unittest.main()
