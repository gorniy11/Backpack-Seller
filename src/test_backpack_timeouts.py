import unittest
from unittest.mock import Mock, patch
from clients import BackpackClient, ServiceError


class BackpackTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.client = BackpackClient({'backpack_token': 'test-token'})
        self.addCleanup(self.client.close)

    @patch('clients.time.sleep')
    def test_read_recovers_after_timeout(self, sleep):
        self.client._request = Mock(side_effect=[ServiceError('timeout', transient=True), {'ok': True}])
        self.assertEqual(self.client._call('GET', '/test'), {'ok': True})
        self.assertEqual(self.client._request.call_count, 2)
        self.assertEqual(self.client._request.call_args.kwargs['timeout'], (15, 60))

    @patch('clients.time.sleep')
    def test_lost_write_is_never_repeated(self, sleep):
        self.client._request = Mock(side_effect=ServiceError('timeout', uncertain=True))
        with self.assertRaises(ServiceError):
            self.client._call('POST', '/test', mutation=True)
        self.client._request.assert_called_once()
        self.assertEqual(self.client._request.call_args.kwargs['timeout'], (15, 90))
        sleep.assert_not_called()

    @patch('clients.time.sleep')
    def test_rate_limit_is_not_retried(self, sleep):
        self.client._request = Mock(side_effect=ServiceError('limited', status_code=429, retry_after=120))
        with self.assertRaises(ServiceError):
            self.client._call('GET', '/test')
        self.client._request.assert_called_once()
        sleep.assert_not_called()
