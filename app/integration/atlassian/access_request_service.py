import datetime
import uuid
from collections.abc import Iterable

from app.integration.atlassian import exceptions, models, ports

_OPEN_STATUSES = frozenset(
    {models.ProductStatus.PENDING, models.ProductStatus.APPROVED}
)


class SpaceAccessRequestService:
    """The request -> IAO review -> decision workflow backing SpaceGuard's
    AllowListSpaceGuard (see guard.py). Routers use this, never the store
    directly.

    There is exactly one request document per (user, space). Asking for a
    product that was never requested, or that was rejected, amends that
    document in place; the id and created_at stay put. That is what keeps a
    space approved for Jira and pending for Confluence visible as one record
    rather than two competing ones.
    """

    def __init__(self, store: ports.SpaceAccessRequestStore) -> None:
        self._store = store

    async def request_access(
        self,
        user_id: str,
        space_key: str,
        iao: str,
        reason: str,
        products: Iterable[models.Product],
    ) -> models.SpaceAccessRequest:
        wanted = list(dict.fromkeys(products))
        existing = await self._store.get_for_user_and_space(user_id, space_key)

        if existing is None:
            request = models.SpaceAccessRequest(
                id=str(uuid.uuid4()),
                user_id=user_id,
                space_key=space_key,
                iao=iao,
                reason=reason,
                products=models.empty_products(),
                created_at=_now(),
            )
            for product in wanted:
                request.products[product] = _pending()
            await self._store.create(request)
            return request

        addable = [
            product
            for product in wanted
            if existing.product(product).status not in _OPEN_STATUSES
        ]

        if not addable:
            msg = (
                f"A pending or approved request already exists for "
                f"{space_key} and every product asked for."
            )
            raise exceptions.AccessRequestAlreadyOpenError(msg)

        for product in addable:
            existing.products[product] = _pending()

        # The latest ask carries the current justification and owner.
        existing.iao = iao
        existing.reason = reason

        await self._store.update(existing)
        return existing

    async def get_for_user(
        self, user_id: str, space_key: str
    ) -> models.SpaceAccessRequest | None:
        return await self._store.get_for_user_and_space(user_id, space_key)

    async def list_for_user(self, user_id: str) -> list[models.SpaceAccessRequest]:
        return await self._store.list_for_user(user_id)

    async def list_pending(self) -> list[models.SpaceAccessRequest]:
        return await self._store.list_pending()

    async def approve(
        self,
        request_id: str,
        product: models.Product,
        reviewer_id: str,
        decision_reason: str,
        data_handling_form_ref: str | None = None,
        risk_assessment_ref: str | None = None,
    ) -> models.SpaceAccessRequest:
        """Approve one product, leaving every other product exactly as it
        was. Approving a space for both products means two calls."""
        request = await self._get_with_pending_product(request_id, product)

        request.products[product] = models.ProductApproval(
            requested=True,
            status=models.ProductStatus.APPROVED,
            reviewer_id=reviewer_id,
            decision_reason=decision_reason,
            decided_at=_now(),
        )

        # The supporting paperwork is recorded per request, not per product:
        # a later decision that cites a new form reference supersedes the
        # earlier one rather than sitting alongside it.
        if data_handling_form_ref is not None:
            request.data_handling_form_ref = data_handling_form_ref
        if risk_assessment_ref is not None:
            request.risk_assessment_ref = risk_assessment_ref

        await self._store.update(request)
        return request

    async def reject(
        self,
        request_id: str,
        product: models.Product,
        reviewer_id: str,
        decision_reason: str,
    ) -> models.SpaceAccessRequest:
        """Reject one product, leaving every other product exactly as it
        was."""
        request = await self._get_with_pending_product(request_id, product)

        request.products[product] = models.ProductApproval(
            requested=True,
            status=models.ProductStatus.REJECTED,
            reviewer_id=reviewer_id,
            decision_reason=decision_reason,
            decided_at=_now(),
        )

        await self._store.update(request)
        return request

    async def _get_with_pending_product(
        self, request_id: str, product: models.Product
    ) -> models.SpaceAccessRequest:
        request = await self._store.get(request_id)

        if request is None:
            msg = f"No access request {request_id}"
            raise exceptions.AccessRequestNotFoundError(msg)

        status = request.product(product).status
        if status != models.ProductStatus.PENDING:
            msg = (
                f"Access request {request_id} is already {status.value} "
                f"for {product.value}"
            )
            raise exceptions.AccessRequestAlreadyDecidedError(msg)

        return request


def _pending() -> models.ProductApproval:
    return models.ProductApproval(requested=True, status=models.ProductStatus.PENDING)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
