from decimal import Decimal
from django.utils import timezone
import pytest
from rest_framework import status

from accounts.models import User
from customers.models import Customer
from employees.models import Employee
from core.context import clear_tenant, set_tenant
from loans.models import Loan, LoanInstallment, LoanPayment
from loans.services import create_loan, register_payment
from tenants.models import Membership, Tool
from tenants.services import enable_tool


def _setup_tenant(two_tenants, rls_context):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))
    return owner, tenant


@pytest.mark.django_db
def test_owner_can_edit_loan_without_payments(two_tenants, client_for, rls_context, seeded_tools):
    owner, tenant = _setup_tenant(two_tenants, rls_context)
    rls_context(owner, tenant)
    customer = Customer.unscoped.create(
        tenant=tenant,
        full_name="Carlos Dueñas",
        document_id="111222",
        neighborhood="Centro",
        phone="3001112233",
    )
    loan = Loan.unscoped.create(
        tenant=tenant,
        customer=customer,
        principal=Decimal("100000.00"),
        interest_rate=Decimal("20.00"),
        installments=20,
        frequency="daily",
        start_date=timezone.localdate(),
        total_payable=Decimal("120000.00"),
        balance=Decimal("120000.00"),
        status="active",
    )
    for i in range(1, 21):
        LoanInstallment.unscoped.create(
            tenant=tenant,
            loan=loan,
            number=i,
            due_date=timezone.localdate(),
            amount_due=Decimal("6000.00"),
            amount_paid=Decimal("0.00"),
            status="pending",
        )

    client = client_for(owner, tenant)
    response = client.patch(
        f"/api/v1/loans/{loan.id}/",
        {
            "principal": "200000.00",
            "interest_rate": "10.00",
            "installments": 10,
            "paperwork_fee": "5000.00",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK

    rls_context(owner, tenant)
    loan.refresh_from_db()
    assert loan.principal == Decimal("200000.00")
    assert loan.interest_rate == Decimal("10.00")
    assert loan.total_payable == Decimal("220000.00")
    assert loan.balance == Decimal("220000.00")
    assert loan.installments == 10
    assert loan.paperwork_fee == Decimal("5000.00")
    assert loan.schedule.count() == 10
    assert loan.schedule.first().amount_due == Decimal("22000.00")


@pytest.mark.django_db
def test_owner_can_edit_loan_with_existing_payments(two_tenants, client_for, rls_context, seeded_tools):
    owner, tenant = _setup_tenant(two_tenants, rls_context)
    rls_context(owner, tenant)
    customer = Customer.unscoped.create(
        tenant=tenant,
        full_name="Maria Gomez",
        document_id="222333",
        neighborhood="Norte",
    )
    collector = Employee.unscoped.create(
        tenant=tenant,
        full_name="Cobrador Juan",
        is_active=True,
    )
    loan = Loan.unscoped.create(
        tenant=tenant,
        customer=customer,
        collector=collector,
        principal=Decimal("100000.00"),
        interest_rate=Decimal("20.00"),
        installments=5,
        frequency="daily",
        start_date=timezone.localdate(),
        total_payable=Decimal("120000.00"),
        balance=Decimal("120000.00"),
        status="active",
    )
    for i in range(1, 6):
        LoanInstallment.unscoped.create(
            tenant=tenant,
            loan=loan,
            number=i,
            due_date=timezone.localdate(),
            amount_due=Decimal("24000.00"),
            amount_paid=Decimal("0.00"),
            status="pending",
        )

    # Register payment of $24,000
    register_payment(
        loan=loan,
        collector=collector,
        amount=Decimal("24000.00"),
        user=owner,
    )
    loan.refresh_from_db()
    assert loan.balance == Decimal("96000.00")

    # Owner edits loan to 4 installments and rate 25% (Total: $125,000)
    client = client_for(owner, tenant)
    response = client.patch(
        f"/api/v1/loans/{loan.id}/",
        {
            "interest_rate": "25.00",
            "installments": 4,
        },
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK

    rls_context(owner, tenant)
    loan.refresh_from_db()
    assert loan.total_payable == Decimal("125000.00")
    # Balance should be total_payable (125000) - payment (24000) = 101000
    assert loan.balance == Decimal("101000.00")
    assert loan.schedule.count() == 4
    assert LoanPayment.objects.filter(loan=loan).count() == 1
    assert loan.schedule.first().amount_paid == Decimal("24000.00")


@pytest.mark.django_db
def test_edit_loan_rejects_lower_total_than_collected(two_tenants, client_for, rls_context, seeded_tools):
    owner, tenant = _setup_tenant(two_tenants, rls_context)
    rls_context(owner, tenant)
    customer = Customer.unscoped.create(
        tenant=tenant,
        full_name="Luis Perez",
        document_id="333444",
        neighborhood="Sur",
    )
    collector = Employee.unscoped.create(
        tenant=tenant,
        full_name="Cobrador Juan",
        is_active=True,
    )
    loan = Loan.unscoped.create(
        tenant=tenant,
        customer=customer,
        collector=collector,
        principal=Decimal("100000.00"),
        interest_rate=Decimal("20.00"),
        installments=2,
        frequency="daily",
        start_date=timezone.localdate(),
        total_payable=Decimal("120000.00"),
        balance=Decimal("120000.00"),
        status="active",
    )
    for i in range(1, 3):
        LoanInstallment.unscoped.create(
            tenant=tenant,
            loan=loan,
            number=i,
            due_date=timezone.localdate(),
            amount_due=Decimal("60000.00"),
            amount_paid=Decimal("0.00"),
            status="pending",
        )

    # Pay 60,000
    register_payment(loan=loan, collector=collector, amount=Decimal("60000.00"), user=owner)

    # Try to edit principal to 40,000 (total payable 48,000 < 60,000 collected)
    client = client_for(owner, tenant)
    response = client.patch(
        f"/api/v1/loans/{loan.id}/",
        {"principal": "40000.00"},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "no puede ser menor a lo ya cobrado" in str(response.data)


@pytest.mark.django_db
def test_soft_delete_and_restore_loan(two_tenants, client_for, rls_context, seeded_tools):
    owner, tenant = _setup_tenant(two_tenants, rls_context)
    rls_context(owner, tenant)
    customer = Customer.unscoped.create(
        tenant=tenant,
        full_name="Pedro Ramirez",
        document_id="555666",
        neighborhood="Centro",
    )
    loan = Loan.unscoped.create(
        tenant=tenant,
        customer=customer,
        principal=Decimal("50000.00"),
        interest_rate=Decimal("20.00"),
        installments=5,
        frequency="daily",
        start_date=timezone.localdate(),
        total_payable=Decimal("60000.00"),
        balance=Decimal("60000.00"),
        status="active",
    )

    client = client_for(owner, tenant)

    # Verify loan appears in standard list
    res_list = client.get("/api/v1/loans/")
    assert res_list.status_code == status.HTTP_200_OK
    assert len(res_list.data) == 1

    # Owner deletes loan
    res_del = client.delete(f"/api/v1/loans/{loan.id}/")
    assert res_del.status_code == status.HTTP_204_NO_CONTENT

    loan.refresh_from_db()
    assert loan.deleted_at is not None

    # Excluded from active list
    res_list2 = client.get("/api/v1/loans/")
    assert len(res_list2.data) == 0

    # Excluded from collection-today
    res_today = client.get("/api/v1/loans/collection-today/")
    assert len(res_today.data) == 0

    # Included in trash
    res_trash = client.get("/api/v1/loans/trash/")
    assert res_trash.status_code == status.HTTP_200_OK
    assert len(res_trash.data) == 1
    assert res_trash.data[0]["id"] == str(loan.id)

    # Restore loan
    res_restore = client.post(f"/api/v1/loans/{loan.id}/restore/")
    assert res_restore.status_code == status.HTTP_200_OK

    loan.refresh_from_db()
    assert loan.deleted_at is None

    # Reappears in active list
    res_list3 = client.get("/api/v1/loans/")
    assert len(res_list3.data) == 1


@pytest.mark.django_db
def test_employee_can_create_loan_assigned_to_themselves(two_tenants, client_for, rls_context, seeded_tools):
    owner, tenant = _setup_tenant(two_tenants, rls_context)
    emp_user = User.objects.create(email="cobrador@example.test")
    rls_context(owner, tenant)
    Membership.objects.create(user=emp_user, tenant=tenant, role=Membership.Role.EMPLOYEE)
    rls_context(emp_user, tenant)
    collector = Employee.unscoped.create(
        tenant=tenant,
        user=emp_user,
        full_name="Cobrador Movil",
        is_active=True,
    )

    client = client_for(emp_user, tenant)
    response = client.post(
        "/api/v1/loans/",
        {
            "customer_details": {
                "full_name": "Cliente en Ruta",
                "document_id": "999000",
                "neighborhood": "Centro",
                "phone": "3110001122",
            },
            "principal": "100000.00",
            "interest_rate": "20.00",
            "is_open_ended": True,
            "frequency": "daily",
            "start_date": timezone.localdate().isoformat(),
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.data
    assert data["collector_name"] == "Cobrador Movil"

    rls_context(owner, tenant)
    created = Loan.objects.get(pk=data["id"])
    assert created.collector == collector


@pytest.mark.django_db
def test_employee_cannot_edit_or_delete_loan(two_tenants, client_for, rls_context, seeded_tools):
    owner, tenant = _setup_tenant(two_tenants, rls_context)
    emp_user = User.objects.create(email="cobrador2@example.test")
    rls_context(owner, tenant)
    Membership.objects.create(user=emp_user, tenant=tenant, role=Membership.Role.EMPLOYEE)
    customer = Customer.unscoped.create(
        tenant=tenant,
        full_name="Ana Restrepo",
        document_id="444555",
        neighborhood="Centro",
    )
    loan = Loan.unscoped.create(
        tenant=tenant,
        customer=customer,
        principal=Decimal("50000.00"),
        interest_rate=Decimal("20.00"),
        installments=5,
        frequency="daily",
        start_date=timezone.localdate(),
        total_payable=Decimal("60000.00"),
        balance=Decimal("60000.00"),
        status="active",
    )

    client = client_for(emp_user, tenant)

    # Employee tries to update -> 403 Forbidden
    res_patch = client.patch(f"/api/v1/loans/{loan.id}/", {"principal": "80000.00"}, format="json")
    assert res_patch.status_code == status.HTTP_403_FORBIDDEN

    # Employee tries to delete -> 403 Forbidden
    res_del = client.delete(f"/api/v1/loans/{loan.id}/")
    assert res_del.status_code == status.HTTP_403_FORBIDDEN
