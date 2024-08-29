from django.http import JsonResponse
from django.views import View


class RootView(View):
    """Root page of the server."""

    def get(self, request, *args, **kwargs):
        return JsonResponse({"status": "online"})


class ProxyAPIView(View):
    """Proxy to the Haalcentraal API service"""

    def get(self, request, *args, **kwargs):
        return JsonResponse({"status": "beta"})
