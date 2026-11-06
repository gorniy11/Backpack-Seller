import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clients import BackpackClient, ServiceError, SteamClient, TelegramClient


OWNER = "76561198000000000"


class Response:
    def __init__(self, data=None, status=200, text=None, headers=None):
        if text is None:
            text = "invalid JSON" if isinstance(data, Exception) else json.dumps(data)
        self.data, self.status_code, self.text = data, status, text
        self.headers = headers or {}
        self.closed = False

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()
        self.responses = []
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        pass


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.patcher = patch("clients.requests.Session", return_value=self.session)
        self.patcher.start()
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def steam(self, **overrides):
        client = SteamClient({"steam_id": OWNER, "steam_api_key": "SECRET_API", **overrides}, Path(self.temp.name))
        client._install_cookies([
            {"name": "steamLoginSecure", "value": OWNER + "%7C%7CSECRET", "domain": ".steamcommunity.com"},
            {"name": "sessionid", "value": "SECRET_SESSION", "domain": "steamcommunity.com"},
        ])
        return client

    def test_empty_config_constructs_but_cannot_perform_account_actions(self):
        client = SteamClient({}, Path(self.temp.name))
        BackpackClient({})
        TelegramClient({})
        with self.assertRaises(ServiceError):
            client.inventory()
        with self.assertRaises(ServiceError):
            client.check()
        self.assertEqual(self.session.calls, [])

    def test_local_session_identity_is_discovered_without_config_or_network(self):
        client = SteamClient({}, Path(self.temp.name))
        self.assertFalse(client.has_session())
        client._install_cookies([
            {"name": "steamLoginSecure", "value": OWNER + "%7C%7CSECRET", "domain": ".steamcommunity.com"},
            {"name": "sessionid", "value": "SESSION", "domain": "steamcommunity.com"},
        ])
        self.assertTrue(client.has_session())
        self.assertEqual(client.session_identity(), OWNER)
        self.assertEqual(self.session.calls, [])

    def test_saved_session_derives_account_before_settings_exist(self):
        cookies = [
            {"name": "steamLoginSecure", "value": OWNER + "%7C%7CSECRET", "domain": ".steamcommunity.com"},
            {"name": "sessionid", "value": "SESSION", "domain": "steamcommunity.com"},
        ]
        root = Path(self.temp.name)
        (root / "steam-session.bin").write_bytes(b"encrypted")
        with patch("vault.unprotect", return_value=json.dumps(cookies).encode()):
            client = SteamClient({}, root)
        self.assertEqual(client.steam_id, OWNER)
        self.assertTrue(client.has_session())
        self.assertFalse(client.session_load_error)
        self.assertEqual(self.session.calls, [])

    def test_expired_saved_cookie_is_not_a_usable_local_session(self):
        client = SteamClient({}, Path(self.temp.name))
        client._install_cookies([
            {"name": "steamLoginSecure", "value": OWNER + "||SECRET", "domain": ".steamcommunity.com", "expires": 1},
            {"name": "sessionid", "value": "SESSION", "domain": "steamcommunity.com"},
        ])
        self.assertFalse(client.has_session())
        self.assertEqual(self.session.calls, [])

    def test_login_discovers_account_without_configured_steam_id(self):
        client = SteamClient({}, Path(self.temp.name))
        manager = MagicMock()
        playwright = manager.return_value.__enter__.return_value
        context = playwright.chromium.launch_persistent_context.return_value
        page = MagicMock()
        context.pages = [page]
        context.cookies.return_value = [
            {"name": "steamLoginSecure", "value": OWNER + "||SECRET", "domain": ".steamcommunity.com"},
            {"name": "sessionid", "value": "SESSION", "domain": "steamcommunity.com"},
        ]
        with patch("playwright.sync_api.sync_playwright", manager), patch.object(client, "_check_session") as check, patch("vault.protect", return_value=b"encrypted"):
            result = client.login()
        self.assertEqual(result["steam_id"], OWNER)
        self.assertEqual(client.session_identity(), OWNER)
        self.assertEqual((Path(self.temp.name) / "steam-session.bin").read_bytes(), b"encrypted")
        check.assert_called_once()
        context.close.assert_called_once()
        self.assertEqual(self.session.calls, [])

    def test_login_rejects_different_configured_account_before_saving(self):
        client = SteamClient({"steam_id": OWNER}, Path(self.temp.name))
        manager = MagicMock()
        context = manager.return_value.__enter__.return_value.chromium.launch_persistent_context.return_value
        context.pages = [MagicMock()]
        context.cookies.return_value = [
            {"name": "steamLoginSecure", "value": "76561198000000001||SECRET", "domain": ".steamcommunity.com"},
            {"name": "sessionid", "value": "SESSION", "domain": "steamcommunity.com"},
        ]
        with patch("playwright.sync_api.sync_playwright", manager):
            with self.assertRaises(ServiceError):
                client.login()
        self.assertFalse((Path(self.temp.name) / "steam-session.bin").exists())
        context.close.assert_called_once()

    def test_inventory_paginates_and_preserves_asset_identity(self):
        client = self.steam()
        self.session.responses = [
            Response({"success": 1, "assets": [{"assetid": "10"}], "descriptions": [{"classid": "a", "instanceid": "0"}], "total_inventory_count": 2, "more_items": 1, "last_assetid": "10"}),
            Response({"success": 1, "assets": [{"assetid": "11"}], "descriptions": [{"classid": "b", "instanceid": "0"}], "total_inventory_count": 2, "more_items": 0}),
        ]
        result = client.inventory()
        self.assertEqual([a["assetid"] for a in result["assets"]], ["10", "11"])
        self.assertEqual(self.session.calls[1][2]["params"]["start_assetid"], "10")
        self.assertEqual(len(result["descriptions"]), 2)

    def test_inventory_failure_does_not_return_partial_items(self):
        client = self.steam()
        self.session.responses = [
            Response({"success": 1, "assets": [{"assetid": "10"}], "descriptions": [], "total_inventory_count": 2, "more_items": 1, "last_assetid": "10"}),
            Response({"success": 0}),
        ]
        with self.assertRaises(ServiceError):
            client.inventory()

    def test_inventory_duplicate_page_is_rejected(self):
        client = self.steam()
        self.session.responses = [
            Response({"success": 1, "assets": [{"assetid": "10"}], "more_items": 1, "last_assetid": "10"}),
            Response({"success": 1, "assets": [{"assetid": "10"}], "more_items": 0}),
        ]
        with self.assertRaises(ServiceError):
            client.inventory()

    def test_partner_inventory_uses_explicit_partner(self):
        client = self.steam()
        self.session.responses = [Response({"success": 1, "assets": [], "descriptions": []})]
        client.inventory("76561198000000001")
        self.assertIn("/inventory/76561198000000001/440/2", self.session.calls[0][1])

    def test_offers_attach_descriptions_across_all_pages(self):
        client = self.steam()
        self.session.responses = [
            Response({"response": {"trade_offers_received": [{"tradeofferid": "1"}], "descriptions": [{"appid": 440, "classid": "a"}], "next_cursor": 5}}),
            Response({"response": {"trade_offers_received": [{"tradeofferid": "2"}], "descriptions": [{"appid": 440, "classid": "b"}], "next_cursor": 0}}),
        ]
        values = client.offers()
        self.assertEqual(len(values), 2)
        self.assertEqual(len(values[0]["_descriptions"]), 2)
        self.assertEqual(self.session.calls[1][2]["params"]["cursor"], 5)

    def test_wrong_account_session_is_refused(self):
        client = self.steam()
        with self.assertRaises(ServiceError):
            client._install_cookies([{"domain": ".steamcommunity.com", "name": "steamLoginSecure", "value": "76561198000000001||OTHER"}])

    def test_check_validates_logged_in_owner(self):
        client = self.steam()
        self.session.responses = [Response(text='var g_steamID = "76561198000000001";')]
        with self.assertRaises(ServiceError):
            client.check()
        self.assertEqual(len(self.session.calls), 1)

    def test_session_check_follows_steam_vanity_redirect_and_checks_account(self):
        client = self.steam()
        redirect = Response(status=302, headers={"Location": "https://steamcommunity.com/id/test-account/"})
        final = Response(text=f'var g_steamID = "{OWNER}";')
        self.session.responses = [redirect, final]
        client._check_session()
        self.assertEqual(self.session.calls[1][1], "https://steamcommunity.com/id/test-account/")
        self.assertTrue(redirect.closed and final.closed)
        self.assertTrue(all(call[2]["allow_redirects"] is False for call in self.session.calls))

    def test_profile_redirect_does_not_trust_profile_owner_in_place_of_logged_in_user(self):
        client = self.steam()
        self.session.responses = [Response(status=302, headers={"Location": "/id/test/"}),
                                  Response(text=f'var g_steamID = false; var profile = "{OWNER}";')]
        with self.assertRaises(ServiceError):
            client._check_session()

    def test_profile_redirect_never_sends_session_to_other_host_or_action(self):
        client = self.steam()
        for target in ["https://evil.test/id/test/", "http://steamcommunity.com/id/test/",
                       "https://steamcommunity.com@evil.test/id/test/", "/tradeoffer/123/accept", "/login/home/"]:
            self.session.calls.clear()
            self.session.responses = [Response(status=302, headers={"Location": target})]
            with self.assertRaises(ServiceError):
                client._check_session()
            self.assertEqual(len(self.session.calls), 1)

    def test_profile_redirect_loop_is_bounded(self):
        client = self.steam()
        self.session.responses = [Response(status=302, headers={"Location": "/id/test/"}) for _ in range(5)]
        with self.assertRaises(ServiceError):
            client._check_session()
        self.assertEqual(len(self.session.calls), 5)






    def test_backpack_uses_asset_and_direct_v2_body(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        response = Response({"id": "440_123", "item": {"id": "123"}, "intent": "sell"}, status=201)
        self.session.responses = [response]
        result = client.create("123", 1, 135, "РћРїРёСЃР°РЅРёРµ")
        body = self.session.calls[0][2]["json"]
        self.assertEqual(body["id"], "123")
        self.assertEqual(body["currencies"], {"keys": 1, "metal": 15})
        self.assertEqual(body["intent"], "sell")
        self.assertNotIn("listing", body)
        self.assertEqual(result["listing_id"], "440_123")
        self.assertTrue(response.closed)

    def test_backpack_currency_uses_scrap_not_float_rounding(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        self.session.responses = [Response({"id": "440_123"})]
        client.create("123", 0, 8, "")
        self.assertEqual(self.session.calls[0][2]["json"]["currencies"]["metal"], .88)

    def test_backpack_patch_updates_conditions_without_changing_item_identity(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        self.session.responses = [Response({"id": "440_123"})]
        client.update("440_123", 2, 10, "New description")
        method, url, options = self.session.calls[0]
        self.assertEqual(method, "PATCH")
        self.assertTrue(url.endswith("/v2/classifieds/listings/440_123"))
        self.assertEqual(options["json"], {"currencies": {"keys": 2, "metal": 1.11}, "details": "New description"})
        self.assertNotIn("id", options["json"])
        self.assertFalse(options["allow_redirects"])

    def test_backpack_patch_missing_or_wrong_identity_is_uncertain(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        for body in ({"id": "440_456"}, {}, None):
            self.session.responses = [Response(body)]
            with self.assertRaises(ServiceError) as caught:
                client.update("440_123", 1, 0, "")
            self.assertTrue(caught.exception.uncertain)

    def test_retry_after_long_delta_and_http_date_are_not_shortened(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        for header, expected in (("7200", 7200), ("Thu, 01 Jan 1970 04:46:40 GMT", 7200)):
            with self.subTest(header=header), patch("clients.time.time", return_value=10000):
                self.session.responses = [Response(status=429, headers={"Retry-After": header})]
                with self.assertRaises(ServiceError) as caught:
                    client.pulse()
                self.assertEqual(caught.exception.retry_after, expected)
                self.assertEqual(caught.exception.status_code, 429)

    def test_bump_uses_only_documented_agent_pulse_endpoint(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        self.session.responses = [Response({"online": True})]
        client.pulse()
        self.assertEqual(self.session.calls[0][0], "POST")
        self.assertTrue(self.session.calls[0][1].endswith("/agent/pulse"))

    def test_backpack_archived_result_is_not_success(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        self.session.responses = [Response({"id": "440_123", "archived": True})]
        with self.assertRaises(ServiceError) as caught:
            client.create("123", 1, 0, "")
        self.assertTrue(caught.exception.uncertain)

    def test_backpack_delete_accepts_successful_no_content(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        response = Response(status=204)
        self.session.responses = [response]
        self.assertEqual(client.delete("440_123"), {"success": True})
        self.assertTrue(response.closed)
        self.assertEqual(self.session.calls[0][0], "DELETE")

    def test_one_public_listing_read_is_read_only_and_identity_checked(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        self.session.responses = [Response({"id": "440_123", "source": "userAgent", "intent": "sell"})]
        self.assertEqual(client.listing("440_123")["source"], "userAgent")
        self.assertEqual(self.session.calls[0][0], "GET")
        self.session.responses = [Response({"id": "440_456"})]
        with self.assertRaises(ServiceError):
            client.listing("440_123")

    def test_deleted_public_listing_is_absent_but_failed_read_is_not(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        self.session.responses = [Response(status=404)]
        self.assertIsNone(client.listing("440_123"))
        self.session.responses = [Response(status=503), Response(status=503)]
        with self.assertRaises(ServiceError):
            client.listing("440_123")

    def test_backpack_delete_accepts_http_200_empty_and_null_bodies(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        for response in [Response(ValueError(), text=""), Response(ValueError(), text=" \r\n "), Response(None)]:
            with self.subTest(body=response.text):
                self.session.calls.clear()
                self.session.responses = [response]
                self.assertEqual(client.delete("440_123"), {"success": True})
                self.assertEqual(len(self.session.calls), 1)
                self.assertTrue(response.closed)

    def test_backpack_delete_does_not_accept_html_or_error_json(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        for response in [Response(ValueError(), text="<html>Login</html>"),
                         Response({"message": "SECRET", "reason": "badToken"}), Response(False)]:
            with self.subTest(body=response.text):
                self.session.calls.clear()
                self.session.responses = [response]
                with self.assertRaises(ServiceError) as caught:
                    client.delete("440_123")
                self.assertTrue(caught.exception.uncertain)
                self.assertNotIn("SECRET", str(caught.exception))
                self.assertEqual(len(self.session.calls), 1)
                self.assertTrue(response.closed)

    def test_backpack_delete_not_found_preserves_status_without_leaking_body(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        self.session.responses = [Response({"message": "SECRET"}, status=404)]
        with self.assertRaises(ServiceError) as caught:
            client.delete("440_123")
        self.assertEqual(caught.exception.status_code, 404)
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertEqual(len(self.session.calls), 1)

    def test_backpack_create_missing_identity_is_uncertain_and_never_retried(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        for response in [Response(ValueError(), text=""), Response(None), Response([]),
                         Response({"success": True}), Response({"result": {}}),
                         Response({"id": None}), Response({"id": True})]:
            with self.subTest(body=response.text):
                self.session.calls.clear()
                self.session.responses = [response]
                with self.assertRaises(ServiceError) as caught:
                    client.create("123", 1, 0, "")
                self.assertTrue(caught.exception.uncertain)
                self.assertEqual(len(self.session.calls), 1)
                self.assertTrue(response.closed)

    def test_backpack_create_reads_result_wrapper_without_fabricating_identity(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        self.session.responses = [Response({"result": {"id": "440_123", "item": {"id": "123"}}})]
        self.assertEqual(client.create("123", 1, 0, "")["listing_id"], "440_123")
        self.assertEqual(len(self.session.calls), 1)


    def test_backpack_preserves_validated_description_without_truncation(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        self.session.responses = [Response({"id": "440_123"})]
        description = "x" * 1500
        client.create("123", 1, 0, description)
        self.assertEqual(self.session.calls[0][2]["json"]["details"], description)

    def test_backpack_listings_reject_token_from_another_account(self):
        client = BackpackClient({"backpack_token": "SECRET", "steam_id": OWNER})
        self.session.responses = [Response({"results": [{"id": "440_123", "steamid": "76561198000000001"}],
                                           "cursor": {"skip": 0, "limit": 100, "total": 1}})]
        with self.assertRaises(ServiceError):
            client.listings()

    def test_backpack_reads_all_result_cursor_pages_and_preserves_price(self):
        client = BackpackClient({"backpack_token": "SECRET", "steam_id": OWNER})
        self.session.responses = [
            Response({"results": [{"id": "440_123", "steamid": OWNER, "currencies": {"keys": 1, "metal": 15}, "item": {"id": "123"}}], "cursor": {"skip": 0, "limit": 1, "total": 2}}),
            Response({"results": [{"id": "440_456", "steamid": OWNER, "currencies": {"keys": 2, "metal": .11}, "item": {"id": "456"}}], "cursor": {"skip": 1, "limit": 1, "total": 2}}),
        ]
        values = client.listings()
        self.assertEqual([v["asset_id"] for v in values], ["123", "456"])
        self.assertEqual(values[0]["currencies"], {"keys": 1, "metal": 15})
        self.assertEqual(self.session.calls[1][2]["params"]["skip"], 1)

    def test_backpack_listings_requires_complete_cursor_even_for_empty_results(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        for body in [[], {"results": []}, {"results": [], "cursor": None},
                     {"results": [], "cursor": []}, {"results": [], "cursor": {}},
                     {"results": [], "cursor": {"skip": 0, "limit": 100}}]:
            with self.subTest(body=body):
                self.session.responses = [Response(body)]
                with self.assertRaises(ServiceError):
                    client.listings()

    def test_backpack_listings_rejects_inconsistent_cursor_and_short_page(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        invalid = [
            {"skip": 1, "limit": 100, "total": 1},
            {"skip": 0, "limit": 0, "total": 1},
            {"skip": 0, "limit": -1, "total": 1},
            {"skip": 0, "limit": 100, "total": 0},
            {"skip": 0, "limit": 100, "total": 2},
            {"skip": False, "limit": 100, "total": 1},
            {"skip": 0, "limit": 100.0, "total": 1},
            {"skip": 0, "limit": 100, "total": "oops"},
        ]
        for cursor in invalid:
            with self.subTest(cursor=cursor):
                self.session.responses = [Response({"results": [{"id": "440_123"}], "cursor": cursor})]
                with self.assertRaises(ServiceError):
                    client.listings()

    def test_backpack_listings_does_not_return_partial_results_after_late_failure(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        first = {"results": [{"id": "440_123"}], "cursor": {"skip": 0, "limit": 1, "total": 2}}
        for last in [
            {"results": [], "cursor": {"skip": 1, "limit": 1, "total": 2}},
            {"results": [{"id": "440_456"}], "cursor": {"skip": 1, "limit": 1, "total": 3}},
            {"results": [{"id": "440_123"}], "cursor": {"skip": 1, "limit": 1, "total": 2}},
        ]:
            with self.subTest(last=last):
                self.session.responses = [Response(first), Response(last)]
                with self.assertRaises(ServiceError):
                    client.listings()

    def test_backpack_listings_accepts_valid_empty_result_and_numeric_string_cursor(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        self.session.responses = [Response({"results": [], "cursor": {"skip": "0", "limit": "100", "total": "0"}})]
        self.assertEqual(client.listings(), [])

    def test_backpack_check_does_not_advertise_automation(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        self.session.responses = [Response({"results": [], "cursor": {"skip": 0, "limit": 100, "total": 0}})]
        self.assertTrue(client.check()["ok"])
        self.assertTrue(all(method == "GET" and "/agent/" not in url for method, url, _ in self.session.calls))

    def test_http_errors_are_safe_closed_and_no_redirects(self):
        client = BackpackClient({"backpack_token": "SECRET"})
        response = Response({"message": "SECRET"}, status=503)
        self.session.responses = [response]
        with self.assertRaises(ServiceError) as caught:
            client.create("123", 1, 0, "")
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertTrue(caught.exception.uncertain)
        self.assertTrue(response.closed)
        self.assertFalse(self.session.calls[0][2]["allow_redirects"])

    def test_telegram_sends_inline_buttons_and_no_parse_mode(self):
        client = TelegramClient({"telegram_token": "123:SECRET", "telegram_chat_id": "42"})
        self.session.responses = [Response({"ok": True, "result": {"message_id": 1}})]
        buttons = [[{"text": "РџСЂРёРЅСЏС‚СЊ", "callback_data": "approve:1"}]]
        client.send("<untrusted name>", buttons)
        body = self.session.calls[0][2]["json"]
        self.assertEqual(body["reply_markup"]["inline_keyboard"], buttons)
        self.assertNotIn("parse_mode", body)

    def test_telegram_uses_supplied_offset_and_bounded_long_poll(self):
        client = TelegramClient({"telegram_token": "123:SECRET"})
        self.session.responses = [Response({"ok": True, "result": []})]
        self.assertEqual(client.poll(101, timeout=999), [])
        body = self.session.calls[0][2]["json"]
        self.assertEqual(body["offset"], 101)
        self.assertEqual(body["timeout"], 25)
        self.assertIn("callback_query", body["allowed_updates"])


if __name__ == "__main__":
    unittest.main()
