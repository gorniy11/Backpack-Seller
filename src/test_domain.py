import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain import parse_price, refined_text, format_price, parse_inventory, validate_offer, offer_fingerprint, inventory_matches


def asset(asset_id, class_id="5021", **changes):
    return {"assetid": str(asset_id), "classid": str(class_id), "instanceid": "0",
            "appid": 440, "contextid": "2", "amount": "1", **changes}


def description(defindex=5021, class_id=None, **changes):
    return {"appid": 440, "classid": str(class_id or defindex), "instanceid": "0",
            "app_data": {"def_index": str(defindex), "quality": "6"},
            "descriptions": [], "tradable": 1, "name": "arbitrary custom name", **changes}


def fixture():
    offer = {"tradeofferid": "9988", "accountid_other": 1234, "is_our_offer": False,
             "trade_offer_state": 2, "items_to_give": [asset(100, "200")],
             "items_to_receive": [asset(500, "5021"), asset(501, "5002"), asset(502, "5001"), asset(503, "5000")]}
    listing = {"100": {"asset_id": "100", "status": "active", "keys": 1,
                       "metal_scrap": 13, "auto_accept": True, "version": 1}}
    descriptions = [description(5021), description(5000), description(5001), description(5002)]
    return offer, listing, descriptions


class PriceTests(unittest.TestCase):
    def test_exact_scrap_units(self):
        self.assertEqual(parse_price("1", "15"), {"keys": 1, "metal_scrap": 135})
        self.assertEqual(parse_price(0, ".11"), {"keys": 0, "metal_scrap": 1})
        self.assertEqual(parse_price("0", "1,33"), {"keys": 0, "metal_scrap": 12})
        self.assertEqual(parse_price(0, "1.00"), {"keys": 0, "metal_scrap": 9})

    def test_all_fractions_round_trip(self):
        for scrap in range(1, 200):
            with self.subTest(scrap=scrap):
                self.assertEqual(parse_price(0, refined_text(scrap))["metal_scrap"], scrap)

    def test_invalid_prices(self):
        for key, metal in [(0, ".1"), (0, ".99"), (0, "1.09"), (0, "-1"), (-1, "1"),
                           (0, "0"), (True, "1"), (1.0, "0"), (0, 0.11), (0, ""), (0, "."), (0, "1e2")]:
            with self.subTest(key=key, metal=metal):
                with self.assertRaises(ValueError):
                    parse_price(key, metal)

    def test_display(self):
        self.assertEqual(format_price(1, 135), "1 Mann Co. Key + 15 Refined Metal")
        self.assertEqual(format_price(2, 0), "2 Mann Co. Key")
        self.assertEqual(format_price(0, 0), "0 Refined Metal")

    def test_visible_price_errors_use_currency_terms_only(self):
        for operation in (lambda: parse_price(0, ".99"), lambda: refined_text(-1)):
            with self.assertRaises(ValueError) as result:
                operation()
            self.assertNotIn("scrap", str(result.exception).lower())
            self.assertNotIn("assetid", str(result.exception).lower())


