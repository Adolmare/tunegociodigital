from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AccountViewSet,
    DocumentExtractionViewSet,
    DocumentViewSet,
    FiscalPeriodViewSet,
    JournalEntryViewSet,
    JournalLineViewSet,
)

router = DefaultRouter()
router.register(r"accounts", AccountViewSet, basename="accounting-account")
router.register(r"fiscal-periods", FiscalPeriodViewSet, basename="accounting-fiscal-period")
router.register(r"journal-entries", JournalEntryViewSet, basename="accounting-journal-entry")
router.register(r"journal-lines", JournalLineViewSet, basename="accounting-journal-line")
router.register(r"documents", DocumentViewSet, basename="accounting-document")
router.register(r"document-extractions", DocumentExtractionViewSet, basename="accounting-document-extraction")

urlpatterns = [
    path("", include(router.urls)),
]
