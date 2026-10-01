import pytest
from dentiva.core.errors import PermissionDeniedError
from dentiva.core.permissions import Permission, Principal, policy


def test_superuser_has_everything():
    p = Principal(1, "root", "Root", [], is_superuser=True)
    for perm in Permission:
        assert p.has(perm)


def test_regular_user_lacks_other_perms():
    p = Principal(2, "recep", "Receptionist", [Permission.PATIENTS_VIEW])
    assert p.has(Permission.PATIENTS_VIEW)
    assert not p.has(Permission.FINANCIAL_REPORTS_VIEW)


def test_policy_require_raises():
    p = Principal(3, "u", "U", [Permission.PATIENTS_VIEW])
    policy.require(p, Permission.PATIENTS_VIEW)  # ok
    with pytest.raises(PermissionDeniedError):
        policy.require(p, Permission.ACCOUNTING_MANAGE)


def test_can_view_financials():
    assert not Principal(4, "u", "U", [Permission.PATIENTS_VIEW]).can_view_financials()
    assert Principal(5, "u", "U", [Permission.INVOICES_VIEW]).can_view_financials()
