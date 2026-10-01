"""Service layer (business logic & RBAC boundary).

Every service method that reads/writes data accepts a :class:`Principal`
(or ``None`` for anonymous pre-auth flows such as login/activation) and
enforces its own permission checks through
:func:`dentiva.core.permissions.policy.require`.
"""
