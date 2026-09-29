import datetime
import enum

import pydantic
from pydantic import alias_generators


class Product(enum.StrEnum):
    """An Atlassian product a space can be approved for independently.

    A space is governed once but decided twice: the Information Asset Owner
    can approve it for Jira and refuse it for Confluence, or the other way
    round. The product is therefore a dimension of the approval, not a
    property of the space.
    """

    JIRA = "jira"
    CONFLUENCE = "confluence"


class ProductStatus(enum.StrEnum):
    """Per-product approval state.

    NOT_REQUESTED is a real stored state, not an absence: every request
    carries an entry for every product so the portal can render the whole
    picture from one document. There is deliberately no aggregate status --
    the portal derives "partly approved" itself and it is never stored or
    sent for a single product.
    """

    NOT_REQUESTED = "not-requested"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ProductApproval(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(
        alias_generator=alias_generators.to_camel, populate_by_name=True
    )

    requested: bool = False
    status: ProductStatus = ProductStatus.NOT_REQUESTED
    reviewer_id: str | None = None
    decision_reason: str | None = None
    decided_at: datetime.datetime | None = None


class SpaceAccessRequest(pydantic.BaseModel):
    """A request for governed access to an Atlassian space or project key:
    request -> IAO review -> decision, once per product.

    Backs SpaceGuard (see guard.py) -- once a product is approved, an agent's
    existing tool calls against that space for that product simply start
    succeeding, and there is nothing further for a tool to do.

    There is one of these per (user, space). A later request for a product
    that was never asked for, or was rejected, amends this document rather
    than creating a second one, so a space approved for Jira and pending for
    Confluence is always visible as a single record.
    """

    model_config = pydantic.ConfigDict(
        alias_generator=alias_generators.to_camel, populate_by_name=True
    )

    id: str
    user_id: str
    space_key: str
    reason: str
    iao: str  # nominated information-asset owner, named at request time
    products: dict[Product, ProductApproval]
    data_handling_form_ref: str | None = None
    risk_assessment_ref: str | None = None
    created_at: datetime.datetime

    def product(self, product: Product) -> ProductApproval:
        return self.products.get(product, ProductApproval())

    def is_approved_for(self, product: Product) -> bool:
        return self.product(product).status == ProductStatus.APPROVED

    def has_pending_product(self) -> bool:
        return any(p.status == ProductStatus.PENDING for p in self.products.values())


def empty_products() -> dict[Product, ProductApproval]:
    """Every product, none of them asked for. Requests always carry a full
    set so a caller never has to distinguish "absent" from "not requested"."""
    return {product: ProductApproval() for product in Product}
