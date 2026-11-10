from decimal import Decimal
from io import BytesIO

from django.db.models import Case, DecimalField, F, Sum, When
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from employees.models import Employee

from .models import CollectorDailyCash, CollectorExpense, Loan, LoanPayment


ZERO = Decimal("0.00")
CURRENCY_FORMAT = "$#,##0.00;($#,##0.00);\"$0.00\""

CATEGORY_LABELS = {
    "transport": "Transporte / Gasolina",
    "food": "Alimentación",
    "supplies": "Papelería e insumos",
    "other": "Otro",
}

METHOD_LABELS = {
    "cash": "Efectivo",
    "transfer": "Transferencia",
    "other": "Otro",
}

PERIOD_LABELS = {
    "day": "Diario",
    "week": "Semanal",
    "fortnight": "Quincenal",
    "month": "Mensual",
    "year": "Anual",
}


def _style_sheet(ws, *, currency_cols=(), left_cols=(1,)):
    header_fill = PatternFill(start_color="0B291E", end_color="0B291E", fill_type="solid")
    header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    total_fill = PatternFill(start_color="E4F1EA", end_color="E4F1EA", fill_type="solid")
    total_font = Font(name="Calibri", size=10, bold=True, color="0B291E")
    zebra_fill = PatternFill(start_color="F8FBF9", end_color="F8FBF9", fill_type="solid")
    body_font = Font(name="Calibri", size=10, color="10231B")
    thin_side = Side(border_style="thin", color="DFE8E2")
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    max_row = ws.max_row
    max_col = ws.max_column
    ws.freeze_panes = "A2"

    for col_idx in range(1, max_col + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = cell_border
        cell.alignment = Alignment(
            horizontal="left" if col_idx in left_cols else "right",
            vertical="center",
        )

    for row_idx in range(2, max_row + 1):
        is_total_row = (
            row_idx == max_row
            and str(ws.cell(row=row_idx, column=1).value or "").startswith("TOTAL")
        )
        for col_idx in range(1, max_col + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = cell_border
            if is_total_row:
                cell.fill = total_fill
                cell.font = total_font
            else:
                if row_idx % 2 == 1:
                    cell.fill = zebra_fill
                cell.font = body_font

            if col_idx in currency_cols and isinstance(cell.value, (int, float, Decimal)):
                cell.number_format = CURRENCY_FORMAT
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif col_idx in left_cols:
                cell.alignment = Alignment(horizontal="left", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="right", vertical="center")

    ws.row_dimensions[1].height = 24
    for col_idx in range(1, max_col + 1):
        col_letter = get_column_letter(col_idx)
        max_len = max(
            (len(str(ws.cell(row=r, column=col_idx).value or "")) for r in range(1, max_row + 1)),
            default=10,
        )
        ws.column_dimensions[col_letter].width = max(12, min(max_len + 5, 38))


def build_loans_excel_workbook(
    *,
    tenant,
    period,
    period_start,
    period_end,
    ledger_rows,
    ledger_totals,
):
    wb = Workbook()

    # 1. Hoja: Libro de Cartera
    ws_ledger = wb.active
    ws_ledger.title = "Libro de Cartera"
    ws_ledger.append([
        "ITEM",
        "FECHA DE INICIO",
        "DIA",
        "CLIENTES",
        "ZONA",
        "CONCEPTO",
        "CAPITAL",
        "PAPELERIA",
        "INTERES",
        "TOTAL A PAGAR",
        "ABONO",
        "RECOGIDO",
        "RESTANTE",
    ])
    for row in ledger_rows:
        ws_ledger.append([
            row["item"],
            row["date"],
            row["day"],
            row["customer"],
            row["neighborhood"] or "",
            row["concept"],
            float(Decimal(str(row["principal"]))),
            float(Decimal(str(row["paperwork_fee"]))),
            float(Decimal(str(row["interest"]))),
            float(Decimal(str(row["total_payable"]))),
            float(Decimal(str(row["abono"]))),
            float(Decimal(str(row["collected"]))),
            float(Decimal(str(row["remaining"]))),
        ])
    ws_ledger.append([
        "TOTALES",
        f"{PERIOD_LABELS.get(period, period)} ({period_start.isoformat()} a {period_end.isoformat()})",
        "",
        f"{len(ledger_rows)} préstamos",
        "",
        "",
        float(Decimal(str(ledger_totals["principal"]))),
        float(Decimal(str(ledger_totals["paperwork_fee"]))),
        float(Decimal(str(ledger_totals["interest"]))),
        float(Decimal(str(ledger_totals["total_payable"]))),
        float(Decimal(str(ledger_totals["abono"]))),
        float(Decimal(str(ledger_totals["collected"]))),
        float(Decimal(str(ledger_totals["remaining"]))),
    ])
    _style_sheet(
        ws_ledger,
        currency_cols=(7, 8, 9, 10, 11, 12, 13),
        left_cols=(1, 2, 3, 4, 5, 6),
    )

    # 2. Hoja: Cierre de Caja por Cobrador
    ws_cash = wb.create_sheet(title="Cierre de Caja")
    ws_cash.append([
        "COBRADOR",
        "DINERO INICIAL",
        "RECOGIDO",
        "GASTOS",
        "CAPITAL PRESTADO",
        "PAPELERÍA",
        "SALDO ESPERADO",
    ])
    employees = list(
        Employee.objects.filter(is_active=True, deleted_at__isnull=True).order_by("full_name")
    )
    emp_ids = [emp.pk for emp in employees]
    openings = {
        row["collector_id"]: row["total"] or ZERO
        for row in CollectorDailyCash.objects.filter(
            collector_id__in=emp_ids, date__range=(period_start, period_end)
        ).values("collector_id").annotate(total=Sum("opening_amount"))
    }
    expenses_by_collector = {
        row["collector_id"]: row["total"] or ZERO
        for row in CollectorExpense.objects.filter(
            collector_id__in=emp_ids, spent_on__range=(period_start, period_end)
        ).values("collector_id").annotate(total=Sum("amount"))
    }
    disbursed_loans = {
        row["collector_id"]: row
        for row in Loan.objects.filter(
            collector_id__in=emp_ids,
            created_at__date__range=(period_start, period_end),
            import_reference="",
            deleted_at__isnull=True,
        ).values("collector_id").annotate(
            principal=Sum("principal"),
            paperwork=Sum("paperwork_fee"),
        )
    }
    collected_by_collector = {
        row["collector_id"]: row["total"] or ZERO
        for row in LoanPayment.objects.filter(
            collector_id__in=emp_ids, paid_at__date__range=(period_start, period_end)
        ).annotate(
            signed_amount=Case(
                When(direction="reversal", then=-F("amount")),
                default=F("amount"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        ).values("collector_id").annotate(total=Sum("signed_amount"))
    }

    cash_totals = [ZERO] * 6
    for emp in employees:
        opening = openings.get(emp.pk, ZERO)
        collected = collected_by_collector.get(emp.pk, ZERO)
        expense_total = expenses_by_collector.get(emp.pk, ZERO)
        loan_data = disbursed_loans.get(emp.pk, {})
        principal = loan_data.get("principal") or ZERO
        paperwork = loan_data.get("paperwork") or ZERO
        expected = opening + collected - expense_total - principal + paperwork
        values = [opening, collected, expense_total, principal, paperwork, expected]
        for idx, val in enumerate(values):
            cash_totals[idx] += val
        ws_cash.append([emp.full_name, *[float(v) for v in values]])

    ws_cash.append(["TOTALES", *[float(v) for v in cash_totals]])
    _style_sheet(ws_cash, currency_cols=(2, 3, 4, 5, 6, 7), left_cols=(1,))

    # 3. Hoja: Gastos del Período
    ws_expenses = wb.create_sheet(title="Gastos")
    ws_expenses.append([
        "FECHA",
        "COBRADOR",
        "CATEGORÍA",
        "DESCRIPCIÓN",
        "OBSERVACIONES",
        "VALOR",
    ])
    expense_qs = (
        CollectorExpense.objects.filter(spent_on__range=(period_start, period_end))
        .select_related("collector")
        .order_by("spent_on", "created_at")
    )
    total_expense_amount = ZERO
    for exp in expense_qs:
        total_expense_amount += exp.amount
        ws_expenses.append([
            exp.spent_on.isoformat(),
            exp.collector.full_name,
            CATEGORY_LABELS.get(exp.category, exp.category),
            exp.description,
            exp.notes or "",
            float(exp.amount),
        ])
    ws_expenses.append(["TOTAL GASTOS", "", "", "", "", float(total_expense_amount)])
    _style_sheet(ws_expenses, currency_cols=(6,), left_cols=(1, 2, 3, 4, 5))

    # 4. Hoja: Abonos y Reversas del Período
    ws_payments = wb.create_sheet(title="Abonos del Período")
    ws_payments.append([
        "FECHA",
        "HORA",
        "CLIENTE",
        "ZONA",
        "COBRADOR",
        "MÉTODO",
        "MOVIMIENTO",
        "VALOR NETO",
    ])
    payments_qs = (
        LoanPayment.objects.filter(paid_at__date__range=(period_start, period_end))
        .select_related("loan__customer", "collector")
        .order_by("paid_at", "id")
    )
    total_payments_amount = ZERO
    for pmt in payments_qs:
        local_dt = timezone.localtime(pmt.paid_at)
        signed = -pmt.amount if pmt.direction == "reversal" else pmt.amount
        total_payments_amount += signed
        ws_payments.append([
            local_dt.date().isoformat(),
            local_dt.strftime("%H:%M:%S"),
            pmt.loan.customer.full_name,
            pmt.loan.customer.neighborhood or "",
            pmt.collector.full_name,
            METHOD_LABELS.get(pmt.method, pmt.method),
            "Reversa" if pmt.direction == "reversal" else "Abono",
            float(signed),
        ])
    ws_payments.append([
        "TOTAL RECOGIDO",
        "",
        "",
        "",
        "",
        "",
        "",
        float(total_payments_amount),
    ])
    _style_sheet(ws_payments, currency_cols=(8,), left_cols=(1, 2, 3, 4, 5, 6, 7))

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
