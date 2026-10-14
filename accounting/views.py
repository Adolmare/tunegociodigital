from rest_framework import viewsets

from tenants.api import TenantViewSet

from .models import Account, Document, DocumentExtraction, FiscalPeriod, JournalEntry, JournalLine
from .serializers import (
    AccountSerializer,
    DocumentExtractionSerializer,
    DocumentSerializer,
    FiscalPeriodSerializer,
    JournalEntrySerializer,
    JournalLineSerializer,
)


class AccountViewSet(TenantViewSet):
    required_tool = "accounting"
    min_role = "employee"
    serializer_class = AccountSerializer

    def get_queryset(self):
        return Account.objects.all()


class FiscalPeriodViewSet(TenantViewSet):
    required_tool = "accounting"
    min_role = "employee"
    serializer_class = FiscalPeriodSerializer

    def get_queryset(self):
        return FiscalPeriod.objects.all()


class JournalEntryViewSet(TenantViewSet):
    required_tool = "accounting"
    min_role = "employee"
    serializer_class = JournalEntrySerializer

    def get_queryset(self):
        return JournalEntry.objects.all()


class JournalLineViewSet(TenantViewSet):
    required_tool = "accounting"
    min_role = "employee"
    serializer_class = JournalLineSerializer

    def get_queryset(self):
        return JournalLine.objects.all()


class DocumentViewSet(TenantViewSet):
    required_tool = "accounting"
    min_role = "employee"
    serializer_class = DocumentSerializer

    def get_queryset(self):
        return Document.objects.all()


class DocumentExtractionViewSet(TenantViewSet):
    required_tool = "accounting"
    min_role = "employee"
    serializer_class = DocumentExtractionSerializer

    def get_queryset(self):
        return DocumentExtraction.objects.all()
