from __future__ import annotations

from datetime import date, datetime

import pytest

from app.sepa_export import SepaPayment, build_sepa_payments, build_sepa_xml

CREATED_AT = datetime(2026, 8, 4, 12, 0, 0)
EXEC_DATE = date(2026, 8, 10)


class TestBuildSepaPayments:
    def test_includes_valid_payments(self) -> None:
        result = build_sepa_payments([(1, "Ana López", "ES9121000418450200051332", 1800.60)])
        assert len(result.payments) == 1
        assert result.payments[0].employee_id == 1
        assert result.payments[0].employee_name == "Ana López"
        assert result.payments[0].amount == 1800.60
        assert result.skipped == []

    def test_skips_employee_without_iban(self) -> None:
        result = build_sepa_payments([(1, "Luis Pérez", "", 1500.0)])
        assert result.payments == []
        assert "Luis Pérez" in result.skipped[0]
        assert "IBAN" in result.skipped[0]

    def test_skips_employee_with_only_whitespace_iban(self) -> None:
        result = build_sepa_payments([(1, "Luis Pérez", "   ", 1500.0)])
        assert result.payments == []

    def test_skips_non_positive_amount(self) -> None:
        result = build_sepa_payments([(1, "Marta Ruiz", "ES9121000418450200051332", 0.0)])
        assert result.payments == []
        assert "Marta Ruiz" in result.skipped[0]

    def test_skips_negative_amount(self) -> None:
        result = build_sepa_payments([(1, "Marta Ruiz", "ES9121000418450200051332", -50.0)])
        assert result.payments == []

    def test_strips_spaces_from_stored_iban(self) -> None:
        result = build_sepa_payments([(1, "Ana López", "ES91 2100 0418 4502 0005 1332", 100.0)])
        assert result.payments[0].iban == "ES9121000418450200051332"

    def test_mixed_valid_and_skipped(self) -> None:
        result = build_sepa_payments(
            [
                (1, "Ana López", "ES9121000418450200051332", 1800.60),
                (2, "Luis Pérez", "", 1500.0),
            ]
        )
        assert len(result.payments) == 1
        assert len(result.skipped) == 1


class TestBuildSepaXml:
    def _payment(self, **overrides: object) -> SepaPayment:
        defaults: dict[str, object] = dict(
            employee_id=1, employee_name="Ana López", iban="ES9121000418450200051332", amount=1800.60
        )
        defaults.update(overrides)
        return SepaPayment(**defaults)  # type: ignore[arg-type]

    def _build(self, payments: list[SepaPayment], **overrides: object) -> str:
        defaults: dict[str, object] = dict(
            company_name="Empresa Ficticia S.L.",
            company_iban="ES9121000418450200051332",
            requested_execution_date=EXEC_DATE,
            message_id="NOM20260804120000",
            created_at=CREATED_AT,
        )
        defaults.update(overrides)
        return build_sepa_xml(payments, **defaults)  # type: ignore[arg-type]

    def test_rejects_empty_payments(self) -> None:
        with pytest.raises(ValueError):
            self._build([])

    def test_rejects_missing_company_name(self) -> None:
        with pytest.raises(ValueError):
            self._build([self._payment()], company_name="")

    def test_rejects_missing_company_iban(self) -> None:
        with pytest.raises(ValueError):
            self._build([self._payment()], company_iban="")

    def test_includes_xml_declaration(self) -> None:
        xml = self._build([self._payment()])
        assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')

    def test_uses_the_correct_namespace(self) -> None:
        xml = self._build([self._payment()])
        assert 'xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"' in xml

    def test_includes_company_as_debtor(self) -> None:
        xml = self._build([self._payment()])
        assert "<Dbtr>" in xml
        assert "Empresa Ficticia S.L." in xml
        assert "<IBAN>ES9121000418450200051332</IBAN>" in xml

    def test_includes_each_employee_as_creditor(self) -> None:
        xml = self._build(
            [
                self._payment(employee_name="Ana López", iban="ES9121000418450200051332"),
                self._payment(employee_name="Luis Pérez", iban="ES7921000813610123456789"),
            ]
        )
        assert "Ana López" in xml
        assert "Luis Pérez" in xml
        assert "ES9121000418450200051332" in xml
        assert "ES7921000813610123456789" in xml

    def test_control_sum_matches_total_amount(self) -> None:
        xml = self._build(
            [self._payment(amount=1000.0), self._payment(employee_id=2, amount=500.50)]
        )
        assert xml.count("<CtrlSum>1500.50</CtrlSum>") == 2  # GrpHdr y PmtInf

    def test_number_of_transactions_matches_payment_count(self) -> None:
        xml = self._build([self._payment(), self._payment(employee_id=2)])
        assert xml.count("<NbOfTxs>2</NbOfTxs>") == 2

    def test_uses_notprovided_when_no_bic_available(self) -> None:
        xml = self._build([self._payment()])
        assert xml.count("<Id>NOTPROVIDED</Id>") == 2  # DbtrAgt y CdtrAgt

    def test_requested_execution_date_is_iso_format(self) -> None:
        xml = self._build([self._payment()])
        assert "<ReqdExctnDt>2026-08-10</ReqdExctnDt>" in xml

    def test_end_to_end_id_is_unique_per_payment(self) -> None:
        xml = self._build([self._payment(), self._payment(employee_id=2)])
        assert "NOM20260804120000-0001" in xml
        assert "NOM20260804120000-0002" in xml

    def test_amount_formatted_with_two_decimals_and_currency(self) -> None:
        xml = self._build([self._payment(amount=1800.6)])
        assert '<InstdAmt Ccy="EUR">1800.60</InstdAmt>' in xml
