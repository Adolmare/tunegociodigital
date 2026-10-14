from rest_framework import viewsets

from tenants.api import ActionMinRoleMixin, TenantViewSet

from .models import Account, Document, DocumentExtraction, FiscalPeriod, JournalEntry, JournalLine
from .serializers import (
    AccountSerializer,
    DocumentExtractionSerializer,
    DocumentSerializer,
    FiscalPeriodSerializer,
    JournalEntrySerializer,
    JournalLineSerializer,
)


class AccountViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "accounting"
    min_role = "manager"
    role_by_action = {"destroy": "owner"}
    serializer_class = AccountSerializer

    def get_queryset(self):
        return Account.objects.all()


class FiscalPeriodViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "accounting"
    min_role = "manager"
    role_by_action = {"destroy": "owner"}
    serializer_class = FiscalPeriodSerializer

    def get_queryset(self):
        return FiscalPeriod.objects.all()


class JournalEntryViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "accounting"
    min_role = "manager"
    role_by_action = {"destroy": "owner"}
    serializer_class = JournalEntrySerializer

    def get_queryset(self):
        return JournalEntry.objects.all()


class JournalLineViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "accounting"
    min_role = "manager"
    role_by_action = {"destroy": "owner"}
    serializer_class = JournalLineSerializer

    def get_queryset(self):
        return JournalLine.objects.all()


class DocumentViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "accounting"
    min_role = "manager"
    role_by_action = {"destroy": "owner"}
    serializer_class = DocumentSerializer

    def get_queryset(self):
        return Document.objects.all()


class DocumentExtractionViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "accounting"
    min_role = "manager"
    role_by_action = {"destroy": "owner"}
    serializer_class = DocumentExtractionSerializer

    def get_queryset(self):
        return DocumentExtraction.objects.all()
