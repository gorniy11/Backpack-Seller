"""backpack.tf search links and unsupported item filters."""
import unittest
from urllib.parse import parse_qs, urlsplit

from market import market_link, market_url
def item(**changes):
    value = dict(appid=440, defindex=378, name="The Team Captain", baseName="Team Captain", quality={"id": 6, "name": "Unique"},
                 craftable=True, tradable=True)
    value.update(changes)
    return value

def inventory(**changes):
    value = dict(asset_id="10", name="Team Captain", defindex=378, quality_id=6, craftable=True, tradable=True,
                 description={"market_name": "Team Captain", "descriptions": [], "app_data": {"def_index": "378", "quality": "6"}})
    value.update(changes)
    return value


class MarketLinkTests(unittest.TestCase):
    def query(self, row):
        return parse_qs(urlsplit(market_url(row)).query)

    def test_known_paint_uses_rgb_and_canonical_base_name_not_custom_name(self):
        row = inventory(name="My custom title", market_hash_name="Team Captain")
        row["description"]["name"] = "My custom title"
        row["description"]["descriptions"] = [{"value": "Paint Color: Pink as Hell"}]
        query = self.query(row)
        self.assertEqual(query["item"], ["Team Captain"])
        self.assertEqual(query["paint"], ["16738740"])
        self.assertEqual(query["quality"], ["6"])
        self.assertEqual(query["craftable"], ["1"])
        self.assertFalse(market_link(row)["exact"])
        self.assertNotIn("asset", market_url(row).lower())

    def test_team_colour_uses_primary_rgb_not_secondary_alias(self):
        row = dict(backpack_item=item(paint={"id": 5046, "name": "Team Spirit"}, paintSecondaryHex="#588a22"))
        self.assertEqual(self.query(row)["paint"], ["12073019"])

    def test_unusual_strange_and_professional_effects_are_encoded_independently(self):
        row = dict(backpack_item=item(quality={"id": 5}, particle={"id": 13, "name": "Burning Flames"},
                                      elevatedQuality={"id": 11}, killstreakTier=3,
                                      sheen={"name": "Team Shine"}, killstreaker={"name": "Fire Horns"}))
        query = self.query(row)
        self.assertEqual(query["particle"], ["13"])
        self.assertEqual(query["quality"], ["5"])
        self.assertEqual(query["elevated"], ["11"])
        self.assertEqual(query["killstreak_tier"], ["3"])
        self.assertEqual(query["sheen"], ["1"])
        self.assertEqual(query["killstreaker"], ["2002"])

    def test_steam_modifier_prefixes_are_not_used_as_base_item_search(self):
        row = inventory(name="Professional Killstreak Australium Rocket Launcher", market_hash_name="Professional Killstreak Australium Rocket Launcher")
        row["description"].update(market_name="Professional Killstreak Australium Rocket Launcher")
        row["description"]["descriptions"] = [{"value": "Sheen: Team Shine"}, {"value": "Killstreaker: Fire Horns"}]
        query = self.query(row)
        self.assertEqual(query["item"], ["Rocket Launcher"])
        self.assertEqual(query["australium"], ["1"])
        self.assertEqual(query["killstreak_tier"], ["3"])

    def test_whole_spell_selection_transmitted_without_claiming_and_semantics(self):
        row = dict(backpack_item=item(spells=[{"name": "Voices from Below"}, {"name": "Exorcism"}]))
        result = market_link(row)
        self.assertEqual(set(result["parameters"]["spell"].split(",")), {"Voices from Below", "Exorcism"})
        self.assertIn("Полный набор Halloween Spells", result["manual"])
        self.assertFalse(result["exact"])

    def test_unsupported_style_and_parts_have_manual_check_without_fake_params(self):
        row = dict(backpack_item=item(style={"name": "New School"}, craftNumber=42,
                                      strangeParts=[{"killEater": {"name": "Robots Destroyed"}}], festivized=True))
        result = market_link(row)
        self.assertEqual(set(result["manual"]), {"Стиль", "Strange Parts", "Festivized", "Номер ковки"})
        self.assertNotIn("style", result["parameters"])
        self.assertNotIn("craftNumber", result["parameters"])
        self.assertNotIn("festivized", result["parameters"])

    def test_warpaint_name_preserves_canonical_case_and_wear(self):
        row = dict(backpack_item=item(texture={"id": 1, "name": "Flower Power"}, wearTier={"name": "Factory New"}))
        query = self.query(row)
        self.assertEqual(query["texture_name"], ["Flower Power"])
        self.assertEqual(query["wear"], ["Factory New"])

    def test_unknown_variant_still_opens_base_search_with_explicit_manual_reason(self):
        row = dict(backpack_item=item(unknownExtra="property"))
        result = market_link(row)
        self.assertEqual(result["parameters"]["item"], "Team Captain")
        self.assertEqual(result["parameters"]["quality"], 6)
        self.assertTrue(result["manual"])
        self.assertFalse(result["exact"])

    def test_unknown_strange_counter_keeps_quality_paint_and_spell_filters(self):
        row = inventory(defindex=None, quality_id=None, name="Strange Team Captain")
        row["description"].update(app_data={}, market_name="Strange Team Captain", type="Strange Hat - Unknown Count: 0",
                                  tags=[{"category": "Quality", "internal_name": "strange"}],
                                  descriptions=[{"value": "Paint Color: Pink as Hell"},
                                                {"value": "Halloween: Voices from Below"}])
        result = market_link(row)
        self.assertEqual(result["parameters"]["item"], "Team Captain")
        self.assertEqual(result["parameters"]["quality"], 11)
        self.assertEqual(result["parameters"]["paint"], 16738740)
        self.assertEqual(result["parameters"]["spell"], "Voices from Below")
        self.assertTrue(result["manual"])
        self.assertFalse(result["exact"])

    def test_decorated_steam_item_keeps_known_unusual_and_killstreak_attributes(self):
        row = inventory(quality_id=15, name="Professional Killstreak Rocket Launcher")
        row["description"].update(market_name="Professional Killstreak Rocket Launcher", descriptions=[
            {"value": "Unusual Effect: Isotope"}, {"value": "Sheen: Team Shine"},
            {"value": "Killstreaker: Fire Horns"}, {"value": "Halloween: Exorcism"}])
        query = self.query(row)
        self.assertEqual(query["quality"], ["15"])
        self.assertEqual(query["particle"], ["702"])
        self.assertEqual(query["killstreak_tier"], ["3"])
        self.assertEqual(query["sheen"], ["1"])
        self.assertEqual(query["killstreaker"], ["2002"])
        self.assertEqual(query["spell"], ["Exorcism"])

    def test_backpack_unknown_attachment_keeps_all_independent_known_filters(self):
        row = dict(backpack_item=item(unknownExtra="property", paint={"id": 5040},
                                      particle={"id": 13}, spells=[{"name": "Exorcism"}],
                                      killstreakTier=3, sheen={"id": 1}, killstreaker={"id": 2002}))
        result = market_link(row)
        self.assertEqual(result["parameters"]["paint"], 1315860)
        self.assertEqual(result["parameters"]["particle"], 13)
        self.assertEqual(result["parameters"]["spell"], "Exorcism")
        self.assertEqual(result["parameters"]["sheen"], 1)
        self.assertEqual(result["parameters"]["killstreaker"], 2002)
        self.assertTrue(result["manual"])

    def test_fallback_never_reads_properties_from_user_text_or_ambiguous_quality(self):
        row = inventory(defindex=None, quality_id=None)
        row["description"].update(app_data={}, tags=[{"category": "Quality", "internal_name": "Unique"},
                                                    {"category": "Quality", "internal_name": "strange"}],
                                  descriptions=[{"type": "usertext", "value": "Paint Color: Pink as Hell"},
                                                {"type": "usertext", "value": "Halloween: Exorcism"},
                                                {"type": "usertext", "value": "Unusual Effect: Burning Flames"}])
        result = market_link(row)
        self.assertNotIn("quality", result["parameters"])
        self.assertNotIn("paint", result["parameters"])
        self.assertNotIn("spell", result["parameters"])
        self.assertNotIn("particle", result["parameters"])


if __name__ == "__main__":
    unittest.main()
