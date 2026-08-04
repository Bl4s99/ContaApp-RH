from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from app.gestoria_export import build_gestoria_rows, write_gestoria_csv
from app.models import Employee, PayrollRecord
from app.payroll import MonthlyPayroll


def make_employee(**overrides: object) -> Employee:
    defaults: dict[str, object] = dict(
        id=1,
        first_name="Ana",
        last_name="López",
        email="ana@example.com",
        phone="+34600111222",
        position="Comercial",
        department_id=1,
        shift_id=None,
        salary=28000.0,
        hire_date=date(2023, 1, 1),
        active=True,
        bank_account="ES91 2100 0418 4502 0005 1332",
        photo=None,
        dependent_children=0,
        dni_nie="12345678Z",
        ss_number="281234567890",
        contract_type="Indefinido",
        contract_end_date=None,
        birth_date=None,
        next_medical_checkup_date=None,
        termination_date=None,
        termination_reason=None,
        anonymized=False,
        prl_training_date=None,
        manager_id=None,
        head_of_department_id=None,
        professional_category_id=None,
    )
    defaults.update(overrides)
    return Employee(**defaults)  # type: ignore[arg-type]


def make_record(**overrides: object) -> PayrollRecord:
    payroll_defaults: dict[str, object] = dict(
        month=3,
        year=2026,
        paga_ordinaria=2000.0,
        paga_extra=0.0,
        supplements_total=100.0,
        bruto_mes=2100.0,
        irpf_pct=15.0,
        irpf_importe=315.0,
        ss_employee_pct=6.35,
        ss_employee_importe=133.35,
        advances_total=50.0,
        neto=1601.65,
        ss_employer_pct=31.4,
        ss_employer_importe=659.4,
        coste_total_empresa=2759.4,
    )
    payroll_overrides = overrides.pop("payroll_overrides", {})
    assert isinstance(payroll_overrides, dict)
    payroll_defaults.update(payroll_overrides)
    record_defaults: dict[str, object] = dict(
        id=1,
        employee_id=1,
        generated_at=datetime(2026, 3, 1, 9, 0),
        annual_gross_salary_snapshot=28000.0,
        dependent_children_snapshot=0,
        payroll=MonthlyPayroll(**payroll_defaults),  # type: ignore[arg-type]
    )
    record_defaults.update(overrides)
    return PayrollRecord(**record_defaults)  # type: ignore[arg-type]


class TestBuildGestoriaRows:
    def test_includes_identity_and_amounts(self) -> None:
        rows = build_gestoria_rows([(make_employee(), "Ventas", make_record())])
        assert len(rows) == 1
        row = rows[0]
        assert row.dni_nie == "12345678Z"
        assert row.ss_number == "281234567890"
        assert row.full_name == "Ana López"
        assert row.department_name == "Ventas"
        assert row.neto == 1601.65
        assert row.iban == "ES91 2100 0418 4502 0005 1332"

    def test_never_omits_an_employee_without_iban(self) -> None:
        rows = build_gestoria_rows(
            [(make_employee(bank_account=""), "Ventas", make_record())]
        )
        assert len(rows) == 1
        assert rows[0].iban == ""

    def test_never_omits_a_zero_net_record(self) -> None:
        record = make_record(payroll_overrides={"neto": 0.0})
        rows = build_gestoria_rows([(make_employee(), "Ventas", record)])
        assert len(rows) == 1

    def test_multiple_entries_preserve_order(self) -> None:
        entries = [
            (make_employee(id=1, first_name="Ana"), "Ventas", make_record(employee_id=1)),
            (make_employee(id=2, first_name="Luis"), "Almacén", make_record(employee_id=2)),
        ]
        rows = build_gestoria_rows(entries)
        assert [r.full_name.split()[0] for r in rows] == ["Ana", "Luis"]


class TestWriteGestoriaCsv:
    def test_writes_semicolon_delimited_header(self, tmp_path: Path) -> None:
        rows = build_gestoria_rows([(make_employee(), "Ventas", make_record())])
        path = tmp_path / "gestoria.csv"
        write_gestoria_csv(rows, path)
        content = path.read_text(encoding="utf-8-sig")
        header = content.splitlines()[0]
        assert "dni_nie;num_seguridad_social;nombre_completo" in header

    def test_formats_amounts_with_comma_decimal(self, tmp_path: Path) -> None:
        rows = build_gestoria_rows([(make_employee(), "Ventas", make_record())])
        path = tmp_path / "gestoria.csv"
        write_gestoria_csv(rows, path)
        content = path.read_text(encoding="utf-8-sig")
        assert "1601,65" in content
        assert "1601.65" not in content

    def test_dates_stay_in_iso_format(self, tmp_path: Path) -> None:
        rows = build_gestoria_rows([(make_employee(), "Ventas", make_record())])
        path = tmp_path / "gestoria.csv"
        write_gestoria_csv(rows, path)
        content = path.read_text(encoding="utf-8-sig")
        assert "2023-01-01" in content

    def test_one_row_per_entry(self, tmp_path: Path) -> None:
        entries = [
            (make_employee(id=1), "Ventas", make_record(employee_id=1)),
            (make_employee(id=2, email="otro@example.com"), "Ventas", make_record(employee_id=2)),
        ]
        rows = build_gestoria_rows(entries)
        path = tmp_path / "gestoria.csv"
        write_gestoria_csv(rows, path)
        content = path.read_text(encoding="utf-8-sig")
        # cabecera + 2 filas + una línea final vacía tras el último salto
        assert len([line for line in content.splitlines() if line]) == 3
