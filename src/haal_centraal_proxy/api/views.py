import logging

import orjson
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.urls import reverse
from rest_framework.request import Request
from rest_framework.views import APIView

from . import permissions
from .client import HaalCentraalClient

logger = logging.getLogger(__name__)


class ScopeCheckAPIView(APIView):
    """Extended API view that performs extra permission checks by default."""

    #: Define which additional scopes are needed
    needed_scopes = None

    def get_permissions(self):
        """Collect the permission checks to perform in initial()"""
        if not self.needed_scopes:
            raise ImproperlyConfigured("needed_scopes is not set")

        return super().get_permissions() + [permissions.IsUserScope(self.needed_scopes)]


class HaalCentraalBRP(ScopeCheckAPIView):
    """View that proxies Haal Centraal BRP.

    This is a pass-through proxy, but with authorization and extra restrictions added.

    See:
    https://brp-api.github.io/Haal-Centraal-BRP-bevragen/
    """

    # Require extra scopes
    needed_scopes = {"BRP/RO"}

    def __init__(self):
        super().__init__()
        # Initialize the client once, so it has a global HTTP connection pool.
        self.client = HaalCentraalClient(
            endpoint_url=settings.HAAL_CENTRAAL_BRP_URL,
            api_key=settings.HAAL_CENTRAAL_API_KEY,
            cert_file=settings.HAAL_CENTRAAL_CERT_FILE,
            key_file=settings.HAAL_CENTRAAL_KEY_FILE,
        )
        self._base_url = reverse("brp-personen")

    def post(self, request: Request, *args, **kwargs):
        """Handle the incoming POST request.
        Basic checks (such as content-type validation) are already done by REST Framework.
        The BRP API uses POST so the logs won't iclude personally identifiable information (PII).
        """
        # Proxy to Haal Centraal
        hc_request = permissions.transform_request(request.data, set(request.get_token_scopes))
        response = self.client.call(hc_request)

        # Rewrite the response to pagination still works.
        _rewrite_links(
            response.data,
            rewrites=[
                (self.client.endpoint_url, self._base_url),
            ],
        )
        return HttpResponse(
            orjson.dumps(response.data),
            content_type=response.headers.get("Content-Type"),
        )


def _rewrite_links(
    data: dict | list, rewrites: list[tuple[str, str]], in_links: bool = False
) -> None:
    """Replace hrefs in _links sections by whatever fn returns for them.

    May modify data in-place.
    """
    if isinstance(data, list):
        # Lists: go level deeper
        for child in data:
            _rewrite_links(child, rewrites, in_links)
    elif isinstance(data, dict):
        # First or second level: dict
        if in_links and isinstance(href := data.get("href"), str):
            for find, replace in rewrites:
                if href.startswith(find):
                    data["href"] = f"{replace}{href[len(find):]}"
                    break

        if links := data.get("_links"):
            # Go level deeper, can skip other keys
            _rewrite_links(links, rewrites, in_links=True)
        else:
            # Dict: go level deeper
            for child in data.values():
                _rewrite_links(child, rewrites, in_links)
