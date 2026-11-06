"""Recover listing changes by reading their state, not repeating the request."""
import copy
import unittest

import test_engine as fixtures
from clients import ServiceError


class ListingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowTests(methodName="runTest")
        self.fixture.setUp()
        self.engine = self.fixture.engine
        self.backpack = self.fixture.backpack
        self.fixture.steam.inventory.return_value = {
            "success": 1, "assets": [fixtures.asset(100)],
            "descriptions": [fixtures.description(200)]}
        row = self.engine.store.get("listings", "100")
        row.update(status="removed")
        self.engine.store.put("listings", "100", row)
        self.remote = []
        self.backpack.listings.side_effect = lambda: copy.deepcopy(self.remote)
        self.backpack.create.side_effect = self.create_remotely
        self.backpack.delete.side_effect = self.delete_remotely

    def tearDown(self):
        self.fixture.tearDown()

    @staticmethod
    def sale(**changes):
        return dict(listing_id="440_100", asset_id="100", intent="sell",
                    currencies={"keys": 1, "metal": 1}, status="active", source="steam", **changes)

    def create_remotely(self, *args):
        self.remote[:] = [self.sale()]
        return copy.deepcopy(self.remote[0])

    def delete_remotely(self, *args):
        self.remote.clear()
        return {}

    def mark_local(self, status="active", **changes):
        row = self.engine.store.get("listings", "100")
        row.update(status=status, **changes)
        self.engine.store.put("listings", "100", row)
        return row

    def current(self):
        return self.engine.store.get("listings", "100")

    def test_publish_response_lost_after_server_success_is_recovered_once(self):
        def lost(*args):
            self.create_remotely(*args)
            raise ServiceError("response lost", uncertain=True)
        self.backpack.create.side_effect = lost
        self.engine.publish("100", "1", "1")
        self.assertEqual(self.current()["status"], "active")
        self.assertEqual(self.current()["listing_id"], "440_100")
        self.backpack.create.assert_called_once()
        self.assertEqual(self.backpack.listings.call_count, 2)

    def test_successful_creation_rejected_by_old_parser_recovers_even_if_certain(self):
        def rejected(*args):
            self.create_remotely(*args)
            raise ServiceError("old response parser rejected success")
        self.backpack.create.side_effect = rejected
        self.engine.publish("100", "1", "1")
        self.assertEqual(self.current()["status"], "active")
        self.backpack.create.assert_called_once()

    def test_uncertain_create_and_failed_read_stays_unknown_without_retry(self):
        self.backpack.listings.side_effect = [[], ServiceError("read unavailable")]
        self.backpack.create.side_effect = ServiceError("response lost", uncertain=True)
        with self.assertRaises(ServiceError):
            self.engine.publish("100", "1", "1")
        self.assertEqual(self.current()["status"], "publish_unknown")
        self.backpack.create.assert_called_once()

    def test_ambiguous_create_different_remote_price_is_not_trusted(self):
        def other_price(*args):
            self.remote[:] = [{**self.sale(), "currencies": {"keys": 2, "metal": 1}}]
            raise ServiceError("response lost", uncertain=True)
        self.backpack.create.side_effect = other_price
        with self.assertRaises(ServiceError):
            self.engine.publish("100", "1", "1")
        self.assertEqual(self.current()["status"], "external_change")
        self.backpack.create.assert_called_once()

    def test_republication_after_old_delete_error_checks_absence_and_sends_once(self):
        self.mark_local("external_change")
        self.engine.publish("100", "1", "1")
        self.assertEqual(self.current()["status"], "active")
        self.backpack.create.assert_called_once()

    def test_remote_success_old_error_row_is_adopted_without_republication(self):
        self.mark_local("error", listing_id="")
        self.remote[:] = [self.sale()]
        with self.assertRaises(ValueError):
            self.engine.publish("100", "1", "1")
        self.assertEqual(self.current()["status"], "active")
        self.assertEqual(self.current()["listing_id"], "440_100")
        self.backpack.create.assert_not_called()

    def test_delete_response_lost_after_success_is_removed_and_republishable(self):
        self.mark_local()
        self.remote[:] = [self.sale()]
        def lost(*args):
            self.assertEqual(self.current()["status"], "removing")
            self.delete_remotely(*args)
            raise ServiceError("response lost", uncertain=True)
        self.backpack.delete.side_effect = lost
        self.engine.remove_listing("100")
        self.assertEqual(self.current()["status"], "removed")
        self.backpack.delete.assert_called_once_with("440_100")
        self.engine.publish("100", "1", "1")
        self.assertEqual(self.current()["status"], "active")
        self.backpack.create.assert_called_once()

    def test_delete_not_found_error_after_remote_success_recovers(self):
        self.mark_local()
        self.remote[:] = [self.sale()]
        def gone(*args):
            self.delete_remotely(*args)
            raise ServiceError("not found", status_code=404)
        self.backpack.delete.side_effect = gone
        self.engine.remove_listing("100")
        self.assertEqual(self.current()["status"], "removed")
        self.backpack.delete.assert_called_once()

    def test_failed_delete_still_present_stays_unknown_without_second_delete(self):
        self.mark_local()
        self.remote[:] = [self.sale()]
        self.backpack.delete.side_effect = ServiceError("response lost", uncertain=True)
        with self.assertRaises(ServiceError):
            self.engine.remove_listing("100")
        self.assertEqual(self.current()["status"], "remove_unknown")
        self.backpack.delete.assert_called_once()
        self.engine.reconcile_listings()
        self.assertEqual(self.current()["status"], "remove_unknown")
        self.backpack.delete.assert_called_once()

    def test_already_absent_delete_is_success_without_delete_request(self):
        self.mark_local()
        self.engine.remove_listing("100")
        self.assertEqual(self.current()["status"], "removed")
        self.backpack.delete.assert_not_called()

    def test_restart_after_delete_submission_recovers_absence_without_replay(self):
        self.mark_local("removing")
        self.fixture.reopen()
        self.engine = self.fixture.engine
        self.assertEqual(self.current()["status"], "remove_unknown")
        self.engine.reconcile_listings()
        self.assertEqual(self.current()["status"], "removed")
        self.backpack.delete.assert_not_called()

    def test_reconcile_removes_stale_state_and_recovers_old_publication_error(self):
        self.mark_local("external_change")
        self.engine.reconcile_listings()
        self.assertEqual(self.current()["status"], "removed")
        self.mark_local("error", listing_id="")
        self.remote[:] = [self.sale()]
        self.engine.reconcile_listings()
        self.assertEqual(self.current()["status"], "active")
        self.backpack.create.assert_not_called()
        self.backpack.delete.assert_not_called()

    def test_reserved_item_cannot_be_removed_or_republished(self):
        self.mark_local(reserved_by="offer-in-flight")
        for method, args in ((self.engine.publish, ("100", "1", "1")),
                             (self.engine.remove_listing, ("100",))):
            with self.assertRaises(ValueError):
                method(*args)
        self.backpack.listings.assert_not_called()
        self.backpack.create.assert_not_called()
        self.backpack.delete.assert_not_called()

    def test_remote_nonactive_and_nonsteam_rows_never_authorize_sale(self):
        for changes in ({"status": "archived"}, {"source": "api"}, {"archived": True}):
            with self.subTest(changes=changes):
                self.mark_local()
                self.remote[:] = [{**self.sale(), **changes}]
                self.engine.reconcile_listings()
                self.assertEqual(self.current()["status"], "external_change")

    def test_same_name_other_item_does_not_recover_uncertain_creation(self):
        def another_item(*args):
            self.remote[:] = [{**self.sale(), "asset_id": "101", "listing_id": "440_101"}]
            raise ServiceError("response lost", uncertain=True)
        self.backpack.create.side_effect = another_item
        with self.assertRaises(ServiceError):
            self.engine.publish("100", "1", "1")
        self.assertEqual(self.current()["status"], "publish_unknown")
        self.backpack.create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
