from __future__ import annotations


class GoodIdeaError(Exception):
    """Base error for the deterministic kernel."""


class ValidationError(GoodIdeaError):
    """Input does not satisfy a rule-owned contract."""


class NotFoundError(GoodIdeaError):
    """A referenced data object does not exist."""


class ConflictError(GoodIdeaError):
    """The requested transition conflicts with current facts."""


class TransactionError(GoodIdeaError):
    """A write failed and was restored to its previous state."""
