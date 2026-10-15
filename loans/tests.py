import pytest
from asgiref.sync import async_to_sync, sync_to_async
from decimal import Decimal
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import User
from accounting.models import EventInbox
from customers.models import Customer
from employees.models import Employee
from loans.models import CollectionRoute, Loan, LoanInstallment, LoanPayment
from loans.views import LoanPaymentEventStreamView
from tenants.models import Membership, Tool
from tenants.services import enable_tool


def _make_employee_and_customer(two_tenants, rls_context, tenant_key="tenant_a"):
    tenant = two_tenants[tenant_key]
    owner = two_tenants["user_a" if tenant_key == "tenant_a" else "user_b"]
    rls_context(owner, tenant)
    employee_user = User.objects.create(
        email=f"collector-{tenant_key}@example.test"
    )
    Membership.objects.create(
        user=employee_user,
        tenant=tenant,
        role=Membership.Role.EMPLOYEE,
    )
    employee = Employee.unscoped.create(
        tenant=tenant,
        user=employee_user,
        full_name="Cobrador",
    )
    customer = Customer.unscoped.create(
        tenant=tenant,
        full_name="Cliente",
    )
    return owner, tenant, employee_user, employee, customer


def _enable_loans(owner, tenant, rls_context):
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))


def _post_loan(client, customer, employee, *, principal="1000.00", rate="20.00"):
    return client.post(
        reverse("loan-list"),
        {
            "customer": str(customer.pk),
            "collector": str(employee.pk),
            "principal": principal,
            "interest_rate": rate,
            "installments": 3,
            "frequency": "monthly",
            "start_date": timezone.localdate().isoformat(),
        },
        format="json",
    )


def _post_payment(client, loan_id, amount):
    return client.post(
        reverse("loan-payment-list"),
        {
            "loan": str(loan_id),
            "amount": str(amount),
            "method": "cash",
        },
        format="json",
    )


@pytest.mark.django_db
def test_loan_delete_requires_owner(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))
    manager = User.objects.create(email="manager@example.test")
    rls_context(owner, tenant)
    Membership.objects.create(user=manager, tenant=tenant, role=Membership.Role.MANAGER)

    rls_context(owner, tenant)
    customer = Customer.unscoped.create(tenant=tenant, full_name="Cliente A")
    loan = Loan.unscoped.create(
        tenant=tenant,
        customer=customer,
        principal=Decimal("1000.00"),
        interest_rate=Decimal("0.00"),
        installments=1,
        start_date="2025-01-01",
        total_payable=Decimal("1000.00"),
        balance=Decimal("1000.00"),
        status="active",
    )

    manager_client = client_for(manager, tenant)
    response = manager_client.delete(reverse("loan-detail", args=[loan.pk]))
    assert response.status_code == status.HTTP_403_FORBIDDEN

    owner_client = client_for(owner, tenant)
    response = owner_client.delete(reverse("loan-detail", args=[loan.pk]))
    assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.django_db
