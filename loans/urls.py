from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .cashflow import (
    CollectorCashSummaryView,
    CollectorDailyCashViewSet,
    CollectorExpenseViewSet,
    CustomerLoanSummaryView,
)
from .views import (
    CollectionRouteViewSet,
    LoanPaymentEventStreamView,
    LoanInstallmentViewSet,
    LoanPaymentViewSet,
    LoanViewSet,
    RouteStopViewSet,
)

router = DefaultRouter()
router.register(r"loans", LoanViewSet, basename="loan")
router.register(r"loan-payments", LoanPaymentViewSet, basename="loan-payment")
router.register(r"loan-installments", LoanInstallmentViewSet, basename="loan-installment")
router.register(r"collection-routes", CollectionRouteViewSet, basename="collection-route")
router.register(r"route-stops", RouteStopViewSet, basename="route-stop")
router.register(r"collector-daily-cash", CollectorDailyCashViewSet, basename="collector-daily-cash")
router.register(r"collector-expenses", CollectorExpenseViewSet, basename="collector-expense")

urlpatterns = [
    path("customer-loan-summary/", CustomerLoanSummaryView.as_view(), name="customer-loan-summary"),
    path("collector-cash-summary/", CollectorCashSummaryView.as_view(), name="collector-cash-summary"),
    path(
        "loan-payment-events/stream/",
        LoanPaymentEventStreamView.as_view(),
        name="loan-payment-events-stream",
    ),
    path("", include(router.urls)),
]
