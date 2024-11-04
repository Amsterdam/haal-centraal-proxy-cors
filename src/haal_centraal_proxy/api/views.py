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

ParameterPolicy = permissions.ParameterPolicy  # shortcut

GEMEENTE_AMSTERDAM_CODE = "0363"
ALLOW_VALUE = set()  # no scopes
SCOPE_NATIONWIDE = {"BRP/buiten-gemeente"}


class BaseProxyView(APIView):
    """View that proxies Haal Centraal BRP.

    This is a pass-through proxy, but with authorization and extra restrictions added.
    The subclasses implement the variations between Haal Centraal endpoints.
    """

    #: Define which additional scopes are needed
    client_class = HaalCentraalClient

    # Need to define for every sublass:
    endpoint_url: str = None
    needed_scopes: set = None
    parameter_ruleset: dict[str, ParameterPolicy] = None

    def setup(self, request, *args, **kwargs):
        """Configure the view before the request handling starts.
        This is the main Django view setup.
        """
        super().setup(request, *args, **kwargs)
        self._base_url = reverse(request.resolver_match.view_name)
        self.client = self.get_client()

    def get_client(self) -> HaalCentraalClient:
        """Provide the Haal Centraal client. This can be overwritten per view if needed."""
        return self.client_class(
            endpoint_url=self.endpoint_url,
            api_key=settings.HAAL_CENTRAAL_API_KEY,
            cert_file=settings.HAAL_CENTRAAL_CERT_FILE,
            key_file=settings.HAAL_CENTRAAL_KEY_FILE,
        )

    def get_permissions(self):
        """Collect the DRF permission checks.
        DRF checks these in the initial() method, and will block view access
        if these permissions are not satisfied.
        """
        if not self.needed_scopes:
            raise ImproperlyConfigured("needed_scopes is not set")

        return super().get_permissions() + [permissions.IsUserScope(self.needed_scopes)]

    def post(self, request: Request, *args, **kwargs):
        """Handle the incoming POST request.
        Basic checks (such as content-type validation) are already done by REST Framework.
        The API uses POST so the logs won't include personally identifiable information (PII).
        """
        # Check the request
        user_scopes = set(request.get_token_scopes)
        hc_request = request.data.copy()

        self.transform_request(hc_request, user_scopes)
        permissions.validate_parameters(self.parameter_ruleset, hc_request, user_scopes)

        # Proxy to Haal Centraal
        response = self.client.call(hc_request)

        # Rewrite the response to pagination still works.
        self.transform_response(response.data)

        # And return it.
        return HttpResponse(
            orjson.dumps(response.data),
            content_type=response.headers.get("Content-Type"),
        )

    def transform_request(self, hc_request: dict, user_scopes: set) -> None:
        """This method can be overwritten to provide extra request parameter handling per endpoint.
        It may perform in-place replacements of the request.
        """

    def transform_response(self, hc_response: dict | list) -> None:
        """Replace hrefs in _links sections by whatever fn returns for them.

        May modify data in-place.
        """
        self._rewrite_links(
            hc_response,
            rewrites=[
                (self.client.endpoint_url, self._base_url),
            ],
        )

    def _rewrite_links(
        self, data: dict | list, rewrites: list[tuple[str, str]], in_links: bool = False
    ):
        if isinstance(data, list):
            # Lists: go level deeper
            for child in data:
                self._rewrite_links(child, rewrites, in_links)
        elif isinstance(data, dict):
            # First or second level: dict
            if in_links and isinstance(href := data.get("href"), str):
                for find, replace in rewrites:
                    if href.startswith(find):
                        data["href"] = f"{replace}{href[len(find):]}"
                        break

            if links := data.get("_links"):
                # Go level deeper, can skip other keys
                self._rewrite_links(links, rewrites, in_links=True)
            else:
                # Dict: go level deeper
                for child in data.values():
                    self._rewrite_links(child, rewrites, in_links)