class InventoryTests(unittest.TestCase):
    def test_same_name_separate_asset_ids_and_paint(self):
        desc = description(200, class_id="a", name="Painted Hat", icon_url="icon-token", icon_url_large="larger-icon",
                           descriptions=[{"value": "Paint Color: A Distinctive Lack of Hue"}, {"value": "Halloween: Voices From Below"}],
                           tags=[{"category": "Quality", "localized_tag_name": "Unique"}])
        rows = parse_inventory({"assets": [asset(1, "a"), asset(2, "a")], "descriptions": [desc]})
        self.assertEqual([row["asset_id"] for row in rows], ["1", "2"])
        self.assertIn("A Distinctive Lack of Hue", rows[0]["paint"])
        self.assertIn("larger-icon", rows[0]["icon_url"])

    def test_only_tradable_known_tf2_assets(self):
        rows = parse_inventory({"assets": [asset(1), asset(2, "x"), asset(3, appid=730), asset(4, "z"), asset(5, missing=True), asset(1)],
                                "descriptions": [description(), description(class_id="x", tradable=0)]})
        self.assertEqual([row["asset_id"] for row in rows], ["1"])

    def test_untrusted_icon_host_removed(self):
        rows = parse_inventory({"assets": [asset(1)], "descriptions": [description(icon_url="https://evil.test/icon")]})
        self.assertEqual(rows[0]["icon_url"], "")

    def test_name_tag_does_not_replace_item_name_or_merge_painted_copies(self):
        rows = parse_inventory({"assets": [asset(1, "a"), asset(2, "b")], "descriptions": [
            description(200, "a", name='"My favourite"', market_name="Team Captain", icon_url="painted-black"),
            description(200, "b", name='"Something else"', market_hash_name="Team Captain", icon_url="painted-pink")]})
        self.assertEqual([r["name"] for r in rows], ["Team Captain", "Team Captain"])
        self.assertNotEqual(rows[0]["icon_url"], rows[1]["icon_url"])
        self.assertTrue(rows[0]["icon_url"].endswith("painted-black/256fx256f"))

    def test_steam_filters_or_within_category_and_between_categories(self):
        desc = description(tags=[{"category": "Quality", "internal_name": "rarity4", "localized_tag_name": "Unique"},
                                 {"category": "Class", "internal_name": "Soldier", "localized_tag_name": "Soldier"},
                                 {"category": "Class", "internal_name": "Medic", "localized_tag_name": "Medic"}])
        row = parse_inventory({"assets": [asset(1)], "descriptions": [desc]})[0]
        self.assertTrue(inventory_matches(row, selected={"Class": {"Medic", "Spy"}, "Quality": {"rarity4"}}))
        self.assertFalse(inventory_matches(row, selected={"Class": {"Medic"}, "Quality": {"strange"}}))
        self.assertFalse(inventory_matches(row, selected={"Class": {"Spy"}}))
        self.assertFalse(inventory_matches(row, query="missing"))

    def test_filter_metadata_excludes_paint(self):
        row = parse_inventory({"assets": [asset(1)], "descriptions": [description(tags=[
            {"category": "Paint", "internal_name": "pink", "localized_tag_name": "Pink"}])]})[0]
        self.assertEqual(row["filter_tags"], [])


