"""Generación de un fichero SEPA pain.001.001.03 ("Customer Credit Transfer
Initiation", el estándar de transferencia por lote que cualquier banco de
la eurozona acepta) para pagar las nóminas ya generadas de un mes -- en vez
de una integración Open Banking/PSD2 en vivo, que exigiría certificarse
como agregador antes de poder implementarse en absoluto (ver README). El
fichero se sube luego a la banca online de la empresa, que es quien lo
ejecuta de verdad: esta aplicación nunca envía dinero ni se conecta a
ningún banco por sí sola.

Dos pasos deliberadamente separados, ambos puros (sin E/S) y con test:
`build_sepa_payments()` decide QUÉ pagos incluir y cuáles omitir (sin IBAN,
importe no positivo) a partir de las nóminas ya generadas de un mes;
`build_sepa_xml()` construye el XML a partir de esa lista ya decidida. Así
la UI puede mostrar qué se va a omitir y por qué ANTES de generar nada, en
vez de que el único modo de descubrirlo sea leer el XML resultante.

Sin BIC (ni de la empresa ni de los empleados, que esta app no recoge): se
usa `<Othr><Id>NOTPROVIDED</Id></Othr>` en FinInstnId, el mecanismo
estándar de SEPA para "solo IBAN" -- el BIC dejó de ser obligatorio para
pagos SEPA domésticos con la actualización de 2016 al Reglamento (UE)
260/2012."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from xml.etree.ElementTree import Element, SubElement, indent, tostring

_NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"


@dataclass(frozen=True, slots=True)
class SepaPayment:
    employee_id: int
    employee_name: str
    iban: str
    amount: float


@dataclass(frozen=True, slots=True)
class SepaBuildResult:
    payments: list[SepaPayment]
    skipped: list[str]


def build_sepa_payments(
    payroll_rows: Sequence[tuple[int, str, str, float]],
) -> SepaBuildResult:
    """`payroll_rows`: (employee_id, employee_name, iban_tal_cual_en_la_ficha,
    neto_a_percibir) -- una fila por nómina ya generada de ese mes."""
    payments: list[SepaPayment] = []
    skipped: list[str] = []
    for employee_id, name, iban, neto in payroll_rows:
        clean_iban = iban.replace(" ", "").strip()
        if not clean_iban:
            skipped.append(f"{name}: sin cuenta bancaria (IBAN) registrada en la ficha")
            continue
        if neto <= 0:
            skipped.append(f"{name}: importe neto no positivo ({neto:.2f} €)")
            continue
        payments.append(
            SepaPayment(employee_id=employee_id, employee_name=name, iban=clean_iban, amount=round(neto, 2))
        )
    return SepaBuildResult(payments=payments, skipped=skipped)


def build_sepa_xml(
    payments: Sequence[SepaPayment],
    *,
    company_name: str,
    company_iban: str,
    requested_execution_date: date,
    message_id: str,
    created_at: datetime,
) -> str:
    if not payments:
        raise ValueError("no hay ningún pago que incluir en el fichero SEPA")
    clean_company_name = company_name.strip()
    if not clean_company_name:
        raise ValueError("falta el nombre de la empresa")
    clean_company_iban = company_iban.replace(" ", "").strip()
    if not clean_company_iban:
        raise ValueError("falta el IBAN de la empresa")

    total = round(sum(p.amount for p in payments), 2)

    doc = Element(
        "Document",
        {
            "xmlns": _NAMESPACE,
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        },
    )
    root = SubElement(doc, "CstmrCdtTrfInitn")

    grp_hdr = SubElement(root, "GrpHdr")
    SubElement(grp_hdr, "MsgId").text = message_id
    SubElement(grp_hdr, "CreDtTm").text = created_at.strftime("%Y-%m-%dT%H:%M:%S")
    SubElement(grp_hdr, "NbOfTxs").text = str(len(payments))
    SubElement(grp_hdr, "CtrlSum").text = f"{total:.2f}"
    initg_pty = SubElement(grp_hdr, "InitgPty")
    SubElement(initg_pty, "Nm").text = clean_company_name

    pmt_inf = SubElement(root, "PmtInf")
    SubElement(pmt_inf, "PmtInfId").text = message_id
    SubElement(pmt_inf, "PmtMtd").text = "TRF"
    SubElement(pmt_inf, "BtchBookg").text = "true"
    SubElement(pmt_inf, "NbOfTxs").text = str(len(payments))
    SubElement(pmt_inf, "CtrlSum").text = f"{total:.2f}"
    pmt_tp_inf = SubElement(pmt_inf, "PmtTpInf")
    SubElement(SubElement(pmt_tp_inf, "SvcLvl"), "Cd").text = "SEPA"
    SubElement(pmt_inf, "ReqdExctnDt").text = requested_execution_date.isoformat()
    SubElement(SubElement(pmt_inf, "Dbtr"), "Nm").text = clean_company_name
    SubElement(SubElement(pmt_inf, "DbtrAcct"), "Id").append(
        _text_element("IBAN", clean_company_iban)
    )
    dbtr_agt_fin_instn_id = SubElement(SubElement(pmt_inf, "DbtrAgt"), "FinInstnId")
    SubElement(SubElement(dbtr_agt_fin_instn_id, "Othr"), "Id").text = "NOTPROVIDED"
    SubElement(pmt_inf, "ChrgBr").text = "SLEV"

    for i, payment in enumerate(payments, start=1):
        tx = SubElement(pmt_inf, "CdtTrfTxInf")
        SubElement(SubElement(tx, "PmtId"), "EndToEndId").text = f"{message_id}-{i:04d}"
        SubElement(SubElement(tx, "Amt"), "InstdAmt", {"Ccy": "EUR"}).text = (
            f"{payment.amount:.2f}"
        )
        cdtr_agt_fin_instn_id = SubElement(SubElement(tx, "CdtrAgt"), "FinInstnId")
        SubElement(SubElement(cdtr_agt_fin_instn_id, "Othr"), "Id").text = "NOTPROVIDED"
        SubElement(SubElement(tx, "Cdtr"), "Nm").text = payment.employee_name
        SubElement(SubElement(tx, "CdtrAcct"), "Id").append(_text_element("IBAN", payment.iban))
        SubElement(SubElement(tx, "RmtInf"), "Ustrd").text = (
            f"Nómina {requested_execution_date:%m/%Y}"
        )

    indent(doc, space="  ")
    body = tostring(doc, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


def _text_element(tag: str, text: str) -> Element:
    element = Element(tag)
    element.text = text
    return element
