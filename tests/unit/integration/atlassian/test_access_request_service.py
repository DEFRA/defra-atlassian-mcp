"""The request -> IAO review -> decision workflow, product by product.

The behaviour worth pinning here is that one (user, space) pair owns exactly
one request document. That is what lets the portal render "Jira approved,
Confluence pending" as a single row instead of reconciling two competing
records.
"""

import pytest

from app.integration.atlassian import access_request_service as service_module
from app.integration.atlassian import exceptions, models
from tests.fakes import in_memory_space_access_request_store

JIRA = models.Product.JIRA
CONFLUENCE = models.Product.CONFLUENCE


@pytest.fixture
def store():
    return in_memory_space_access_request_store.InMemorySpaceAccessRequestStore()


@pytest.fixture
def service(store):
    return service_module.SpaceAccessRequestService(store)


async def _request(service, *products, user_id="usr_a", space_key="FARM"):
    return await service.request_access(
        user_id, space_key, "owner@defra.gov.uk", "need it", list(products)
    )


class TestRequestingAccess:
    async def test_marks_every_product_asked_for_as_pending(self, service):
        request = await _request(service, JIRA, CONFLUENCE)

        assert request.product(JIRA).status == models.ProductStatus.PENDING
        assert request.product(CONFLUENCE).status == models.ProductStatus.PENDING

    async def test_records_products_not_asked_for_as_not_requested(self, service):
        request = await _request(service, JIRA)

        confluence = request.product(CONFLUENCE)
        assert confluence.requested is False
        assert confluence.status == models.ProductStatus.NOT_REQUESTED

    async def test_refuses_a_repeat_of_everything_already_open(self, service):
        await _request(service, JIRA, CONFLUENCE)

        with pytest.raises(exceptions.AccessRequestAlreadyOpenError):
            await _request(service, JIRA, CONFLUENCE)

    async def test_refuses_a_product_that_is_already_approved(self, service):
        request = await _request(service, JIRA)
        await service.approve(request.id, JIRA, "usr_iao", "fine")

        with pytest.raises(exceptions.AccessRequestAlreadyOpenError):
            await _request(service, JIRA)

    async def test_a_second_user_gets_their_own_request(self, service):
        first = await _request(service, JIRA, user_id="usr_a")
        second = await _request(service, JIRA, user_id="usr_b")

        assert first.id != second.id


class TestAddingAProductLater:
    async def test_amends_the_same_document(self, service):
        first = await _request(service, JIRA)

        second = await _request(service, CONFLUENCE)

        assert second.id == first.id
        assert second.product(CONFLUENCE).status == models.ProductStatus.PENDING

    async def test_preserves_an_existing_approval(self, service):
        request = await _request(service, JIRA)
        await service.approve(request.id, JIRA, "usr_iao", "fine")

        amended = await _request(service, CONFLUENCE)

        assert amended.product(JIRA).status == models.ProductStatus.APPROVED
        assert amended.product(CONFLUENCE).status == models.ProductStatus.PENDING

    async def test_a_rejected_product_can_be_asked_for_again(self, service):
        """A rejection is a decision about a moment, not a permanent ban --
        the requester can come back with a better justification."""
        request = await _request(service, JIRA)
        await service.reject(request.id, JIRA, "usr_iao", "no case made")

        amended = await _request(service, JIRA)

        assert amended.product(JIRA).status == models.ProductStatus.PENDING
        assert amended.product(JIRA).decision_reason is None
        assert amended.product(JIRA).reviewer_id is None

    async def test_asking_again_updates_the_justification_and_owner(self, service):
        request = await _request(service, JIRA)
        await service.reject(request.id, JIRA, "usr_iao", "no")

        amended = await service.request_access(
            "usr_a", "FARM", "new.owner@defra.gov.uk", "a better reason", [JIRA]
        )

        assert amended.id == request.id
        assert amended.iao == "new.owner@defra.gov.uk"
        assert amended.reason == "a better reason"


class TestDeciding:
    async def test_approving_records_the_reviewer_and_paperwork(self, service):
        request = await _request(service, JIRA, CONFLUENCE)

        decided = await service.approve(
            request.id, JIRA, "usr_iao", "no personal data", "DH-1", "RA-1"
        )

        approval = decided.product(JIRA)
        assert approval.status == models.ProductStatus.APPROVED
        assert approval.reviewer_id == "usr_iao"
        assert approval.decision_reason == "no personal data"
        assert approval.decided_at is not None
        assert decided.data_handling_form_ref == "DH-1"
        assert decided.risk_assessment_ref == "RA-1"

    async def test_approving_one_product_leaves_the_other_pending(self, service):
        request = await _request(service, JIRA, CONFLUENCE)

        decided = await service.approve(request.id, JIRA, "usr_iao", "fine")

        assert decided.product(CONFLUENCE).status == models.ProductStatus.PENDING

    async def test_rejecting_one_product_leaves_the_other_pending(self, service):
        request = await _request(service, JIRA, CONFLUENCE)

        decided = await service.reject(request.id, CONFLUENCE, "usr_iao", "no")

        assert decided.product(CONFLUENCE).status == models.ProductStatus.REJECTED
        assert decided.product(JIRA).status == models.ProductStatus.PENDING

    async def test_a_second_decision_on_the_same_product_conflicts(self, service):
        request = await _request(service, JIRA)
        await service.approve(request.id, JIRA, "usr_iao", "fine")

        with pytest.raises(exceptions.AccessRequestAlreadyDecidedError):
            await service.reject(request.id, JIRA, "usr_iao", "changed my mind")

    async def test_deciding_a_product_nobody_asked_for_conflicts(self, service):
        request = await _request(service, JIRA)

        with pytest.raises(exceptions.AccessRequestAlreadyDecidedError):
            await service.approve(request.id, CONFLUENCE, "usr_iao", "fine")

    async def test_an_unknown_request_is_not_found(self, service):
        with pytest.raises(exceptions.AccessRequestNotFoundError):
            await service.approve("no-such-request", JIRA, "usr_iao", "fine")


class TestListingPending:
    async def test_includes_a_request_with_any_product_still_pending(self, service):
        request = await _request(service, JIRA, CONFLUENCE)
        await service.approve(request.id, JIRA, "usr_iao", "fine")

        assert [r.id for r in await service.list_pending()] == [request.id]

    async def test_excludes_a_request_once_every_product_is_decided(self, service):
        request = await _request(service, JIRA, CONFLUENCE)
        await service.approve(request.id, JIRA, "usr_iao", "fine")
        await service.reject(request.id, CONFLUENCE, "usr_iao", "no")

        assert await service.list_pending() == []

    async def test_excludes_a_request_whose_other_product_was_never_asked_for(
        self, service
    ):
        """not-requested is not pending -- a Jira-only request that has been
        decided is finished, and leaving it on the IAO's queue forever
        because Confluence is untouched would be wrong."""
        request = await _request(service, JIRA)
        await service.approve(request.id, JIRA, "usr_iao", "fine")

        assert await service.list_pending() == []
