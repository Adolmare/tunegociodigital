from django.db import models

from core.models import TenantOwnedModel


class Account(TenantOwnedModel):
    TYPE_CHOICES = [
        ("asset", "Activo"),
        ("liability", "Pasivo"),
        ("equity", "Patrimonio"),
        ("income", "Ingreso"),
        ("expense", "Gasto"),
    ]

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=150)
    account_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="asset")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_account_tenant_code")
        ]


class FiscalPeriod(TenantOwnedModel):
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    status = models.CharField(max_length=20, default="open")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "year", "month"], name="uniq_fiscal_period")
        ]


class JournalEntry(TenantOwnedModel):
    period = models.ForeignKey(FiscalPeriod, on_delete=models.PROTECT, related_name="entries")
    entry_date = models.DateField()
    description = models.CharField(max_length=200)
    reference_type = models.CharField(max_length=40, blank=True)
    reference_id = models.CharField(max_length=64, blank=True)


class JournalLine(TenantOwnedModel):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="lines")
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    description = models.CharField(max_length=200, blank=True)


class Document(TenantOwnedModel):
    KIND_CHOICES = [
        ("invoice", "Factura"),
        ("receipt", "Recibo"),
        ("statement", "Extracto"),
    ]

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="invoice")
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to="documents/%Y/%m/", blank=True, null=True)
    source = models.CharField(max_length=50, default="manual")


class DocumentExtraction(TenantOwnedModel):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="extractions")
    status = models.CharField(max_length=20, default="pending_review")
    raw_text = models.TextField(blank=True)
    extracted_payload = models.JSONField(default=dict, blank=True)


class EventInbox(TenantOwnedModel):
    event_name = models.CharField(max_length=120)
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)
    handled = models.BooleanField(default=False)
    idempotency_key = models.CharField(max_length=120, unique=True)
