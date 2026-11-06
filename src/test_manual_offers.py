import copy
import unittest
from clients import ServiceError, SteamClient
import test_engine as fixtures


class ManualOfferTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.engine = self.fixture.engine
        self.engine.monitoring = True

    def test_valid_offer_only_sends_verdict_and_item_quantities(self):
        self.engine._record_offer(fixtures.offer())
        row = self.engine.store.get('offers', '9988')
        self.assertTrue(row['valid'])
        self.assertEqual(row['status'], 'manual')
        text = self.fixture.telegram.send.call_args.args[0]
        self.assertIn('× 1', text)
        self.assertIn('Проверка пройдена', text)
        self.fixture.steam.accept.assert_not_called()
        self.fixture.steam.decline.assert_not_called()
        self.assertFalse(hasattr(SteamClient, 'accept'))
        self.assertFalse(hasattr(self.engine, 'accept'))

    def test_invalid_offer_is_reported_without_trade_writes(self):
        offer = fixtures.offer()
        offer['items_to_receive'] = []
        self.engine._record_offer(offer)
        self.assertFalse(self.engine.store.get('offers', '9988')['valid'])
        self.assertIn('Проверка не пройдена', self.fixture.telegram.send.call_args.args[0])
        self.fixture.steam.accept.assert_not_called()
        self.fixture.steam.decline.assert_not_called()

    def test_same_offer_notification_is_not_repeated(self):
        self.engine._record_offer(fixtures.offer())
        self.engine._record_offer(fixtures.offer())
        self.fixture.telegram.send.assert_called_once()

    def test_unavailable_site_is_reported_as_unverified(self):
        self.fixture.backpack.listings.side_effect = ServiceError('offline')
        self.engine._record_offer(fixtures.offer())
        self.assertFalse(self.engine.store.get('offers', '9988')['valid'])
        self.assertNotIn('Обмен не принят', self.fixture.telegram.send.call_args.args[0])

    def test_description_template_is_saved_and_used(self):
        template = 'My {name}: {price} {paint}'
        self.engine.save_settings({'description_template': template})
        self.assertEqual(self.engine.settings()['description_template'], template)
        self.fixture.reopen()
        self.assertEqual(self.fixture.engine.settings()['description_template'], template)
