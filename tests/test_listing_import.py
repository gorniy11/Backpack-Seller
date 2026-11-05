"""Importing the account's active listings."""
import copy
import unittest

import test_engine as fixtures
from clients import ServiceError


class ListingImportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowTests(methodName="runTest")
        self.fixture.setUp()
        self.engine = self.fixture.engine
        self.backpack = self.fixture.backpack
        self.remote = []
        self.backpack.listings.side_effect = lambda: copy.deepcopy(self.remote)

    def tearDown(self):
        self.fixture.tearDown()

    @staticmethod
    def sale(asset_id="200", **changes):
        value = dict(asset_id=str(asset_id), listing_id="440_" + str(asset_id),
                     steamid=fixtures.OWNER, appid=440, intent="sell", source="steam", status="active",
                     currencies={"keys": 1, "metal": 15}, details="A website listing",
                     item=dict(appid=440, id=str(asset_id), defindex=825, name="The Hat of Cards",
                               marketName="Hat of Cards", quality={"id": 6, "name": "Unique"},
                               craftable=True, tradable=True,
                               paint={"id": 5040, "name": "A Distinctive Lack of Hue"},
                               spells=[{"name": "Voices From Below"}]))
        value.update(changes)
        return value

    def row(self, asset_id="200"):
        return self.engine.store.get("listings", asset_id)

    def assert_no_mutations(self):
        self.backpack.create.assert_not_called()
        self.backpack.delete.assert_not_called()
        self.fixture.steam.accept.assert_not_called()
        self.fixture.steam.inventory.assert_not_called()

    def test_imports_active_own_listing_without_loading_steam_inventory(self):
        self.remote = [self.sale()]
        message = self.engine.import_listings()
        row = self.row()
        self.assertEqual(row["name"], "Hat of Cards")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["keys"], 1)
        self.assertEqual(row["metal_scrap"], 135)
        self.assertEqual(row["details"], "A website listing")
        self.assertEqual(row["account"], fixtures.OWNER)
        self.assertEqual(row["backpack_item"], self.remote[0]["item"])
        self.assertTrue(row["price_supported"])
        self.assertIn("Новых: 1", message)
        self.assertIsNone(self.engine.store.get("inventory", "200"))
        self.assert_no_mutations()

    def test_import_uses_canonical_steam_name_and_keeps_full_remote_variant(self):
        self.engine.store.put("inventory", "200", dict(asset_id="200", name="An old item alias",
            description={"name": "A Name Tag alias", "market_name": "Hat of Cards"}))
        self.remote = [self.sale()]
        self.engine.reconcile_listings()
        self.assertEqual(self.row()["name"], "Hat of Cards")
        self.assertEqual(self.row()["backpack_item"]["spells"], [{"name": "Voices From Below"}])
        self.assert_no_mutations()

    def test_all_known_steam_listing_sources_are_supported_including_user_agent(self):
        self.remote = [self.sale(str(200 + index), source=source)
                       for index, source in enumerate(("steam", "user", "userAgent", "backpackTf", "backpack.tf"))]
        self.engine.import_listings()
        self.assertEqual([self.row(str(200 + index))["status"] for index in range(5)], ["active"] * 5)
        self.assert_no_mutations()

    def test_existing_user_agent_listing_stays_active_during_reconciliation(self):
        self.remote = [self.sale("100", source="userAgent", currencies={"keys": 1, "metal": 1})]
        self.engine.reconcile_listings()
        self.assertEqual(self.row("100")["status"], "active")
        self.assert_no_mutations()

    def test_does_not_import_buys_archives_other_games_or_nonsteam_sources(self):
        self.remote = [self.sale("200", intent="buy"), self.sale("201", archived=True),
                       self.sale("202", status="archived"), self.sale("203", appid=730),
                       self.sale("204", item={"appid": 730}), self.sale("205", source="marketplaceTf"),
                       self.sale("not-an-exact-item"), self.sale("207", steamid="")]
        self.engine.import_listings()
        self.assertTrue(all(self.row(str(index)) is None for index in range(200, 208)))
        self.assert_no_mutations()

    def test_wrong_account_read_is_rejected_before_local_state_changes(self):
        old = self.engine.store.listings()
        self.remote = [self.sale(steamid="76561198000000001")]
        with self.assertRaises(ServiceError):
            self.engine.import_listings()
        self.assertEqual(self.engine.store.listings(), old)
        self.assert_no_mutations()

    def test_duplicate_item_identity_is_not_imported_as_a_new_active_sale(self):
        self.remote = [self.sale(), self.sale(listing_id="another_listing")]
        self.engine.import_listings()
        self.assertIsNone(self.row())
        self.assert_no_mutations()

    def test_conflicting_full_item_identity_and_invalid_numeric_ids_are_not_imported(self):
        wrong_item = self.sale()
        wrong_item["item"]["id"] = "999"
        self.remote = [wrong_item, self.sale("0"), self.sale(str(2**64))]
        self.engine.import_listings()
        self.assertTrue(all(self.row(asset) is None for asset in ("200", "0", str(2**64))))
        self.assert_no_mutations()

    def test_repeated_import_has_no_duplicates_or_spurious_policy_version_change(self):
        self.remote = [self.sale()]
        self.engine.import_listings()
        version = self.row()["version"]
        message = self.engine.import_listings()
        self.assertEqual(len([row for row in self.engine.store.listings() if row["asset_id"] == "200"]), 1)
        self.assertEqual(self.row()["version"], version)
        self.assertIn("Новых: 0", message)
        self.assert_no_mutations()

    def test_website_price_and_description_updates_are_imported_with_new_policy_version(self):
        self.remote = [self.sale()]
        self.engine.import_listings()
        version = self.row()["version"]
        self.remote[0].update(currencies={"keys": 2, "metal": 5.11}, details="Changed on website")
        self.engine.import_listings()
        row = self.row()
        self.assertEqual((row["keys"], row["metal_scrap"], row["details"]), (2, 46, "Changed on website"))
        self.assertEqual(row["version"], version + 1)
        self.assertEqual(row["status"], "active")
        self.assert_no_mutations()

    def test_removed_on_site_is_marked_removed_and_website_republication_is_imported(self):
        self.remote = [self.sale()]
        self.engine.import_listings()
        self.remote = []
        self.engine.import_listings()
        self.assertEqual(self.row()["status"], "removed")
        self.remote = [self.sale(currencies={"keys": 3, "metal": 0})]
        self.engine.import_listings()
        self.assertEqual((self.row()["status"], self.row()["keys"]), ("active", 3))
        self.assert_no_mutations()

    def test_reserved_trade_keeps_its_price_version_and_item_metadata(self):
        self.remote = [self.sale()]
        self.engine.import_listings()
        row = self.row()
        row["reserved_by"] = "in-flight-offer"
        self.engine.store.put("listings", "200", row)
        original = copy.deepcopy(row)
        self.remote[0].update(currencies={"keys": 9}, details="Changed while reserved",
                              item={"defindex": 1, "name": "A different description"})
        self.engine.import_listings()
        current = self.row()
        for field in ("keys", "metal_scrap", "version", "listing_id", "details", "backpack_item"):
            self.assertEqual(current[field], original[field])
        self.assertEqual(current["status"], "external_change")
        self.assertEqual(current["observed_currencies"], {"keys": 9})
        self.assert_no_mutations()

    def test_pending_offer_protects_policy_even_if_old_reservation_field_is_missing(self):
        self.remote = [self.sale()]
        self.engine.import_listings()
        self.engine.store.put("offers", "pending-offer", dict(offer_id="pending-offer", status="needs_confirmation", asset_ids=["200"]))
        self.remote[0]["currencies"] = {"keys": 8}
        self.engine.import_listings()
        self.assertEqual((self.row()["keys"], self.row()["metal_scrap"]), (1, 135))
        self.assertEqual(self.row()["reserved_by"], "pending-offer")
        self.assertEqual(self.row()["status"], "external_change")
        self.assert_no_mutations()

    def test_unsupported_currency_is_visible_but_cannot_authorize_a_trade(self):
        self.remote = [self.sale(currencies={"usd": 2})]
        message = self.engine.import_listings()
        self.assertEqual(self.row()["status"], "unsupported_price")
        self.assertFalse(self.row()["price_supported"])
        self.assertEqual(self.row()["remote_currencies"], {"usd": 2})
        self.assertIn("С неподдерживаемой ценой: 1", message)
        self.assert_no_mutations()

    def test_failed_complete_read_does_not_remove_or_overwrite_cached_records(self):
        self.remote = [self.sale()]
        self.engine.import_listings()
        previous = self.engine.store.listings()
        self.backpack.listings.side_effect = ServiceError("Full page read failed")
        with self.assertRaises(ServiceError):
            self.engine.import_listings()
        self.assertEqual(self.engine.store.listings(), previous)
        self.assert_no_mutations()


if __name__ == "__main__":
    unittest.main()