def test_employee_can_list_and_create_loans_and_payments(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner = two_tenants["user_a"]
    tenant = two_tenants["tenant_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))
    user = User.objects.create(email="collector-a@example.test")
    Membership.objects.create(user=user, tenant=tenant, role=Membership.Role.EMPLOYEE)
    rls_context(user, tenant)
    employee = Employee.unscoped.create(
        tenant=tenant,
        user=user,
        full_name="Cobrador A",
    )
    customer = Customer.unscoped.create(tenant=tenant, full_name="Cliente A")

    client = client_for(user, tenant)
    response = client.post(
        reverse("loan-list"),
        {
            "customer": str(customer.pk),
            "collector": str(employee.pk),
            "principal": "1000.00",
            "interest_rate": "0.00",
            "installments": 1,
            "frequency": "monthly",
            "start_date": "2025-01-01",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    loan_id = response.data["id"]
    assert client.get(reverse("loan-list")).status_code == status.HTTP_200_OK

    response = client.post(
        reverse("loan-payment-list"),
        {
            "loan": loan_id,
            "collector": str(employee.pk),
            "amount": "100.00",
            "method": "cash",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    payment_id = response.data["id"]
    assert client.get(reverse("loan-payment-list")).status_code == status.HTTP_200_OK
    assert client.patch(
        reverse("loan-payment-detail", args=[payment_id]),
        {"amount": "1.00"},
        format="json",
    ).status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_loan_amounts_are_calculated_and_payments_update_installments(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner, tenant, employee_user, employee, customer = _make_employee_and_customer(
        two_tenants, rls_context
    )
    _enable_loans(owner, tenant, rls_context)

    response = _post_loan(client_for(owner, tenant), customer, employee)
    assert response.status_code == status.HTTP_201_CREATED
    loan_id = response.data["id"]
    assert response.data["total_payable"] == "1200.00"
    assert response.data["balance"] == "1200.00"
    assert response.data["status"] == "active"
    assert [row["amount_due"] for row in response.data["installment_schedule"]] == [
        "400.00",
        "400.00",
        "400.00",
    ]

    collector_client = client_for(employee_user, tenant)
    negative = _post_payment(collector_client, loan_id, "-1.00")
    assert negative.status_code == status.HTTP_400_BAD_REQUEST
    excessive = _post_payment(collector_client, loan_id, "1200.01")
    assert excessive.status_code == status.HTTP_400_BAD_REQUEST

    partial = _post_payment(collector_client, loan_id, "30.00")
    assert partial.status_code == status.HTTP_201_CREATED
    partial_installments = collector_client.get(reverse("loan-installment-list"))
    assert partial_installments.status_code == status.HTTP_200_OK
    first_installment = next(
        row
        for row in partial_installments.data
        if str(row["loan"]) == loan_id and row["number"] == 1
    )
    assert first_installment["amount_paid"] == "30.00"
    assert first_installment["status"] == "partial"

    loan_detail = client_for(owner, tenant).get(reverse("loan-detail", args=[loan_id]))
    assert loan_detail.data["balance"] == "1170.00"
    assert loan_detail.data["status"] == "active"

    final_payment = _post_payment(collector_client, loan_id, "1170.00")
    assert final_payment.status_code == status.HTTP_201_CREATED
    loan_detail = client_for(owner, tenant).get(reverse("loan-detail", args=[loan_id]))
    assert loan_detail.data["balance"] == "0.00"
    assert loan_detail.data["status"] == "paid"
    assert LoanInstallment.unscoped.filter(
        loan_id=loan_id,
        status="paid",
        amount_paid=Decimal("400.00"),
    ).count() == 3
    assert EventInbox.unscoped.filter(
        tenant_id=tenant.pk,
        event_name="loan.payment_received",
    ).count() == 2


@pytest.mark.django_db
def test_owner_and_admin_receive_live_payment_events(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner, tenant, employee_user, employee, customer = _make_employee_and_customer(
        two_tenants, rls_context
    )
    _enable_loans(owner, tenant, rls_context)
    loan_response = _post_loan(client_for(owner, tenant), customer, employee)
    assert loan_response.status_code == status.HTTP_201_CREATED
    loan_id = loan_response.data["id"]

    rls_context(owner, tenant)
    admin_user = User.objects.create(email="loan-admin@example.test")
    Membership.objects.create(
        user=admin_user,
        tenant=tenant,
        role=Membership.Role.ADMIN,
    )

    stream_url = reverse("loan-payment-events-stream")
    employee_client = client_for(employee_user, tenant)
    assert employee_client.get(stream_url).status_code == status.HTTP_403_FORBIDDEN

    def make_stream_response(user):
        request = APIRequestFactory().get(
            stream_url,
            HTTP_X_TENANT_ID=str(tenant.pk),
        )
        force_authenticate(request, user=user)
        return LoanPaymentEventStreamView.as_view()(request)

    owner_response = make_stream_response(owner)
    admin_response = make_stream_response(admin_user)
    assert owner_response.status_code == admin_response.status_code == status.HTTP_200_OK
    assert owner_response["Content-Type"].startswith("text/event-stream")
    assert owner_response.is_async
    owner_stream = owner_response.streaming_content
    admin_stream = admin_response.streaming_content

    async def receive_live_payment():
        ready_owner = await anext(owner_stream)
        ready_admin = await anext(admin_stream)
        payment_response = await sync_to_async(
            _post_payment,
            thread_sensitive=True,
        )(employee_client, loan_id, "100.00")
        assert payment_response.status_code == status.HTTP_201_CREATED
        owner_event = await anext(owner_stream)
        admin_event = await anext(admin_stream)
        await owner_stream.aclose()
        await admin_stream.aclose()
        return ready_owner, ready_admin, payment_response, owner_event, admin_event

    ready_owner, ready_admin, payment_response, owner_event, admin_event = (
        async_to_sync(receive_live_payment)()
    )
    assert ready_owner == ready_admin == b"event: ready\ndata: {}\n\n"
    for event in (owner_event, admin_event):
        event = event.decode()
        assert "event: loan.payment_received\n" in event
        assert f'"payment_id":"{payment_response.data["id"]}"' in event
        assert '"balance":"1100.00"' in event


@pytest.mark.django_db
def test_loan_rejects_client_supplied_financial_totals(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner, tenant, _, employee, customer = _make_employee_and_customer(
        two_tenants, rls_context
    )
    _enable_loans(owner, tenant, rls_context)
    payload = {
        "customer": str(customer.pk),
        "collector": str(employee.pk),
        "principal": "1000.00",
        "interest_rate": "20.00",
        "installments": 2,
        "frequency": "daily",
        "start_date": timezone.localdate().isoformat(),
        "total_payable": "1.00",
        "balance": "0.00",
        "status": "paid",
    }

    response = client_for(owner, tenant).post(
        reverse("loan-list"),
        payload,
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not Loan.unscoped.filter(customer=customer).exists()


@pytest.mark.django_db
def test_loan_can_create_customer_and_daily_collection_queue(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner, tenant, employee_user, employee, _ = _make_employee_and_customer(
        two_tenants, rls_context
    )
    _enable_loans(owner, tenant, rls_context)
    today = timezone.localdate()

    response = client_for(owner, tenant).post(
        reverse("loan-list"),
        {
            "customer_details": {
                "full_name": "Cliente nuevo",
                "document_id": "CC-999",
                "location": {
                    "type": "Point",
                    "coordinates": [-74.08175, 4.60971],
                },
            },
            "collector": str(employee.pk),
            "principal": "1000.00",
            "interest_rate": "20.00",
            "installments": 2,
            "frequency": "daily",
            "start_date": (today - timedelta(days=2)).isoformat(),
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    loan_id = response.data["id"]
    assert response.data["customer_name"] == "Cliente nuevo"
    assert response.data["document_id"] == "CC-999"
    assert response.data["location"] == {
        "type": "Point",
        "coordinates": [-74.08175, 4.60971],
    }
    assert response.data["frequency"] == "daily"

    queue_response = client_for(employee_user, tenant).get(
        reverse("loan-collection-today")
    )
    assert queue_response.status_code == status.HTTP_200_OK
    due_installments = [
        row
        for row in queue_response.data
        if str(row["loan"]) == loan_id
    ]
    assert len(due_installments) == 2
    assert due_installments[0]["is_overdue"] is True
    assert due_installments[0]["status"] == "delinquent"
    assert due_installments[0]["pending_amount"] == Decimal("600.00")
    assert due_installments[1]["is_overdue"] is False
    assert due_installments[1]["status"] == "pending"


@pytest.mark.django_db
def test_payment_reversal_is_owner_only_and_creates_inverse_entry(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner, tenant, employee_user, employee, customer = _make_employee_and_customer(
        two_tenants, rls_context
    )
    _enable_loans(owner, tenant, rls_context)
    manager = User.objects.create(email="loan-manager@example.test")
    rls_context(owner, tenant)
    Membership.objects.create(
        user=manager,
        tenant=tenant,
        role=Membership.Role.MANAGER,
    )

    loan_response = _post_loan(client_for(owner, tenant), customer, employee)
    loan_id = loan_response.data["id"]
    payment_response = _post_payment(
        client_for(employee_user, tenant),
        loan_id,
        "100.00",
    )
    payment_id = payment_response.data["id"]

    manager_response = client_for(manager, tenant).post(
        reverse("loan-payment-reverse", args=[payment_id]),
        {},
        format="json",
    )
    assert manager_response.status_code == status.HTTP_403_FORBIDDEN

    owner_client = client_for(owner, tenant)
    reversal_response = owner_client.post(
        reverse("loan-payment-reverse", args=[payment_id]),
        {},
        format="json",
    )
    assert reversal_response.status_code == status.HTTP_201_CREATED
    assert reversal_response.data["direction"] == "reversal"
    assert str(reversal_response.data["reversal_of"]) == payment_id
    assert LoanPayment.unscoped.filter(
        pk=payment_id,
        direction="payment",
    ).exists()
    assert LoanPayment.unscoped.filter(
        reversal_of_id=payment_id,
        direction="reversal",
    ).count() == 1

    loan_detail = owner_client.get(reverse("loan-detail", args=[loan_id]))
    assert loan_detail.data["balance"] == "1200.00"
    repeated = owner_client.post(
        reverse("loan-payment-reverse", args=[payment_id]),
        {},
        format="json",
    )
    assert repeated.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_installments_are_hidden_from_other_tenant(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner_a, tenant_a, _, employee_a, customer_a = _make_employee_and_customer(
        two_tenants, rls_context, "tenant_a"
    )
    owner_b, tenant_b, _, _, _ = _make_employee_and_customer(
        two_tenants, rls_context, "tenant_b"
    )
    _enable_loans(owner_a, tenant_a, rls_context)
    _enable_loans(owner_b, tenant_b, rls_context)

    response = _post_loan(client_for(owner_a, tenant_a), customer_a, employee_a)
    installment_id = response.data["installment_schedule"][0]["id"]

    other_tenant_response = client_for(owner_b, tenant_b).get(
        reverse("loan-installment-detail", args=[installment_id])
    )
    assert other_tenant_response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_employee_only_sees_own_collection_routes(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner = two_tenants["user_a"]
    tenant_a = two_tenants["tenant_a"]
    rls_context(owner, tenant_a)
    enable_tool(tenant_a, Tool.objects.get(code="loans"))
    user_a = User.objects.create(email="collector-a@example.test")
    user_b = User.objects.create(email="collector-b@example.test")
    Membership.objects.create(user=user_a, tenant=tenant_a, role=Membership.Role.EMPLOYEE)
    Membership.objects.create(user=user_b, tenant=tenant_a, role=Membership.Role.EMPLOYEE)
    rls_context(user_a, tenant_a)
    employee_a = Employee.unscoped.create(
        tenant=tenant_a,
        user=user_a,
        full_name="Cobrador A",
    )
    rls_context(user_a, tenant_a)
    employee_b = Employee.unscoped.create(
        tenant=tenant_a,
        user=user_b,
        full_name="Cobrador B",
    )
    route_a = CollectionRoute.unscoped.create(
        tenant=tenant_a,
        collector=employee_a,
        name="Ruta A",
        date="2025-01-01",
    )
    CollectionRoute.unscoped.create(
        tenant=tenant_a,
        collector=employee_b,
        name="Ruta B",
        date="2025-01-01",
    )

    response = client_for(user_a, tenant_a).get(reverse("collection-route-list"))
    assert response.status_code == status.HTTP_200_OK
    assert [row["id"] for row in response.data] == [str(route_a.pk)]
