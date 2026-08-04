class GoodIdeaError(Exception):
    """Base error with a stable machine-readable code."""

    code = "goodidea_error"


class ValidationError(GoodIdeaError):
    code = "validation_error"


class IntegrityError(GoodIdeaError):
    code = "integrity_error"


class TransactionError(GoodIdeaError):
    code = "transaction_error"


class GitError(GoodIdeaError):
    code = "git_error"