class BrpPersonenView(BaseProxyView):
    """View that proxies Haal Centraal BRP 'personen' (persons).

    See: https://brp-api.github.io/Haal-Centraal-BRP-bevragen/
    """

    endpoint_url = settings.HAAL_CENTRAAL_BRP_URL

    # Require extra scopes
    needed_scopes = {"BRP/RO"}

    # A quick dictionary to automate permission-based access to certain filter parameters.
    parameter_ruleset = {
        "type": ParameterPolicy(
            scopes_for_values={
                "RaadpleegMetBurgerservicenummer": {"BRP/zoek-bsn"},
                "ZoekMetGeslachtsnaamEnGeboortedatum": {"BRP/zoek-naam-geb"},
                "ZoekMetNaamEnGemeenteVanInschrijving": {"BRP/zoek-naam-gemeente"},
                "ZoekMetAdresseerbaarObjectIdentificatie": {"BRP/zoek-adres-id"},
                "ZoekMetNummeraanduidingIdentificatie": {"BRP/zoek-nummeraand-id"},
                "ZoekMetPostcodeEnHuisnummer": {"BRP/zoek-postcode"},
                "ZoekMetStraatHuisnummerEnGemeenteVanInschrijving": {"BRP/zoek-straat"},
            }
        ),
        "fields": ParameterPolicy(
            # - Fields/field groups that can be requested for a search:
            #   https://raw.githubusercontent.com/BRP-API/Haal-Centraal-BRP-bevragen/master/features/fields-filtered-PersoonBeperkt.csv
            # - Fields/field groups that can be requested a single person by their BSN:
            #   https://raw.githubusercontent.com/BRP-API/Haal-Centraal-BRP-bevragen/master/features/fields-filtered-Persoon.csv
            scopes_for_values={
                "aNummer": {"BRP/x"},
                "adressering": {"BRP/x"},
                "adressering.*": {"BRP/x"},
                "adresseringBinnenland": {"BRP/x"},
                "adresseringBinnenland.*": {"BRP/x"},
                "burgerservicenummer": {"BRP/x"},
                "datumEersteInschrijvingGBA": {"BRP/x"},
                "datumInschrijvingInGemeente": {"BRP/x"},
                "europeesKiesrecht": {"BRP/x"},
                "europeesKiesrecht.*": {"BRP/x"},
                "geboorte": {"BRP/x"},
                "geboorte.*": {"BRP/x"},
                "gemeenteVanInschrijving": {"BRP/x"},
                "geslacht": {"BRP/x"},
                "gezag": {"BRP/x"},
                "immigratie": {"BRP/x"},
                "immigratie.*": {"BRP/x"},
                "indicatieCurateleRegister": {"BRP/x"},
                "indicatieGezagMinderjarige": {"BRP/x"},
                "kinderen": {"BRP/x"},
                "kinderen.*": {"BRP/x"},
                "leeftijd": {"BRP/x"},
                "naam": ALLOW_VALUE,
                "naam.*": {"BRP/x"},
                "nationaliteiten": {"BRP/x"},
                "nationaliteiten.*": {"BRP/x"},
                "ouders": {"BRP/x"},
                "ouders.*": {"BRP/x"},
                "overlijden": {"BRP/x"},
                "overlijden.*": {"BRP/x"},
                "pad": {"BRP/x"},
                "partners": {"BRP/x"},
                "partners.*": {"BRP/x"},
                "uitsluitingKiesrecht": {"BRP/x"},
                "uitsluitingKiesrecht.*": {"BRP/x"},
                "verblijfplaats": {"BRP/adres-buitenland"},
                "verblijfplaats.*": {"BRP/adres-buitenland"},
                "verblijfplaatsBinnenland": {"BRP/adres"},
                "verblijfplaatsBinnenland.*": {"BRP/adres"},
                "verblijfstitel": {"BRP/x"},
                "verblijfstitel.*": {"BRP/x"},
            }
        ),
        # All possible search parameters are named here,
        # to avoid passing through a flag that allows more access.
        # See: https://brp-api.github.io/Haal-Centraal-BRP-bevragen/v2/redoc#tag/Personen/operation/Personen
        "geboortedatum": ParameterPolicy.allow_all,
        "geslachtsnaam": ParameterPolicy.allow_all,
        "geslacht": ParameterPolicy.allow_all,
        "voorvoegsel": ParameterPolicy.allow_all,
        "voornamen": ParameterPolicy.allow_all,
        "straat": ParameterPolicy.allow_all,
        "huisletter": ParameterPolicy.allow_all,
        "huisnummer": ParameterPolicy.allow_all,
        "huisnummertoevoeging": ParameterPolicy.allow_all,
        "postcode": ParameterPolicy.allow_all,
        "nummeraanduidingIdentificatie": ParameterPolicy.allow_all,
        "adresseerbaarObjectIdentificatie": ParameterPolicy.allow_all,
        "verblijfplaats": ParameterPolicy.for_all_values({"BRP/in-buitenland"}),
        "burgerservicenummer": ParameterPolicy.for_all_values({"BRP/zoek-bsn"}),
        "inclusiefOverledenPersonen": ParameterPolicy(
            scopes_for_values={
                "true": {"BRP/in-overl"},
                "false": ALLOW_VALUE,
            }
        ),
        "gemeenteVanInschrijving": ParameterPolicy(
            {GEMEENTE_AMSTERDAM_CODE: ALLOW_VALUE},  # ok to include ?gemeenteVanInschrijving=0363
            default_scope=SCOPE_NATIONWIDE,
        ),
    }

    def transform_request(self, hc_request: dict, user_scopes: set) -> None:
        """Extra rules before passing the request to Haal Centraal"""
        if not user_scopes.issuperset(SCOPE_NATIONWIDE):
            # If the use may only search in Amsterdam, enforce that.
            # if a different value is set, it will be handled by the permission check later.
            hc_request.setdefault("gemeenteVanInschrijving", GEMEENTE_AMSTERDAM_CODE)


