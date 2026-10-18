from django.views.generic import TemplateView

from customers.neighborhoods import NEIGHBORHOODS


class LoanPortalView(TemplateView):
    template_name = "loans/portal.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["neighborhoods"] = NEIGHBORHOODS
        return context
