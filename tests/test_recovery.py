import threading
import unittest
from unittest.mock import MagicMock

from engine import SellerEngine


class PublicationRecoveryTests(unittest.TestCase):
    def engine(self):
        obj = object.__new__(SellerEngine)
        obj.lock = threading.RLock()
        obj.demo = False
        obj.store = MagicMock()
        obj.backpack = MagicMock()
        obj.on_event = MagicMock()
        obj.log = MagicMock()
        return obj

    def test_demo_reconciliation_never_calls_backpack(self):
        engine = self.engine()
        engine.demo = True
        self.assertEqual(engine.reconcile_listings(), {})
        engine.backpack.listings.assert_not_called()

    def test_unknown_publication_can_be_cleared_after_authoritative_read(self):
        engine = self.engine()
        engine.store.get.return_value = dict(asset_id="123", status="publish_unknown", listing_id="", version=1)
        engine.backpack.listings.return_value = []
        engine.remove_listing("123")
        engine.backpack.listings.assert_called_once()
        engine.backpack.delete.assert_not_called()
        self.assertEqual(engine.store.put.call_args.args[2]["status"], "removed")

    def test_unknown_publication_found_remotely_is_deleted_before_clear(self):
        engine = self.engine()
        engine.store.get.return_value = dict(asset_id="123", status="publish_unknown", listing_id="", version=1)
        engine.backpack.listings.return_value = [dict(asset_id="123", listing_id="440_123")]
        engine.remove_listing("123")
        engine.backpack.delete.assert_called_once_with("440_123")
        self.assertEqual(engine.store.put.call_args.args[2]["status"], "removed")

    def test_remote_listing_identity_intent_and_active_state_are_required(self):
        remote = dict(asset_id="123", listing_id="440_123", intent="sell", currencies={"keys": 1, "metal": 0})
        for change in ({"asset_id": "999"}, {"asset_id": ""}, {"intent": "buy"}, {"intent": None}, {"archived": True}):
            with self.subTest(change=change):
                engine = self.engine()
                local = dict(asset_id="123", listing_id="440_123", status="active", keys=1, metal_scrap=0)
                engine.store.listings.return_value = [local]
                engine.backpack.listings.return_value = [{**remote, **change}]
                engine.reconcile_listings()
                self.assertEqual(engine.store.put.call_args.args[2]["status"], "external_change")