class BrpVerblijfsplaatsHistorieView(BaseProxyView):
    """View that proxies Haal Centraal BRP Verblijfplaatshistorie of a person (residence history).

    See: https://brp-api.github.io/Haal-Centraal-BRP-historie-bevragen/
    """

    endpoint_url = settings.HAAL_CENTRAAL_BRP_VERBLIJFSPLAATS_HISTORIE_URL

    # Require extra scopes
    needed_scopes = {"BRP/RO"}

    # A quick dictionary to automate permission-based access to certain filter parameters.
    parameter_ruleset = {
        "type": ParameterPolicy(
            scopes_for_values={
                "RaadpleegMetPeildatum": {"BRP/zoek-historie"},
                "RaadpleegMetPeriode": {"BRP/zoek-historie"},
            }
        ),
        "burgerservicenummer": ParameterPolicy.allow_all,  # used for both request types.
        "peildatum": ParameterPolicy.allow_all,  # for RaadpleegMetPeildatum
        "datumTot": ParameterPolicy.allow_all,  # for RaadpleegMetPeriode
        "datumVan": ParameterPolicy.allow_all,  # for RaadpleegMetPeriode
    }


class BrpBewoningenView(BaseProxyView):
    """View to proxy Haal Centraal Bewoning (ocupancy).

    See: https://brp-api.github.io/Haal-Centraal-BRP-bewoning/
    """

    endpoint_url = settings.HAAL_CENTRAAL_BRP_BEWONINGEN_URL

    # Require extra scopes
    needed_scopes = {"BRP/RO"}

    # Validate the access to various parameters:
    parameter_ruleset = {
        "type": ParameterPolicy(
            scopes_for_values={
                "BewoningMetPeildatum": {"BRP/zoek-bewoningen"},
                "BewoningMetPeriode": {"BRP/zoek-bewoningen"},
            }
        ),
        "adresseerbaarObjectIdentificatie": ParameterPolicy.allow_all,  # used for both types.
        "peildatum": ParameterPolicy.allow_all,  # for BewoningMetPeildatum
        "datumTot": ParameterPolicy.allow_all,  # for BewoningMetPeriode
        "datumVan": ParameterPolicy.allow_all,  # for BewoningMetPeriode
    }


class ReisdocumentenView(BaseProxyView):
    """View to proxy Haal Centraal Reisdocumenten (travel documents).

    See: https://brp-api.github.io/Haal-Centraal-Reisdocumenten-bevragen/
    """

    endpoint_url = settings.HAAL_CENTRAAL_REISDOCUMENTEN_URL

    # Require extra scopes
    needed_scopes = {"BRP/RO"}

    # A quick dictionary to automate permission-based access to certain filter parameters.
    parameter_ruleset = {
        "type": ParameterPolicy(
            scopes_for_values={
                "RaadpleegMetReisdocumentnummer": {"BRP/zoek-doc"},
                "ZoekMetBurgerservicenummer": {"BRP/zoek-doc-bsn"},
            }
        ),
        "fields": ParameterPolicy(
            scopes_for_values={
                # Extracted from redoc and
                # https://github.com/BRP-API/Haal-Centraal-Reisdocumenten-bevragen/blob/master/src/Reisdocument.Validatie/Validators/ReisdocumentenQueryValidator.cs
                "reisdocumentnummer": {"BRP/x"},
                "soort": {"BRP/x"},
                "soort.*": {"BRP/x"},
                "houder": {"BRP/x"},
                "houder.*": {"BRP/x"},
                "datumEindeGeldigheid": {"BRP/x"},
                "datumEindeGeldigheid.*": {"BRP/x"},
                "inhoudingOfVermissing": {"BRP/x"},
                "inhoudingOfVermissing.*": {"BRP/x"},
            }
        ),
        "reisdocumentnummer": ParameterPolicy(
            # for RaadpleegMetReisdocumentnummer
            default_scope={"BRP/zoek-doc"}
        ),
        "burgerservicenummer": ParameterPolicy(
            # for ZoekMetBurgerservicenummer
            default_scope={"BRP/zoek-doc-bsn"}
        ),
    }
