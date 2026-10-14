from rest_framework import serializers

from tenants.api import TenantScopedRelatedField

from .models import Account, Document, DocumentExtraction, FiscalPeriod, JournalEntry, JournalLine


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")


class FiscalPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalPeriod
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")


class JournalEntrySerializer(serializers.ModelSerializer):
    period = TenantScopedRelatedField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["period"].queryset = FiscalPeriod.objects.all()

    class Meta:
        model = JournalEntry
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")


class JournalLineSerializer(serializers.ModelSerializer):
    entry = TenantScopedRelatedField()
    account = TenantScopedRelatedField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["entry"].queryset = JournalEntry.objects.all()
        self.fields["account"].queryset = Account.objects.all()

    class Meta:
        model = JournalLine
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")


class DocumentExtractionSerializer(serializers.ModelSerializer):
    document = TenantScopedRelatedField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document"].queryset = Document.objects.all()

    class Meta:
        model = DocumentExtraction
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")
