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




