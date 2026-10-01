"""Integration test: bootstrap applies migrations and all expected tables exist."""


def test_all_tables_created(session_factory):
    from sqlalchemy import inspect
    ins = inspect(session_factory._engine)
    tables = set(ins.get_table_names())
    expected = {
        "clinic_profile", "role", "permission_assignment", "user", "audit_event",
        "staff", "designation", "dentist", "dentist_designations",
        "patient", "tooth_reference", "visit", "dental_chart_finding",
        "appointment", "queue_entry", "treatment_catalog", "treatment_record",
        "clinical_template_option", "prescription", "prescription_medicine",
        "invoice", "invoice_line_item", "payment_method", "payment",
        "supplier", "inventory_category", "inventory_item", "inventory_movement",
        "accounting_category", "accounting_entry",
        "attachment", "app_setting", "printer_profile", "backup_record",
        "notification",
    }
    missing = expected - tables
    assert not missing, f"Missing tables: {missing}"


def test_foreign_keys_enabled(session_factory):
    with session_factory() as s:
        row = s.connection().exec_driver_sql("PRAGMA foreign_keys").fetchone()
    assert row[0] == 1


def test_wal_mode_enabled(session_factory):
    with session_factory() as s:
        row = s.connection().exec_driver_sql("PRAGMA journal_mode").fetchone()
    assert row[0].lower() == "wal"


def test_seed_data_populated(session_factory):
    from dentiva.models import ClinicalTemplateOption, PaymentMethod, Role, ToothReference
    from sqlalchemy import func, select
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(PaymentMethod)) >= 8
        assert s.scalar(select(func.count()).select_from(Role)) >= 5
        # 32 adult + 20 pediatric = 52 teeth
        assert s.scalar(select(func.count()).select_from(ToothReference)) == 52
        cc = s.scalar(select(func.count()).where(ClinicalTemplateOption.section_key == "cc"))
        assert cc > 0
