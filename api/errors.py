"""Shared HTTP authentication and authorization errors."""


class AuthenticationError(PermissionError):
    """Raised when a request lacks valid authentication credentials."""


class AuthorizationError(PermissionError):
    """Raised when an authenticated identity lacks required capability."""