class OfferTests(unittest.TestCase):
    def test_exact_valid_and_no_name_identity(self):
        offer, listings, desc = fixture()
        result = validate_offer(offer, listings, desc)
        self.assertTrue(result.valid, result.reason)
        self.assertEqual((result.keys, result.metal_scrap), (1, 13))
        self.assertEqual(result.asset_ids, ("100",))
        self.assertTrue(result.auto_eligible)
        self.assertEqual(len(result.fingerprint), 64)

    def test_defindex_and_quality_required_not_display_name(self):
        for data in [{}, {"def_index": "1", "quality": "6"}, {"def_index": "5021", "quality": "11"}, {"def_index": "5021"}]:
            offer, listings, desc = fixture()
            desc[0].update(app_data=data, name="Mann Co. Supply Crate Key", market_hash_name="Mann Co. Supply Crate Key")
            self.assertFalse(validate_offer(offer, listings, desc).valid)

    def test_incomplete_metadata_never_accepted(self):
        offer, listings, desc = fixture()
        desc[0].pop("descriptions")
        self.assertFalse(validate_offer(offer, listings, desc).valid)
        desc[0]["craftable"] = True
        self.assertTrue(validate_offer(offer, listings, desc).valid)

    def test_noncraftable_currency(self):
        for changes in [{"craftable": False}, {"descriptions": [{"value": "( Not Usable in Crafting )"}]}]:
            offer, listings, desc = fixture()
            desc[0].update(changes)
            self.assertFalse(validate_offer(offer, listings, desc).valid)

    def test_exact_price_requires_both_parts_no_conversion(self):
        for received in [[], [asset(500)], [asset(500), asset(501, "5002")],
                         [asset(500), asset(501, "5002"), asset(502, "5001"), asset(503, "5000"), asset(504, "5000")]]:
            offer, listings, desc = fixture()
            offer["items_to_receive"] = received
            self.assertFalse(validate_offer(offer, listings, desc).valid)

    def test_additional_outgoing_item_and_inactive_listing(self):
        offer, listings, desc = fixture()
        offer["items_to_give"].append(asset(101, "200"))
        self.assertFalse(validate_offer(offer, listings, desc).valid)
        offer["items_to_give"].pop()
        listings["100"]["status"] = "sold"
        self.assertFalse(validate_offer(offer, listings, desc).valid)

    def test_bad_assets_on_each_side(self):
        for side in ["items_to_give", "items_to_receive"]:
            for changes in [{"appid": 730}, {"contextid": "3"}, {"amount": "2"}, {"amount": None}, {"missing": True}, {"currencyid": "1"}, {"assetid": ""}]:
                with self.subTest(side=side, changes=changes):
                    offer, listings, desc = fixture()
                    offer[side][0].update(changes)
                    self.assertFalse(validate_offer(offer, listings, desc).valid)

    def test_duplicates_rejected_on_each_side(self):
        for side in ["items_to_give", "items_to_receive"]:
            offer, listings, desc = fixture()
            offer[side].append(copy.deepcopy(offer[side][0]))
            result = validate_offer(offer, listings, desc)
            self.assertFalse(result.valid)
            self.assertNotIn("assetid", result.reason.lower())
            self.assertNotIn("scrap", result.reason.lower())

    def test_incoming_active_only_and_identity_required(self):
        for changes in [{"is_our_offer": True}, {"is_our_offer": 0}, {"trade_offer_state": 3}, {"tradeofferid": None}, {"accountid_other": 0}]:
            offer, listings, desc = fixture()
            offer.update(changes)
            self.assertFalse(validate_offer(offer, listings, desc).valid)

    def test_multiple_listings_sum_and_all_item_auto_policy(self):
        offer, listings, desc = fixture()
        offer["items_to_give"].append(asset(101, "200"))
        listings["100"].update(keys=1, metal_scrap=4)
        listings["101"] = {"asset_id": "101", "status": "active", "keys": 0, "metal_scrap": 9, "auto_accept": False}
        result = validate_offer(offer, listings, desc)
        self.assertTrue(result.valid)
        self.assertFalse(result.auto_eligible)
        listings["101"]["auto_accept"] = True
        self.assertTrue(validate_offer(offer, listings, desc).auto_eligible)

    def test_currency_description_class_and_instance_must_match(self):
        for changes in [{"classid": "wrong"}, {"instanceid": "wrong"}, {"appid": 730}, {"tradable": 0}]:
            offer, listings, desc = fixture()
            by_asset = {"500": {**desc[0], **changes}, "501": desc[3], "502": desc[2], "503": desc[1]}
            self.assertFalse(validate_offer(offer, listings, by_asset).valid)

    def test_fingerprint_binds_offer_prices_versions_and_policy(self):
        offer, listings, desc = fixture()
        previous = validate_offer(offer, listings, desc).fingerprint
        changes = [(offer, "accountid_other", 5678), (offer, "message", "changed"),
                   (listings["100"], "version", 2), (listings["100"], "auto_accept", False), (listings["100"], "keys", 2)]
        for target, key, value in changes:
            old = target.get(key)
            target[key] = value
            self.assertNotEqual(validate_offer(offer, listings, desc).fingerprint, previous)
            if old is None:
                del target[key]
            else:
                target[key] = old

    def test_listing_invalid_or_zero_price(self):
        for changes in [{"keys": True}, {"metal_scrap": -1}, {"keys": 0, "metal_scrap": 0}, {"keys": 1.0}]:
            offer, listings, desc = fixture()
            listings["100"].update(changes)
            self.assertFalse(validate_offer(offer, listings, desc).valid)

    def test_fingerprint_survives_state_and_timestamp_changes(self):
        offer, listings, desc = fixture()
        original = offer_fingerprint(offer, listings)
        offer.update(trade_offer_state=9, time_updated=123456)
        self.assertEqual(offer_fingerprint(offer, listings), original)


if __name__ == "__main__":
    unittest.main()
