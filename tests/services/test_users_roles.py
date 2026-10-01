"""User/role/audit service tests — default roles, role CRUD with permission matrix,
update_user, activate/deactivate, and audit event filtering."""
from __future__ import annotations

import datetime as dt

import pytest
from dentiva.core.errors import PermissionDeniedError, ValidationError
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import audit_service, user_service


def test_default_roles_listed(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        roles = user_service.list_roles(uow.session, admin_principal)
    names = {r.name for r in roles}
    assert "Administrator" in names or len(roles) >= 4
    for r in roles:
        assert isinstance(r.permissions, list)


def test_create_role_and_permission_validation(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        r = user_service.create_role(
            uow.session, admin_principal,
            name="Front Desk", description="Reception",
            permissions=["patients.view", "appointments.view", "appointments.create"],
        )
        uow.commit()
        rid = r.id
    with UnitOfWork(session_factory) as uow:
        roles = user_service.list_roles(uow.session, admin_principal)
        mine = next(x for x in roles if x.id == rid)
        assert "patients.view" in mine.permissions
        assert "appointments.create" in mine.permissions
        # invalid perm rejected
        with pytest.raises(ValidationError):
            user_service.create_role(
                uow.session, admin_principal, name="Bad", permissions=["not.a.real.perm"]
            )
        # duplicate rejected
        with pytest.raises(ValidationError):
            user_service.create_role(uow.session, admin_principal, name="Front Desk")


def test_update_user_and_role(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        r = user_service.create_role(uow.session, admin_principal, name="Junior Assistant", permissions=["patients.view"])
        uow.commit()
        rid = r.id
        from dentiva.services.auth_service import create_user
        u = create_user(uow.session, admin_principal, username="assist", password="secret1",
                        display_name="Asst", role_id=rid)
        uow.commit()
        uid = u.id
    with UnitOfWork(session_factory) as uow:
        user_service.update_user(uow.session, admin_principal, uid, display_name="Assistant Jr.", username="assist2")
        # change role
        user_service.set_user_role(uow.session, admin_principal, uid, None)
        uow.commit()
        users = user_service.list_users(uow.session, admin_principal)
        me = next(x for x in users if x.id == uid)
        assert me.display_name == "Assistant Jr."
        assert me.username == "assist2"
        assert me.role_id is None
        with pytest.raises(ValidationError):
            user_service.update_user(uow.session, admin_principal, uid, username="ad")  # too short


def test_deactivate_and_reactivate(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        from dentiva.services.auth_service import create_user
        u = create_user(uow.session, admin_principal, username="temp", password="secret1", display_name="Temp", role_id=None)
        uow.commit()
        uid = u.id
    with UnitOfWork(session_factory) as uow:
        user_service.deactivate_user(uow.session, admin_principal, uid)
        uow.commit()
        users = user_service.list_users(uow.session, admin_principal)
        me = next(x for x in users if x.id == uid)
        assert me.is_active is False
        user_service.activate_user(uow.session, admin_principal, uid)
        uow.commit()
        users = user_service.list_users(uow.session, admin_principal)
        me = next(x for x in users if x.id == uid)
        assert me.is_active is True


def test_self_deactivate_blocked(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            user_service.deactivate_user(uow.session, admin_principal, admin_principal.user_id)


def test_audit_list_filters(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        audit_service.record(uow.session, admin_principal, "test.action",
                             entity_type="test_entity", summary="hello world")
        uow.commit()
        today = dt.date.today()
        evts = audit_service.list_events(
            uow.session, admin_principal, limit=10, action="test.action",
            start=dt.datetime.combine(today - dt.timedelta(days=1), dt.time.min),
            end=dt.datetime.combine(today + dt.timedelta(days=1), dt.time.max),
            search="hello",
        )
        assert any("hello world" in e.summary for e in evts)


def test_permission_gating(session_factory):
    from dentiva.core.permissions import Principal
    nobody = Principal(user_id=None, username="nobody", display_name="nobody",
                       permissions=(), is_superuser=False)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(PermissionDeniedError):
            user_service.list_users(uow.session, nobody)
        with pytest.raises(PermissionDeniedError):
            user_service.create_role(uow.session, nobody, name="x")
