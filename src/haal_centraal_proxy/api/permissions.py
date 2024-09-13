import logging
import re
from dataclasses import dataclass, field
from functools import cached_property

from rest_framework import status
from rest_framework.permissions import BasePermission

from .exceptions import ProblemJsonException

audit_log = logging.getLogger("haal_centraal_proxy.audit")

GEMEENTE_AMSTERDAM_CODE = "0363"

ANY = object()  # sentinel


@dataclass
class ParameterPolicy:
    """A rule for which parameter values are allowed"""

    #: A specific scope for each value.
    scopes_for_values: dict[str | None, set[str]] = field(default_factory=dict)
    #: A default scope in case the value is missing in the :attr:`scopes_for_values`.
    default_scope: set[str] | None = None

    def get_needed_scopes(self, value) -> set[str]:
        """Return which scopes are required for a given parameter value."""
        try:
            return self.scopes_for_values[value]
        except KeyError:
            # Check if there is a "fieldvalue*" lookup
            for pattern, roles in self._roles_for_values_re:
                if pattern.match(value):
                    return roles

        if self.default_scope is None:
            raise ValueError(f"Value not handled: {value}")
        return self.default_scope

    @cached_property
    def _roles_for_values_re(self) -> list[tuple[re.Pattern, set[str]]]:
        return [
            (re.compile(re.escape(key).replace(r"\*", ".+")), roles)
            for key, roles in self.scopes_for_values.items()
            if key.endswith("*")
        ]


ALLOW_PARAMETER = ParameterPolicy(default_scope=set())
ALLOW_VALUE = set()  # no scopes
SCOPE_NATIONWIDE = {"BRP/buiten-gemeente"}

# A quick dictionary to automate permission-based access to certain filter parameters.
QUERY_PERMISSIONS: dict[str, ParameterPolicy] = {
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
    "geboortedatum": ALLOW_PARAMETER,
    "geslachtsnaam": ALLOW_PARAMETER,
    "geslacht": ALLOW_PARAMETER,
    "voorvoegsel": ALLOW_PARAMETER,
    "voornamen": ALLOW_PARAMETER,
    "straat": ALLOW_PARAMETER,
    "huisletter": ALLOW_PARAMETER,
    "huisnummer": ALLOW_PARAMETER,
    "huisnummertoevoeging": ALLOW_PARAMETER,
    "postcode": ALLOW_PARAMETER,
    "nummeraanduidingIdentificatie": ALLOW_PARAMETER,
    "adresseerbaarObjectIdentificatie": ALLOW_PARAMETER,
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
    "verblijfplaats": ParameterPolicy(default_scope={"BRP/in-buitenland"}),
    "burgerservicenummer": ParameterPolicy(default_scope={"BRP/zoek-bsn"}),
}


def transform_request(hc_request: dict, user_scopes: set):
    """Validate and adjust the JSON body contents POST request to Haal Centraal.
    This will add extra search parameters so enforce restrictions based on the user profile.
    """
    updated_request = hc_request.copy()

    # Inject extra defaults:
    if not user_scopes.issuperset(SCOPE_NATIONWIDE):
        # If the use may only search in Amsterdam, enforce that.
        # if a different value is set, it will be handled by the permission check later.
        updated_request.setdefault("gemeenteVanInschrijving", GEMEENTE_AMSTERDAM_CODE)

    # Check the requested fields
    _check_parameters(hc_request, user_scopes)

    return updated_request


def _check_parameters(hc_request, user_scopes: set[str]):
    """Check the parameters of the query"""
    request_type = hc_request.get("type")
    if not request_type:
        raise ProblemJsonException(
            title="Een of meerdere parameters zijn niet correct.",
            status=400,
            detail="De foutieve parameter(s) zijn: types.",
            code="paramsValidation",
        )

    # Check whether certain parameters are allowed:
    invalid_names = []
    all_needed_scopes = set()
    for field_name, values in hc_request.items():
        try:
            policy = QUERY_PERMISSIONS[field_name]
        except KeyError:
            invalid_names.append(field_name)
        else:
            needed_for_param = _check_parameter_values(policy, field_name, values, user_scopes)
            all_needed_scopes.update(needed_for_param)

    if invalid_names:
        raise ProblemJsonException(
            title="Een of meerdere parameters zijn niet correct.",
            detail=f"De foutieve parameter(s) zijn: {', '.join(invalid_names)}.",
            code="paramsValidation",
            status=status.HTTP_400_BAD_REQUEST,
        )

    audit_log.info(
        "Granted access for %(type)s, needed: %(needed)s, granted: %(granted)s",
        {
            "type": hc_request.get("type", "<unknown type>"),
            "granted": ",".join(sorted(user_scopes)),
            "needed": ",".join(sorted(all_needed_scopes)),
        },
        extra={
            "type": hc_request.get("type", "<unknown type>"),
            "granted": sorted(user_scopes),
            "needed": sorted(all_needed_scopes),
        },
    )


def _check_parameter_values(policy: ParameterPolicy, field_name, values, user_scopes):
    """Check whether the given parameter values are allowed."""
    is_multiple = isinstance(values, list)
    if not is_multiple:
        # Multiple values: will check each one
        values = [values]

    invalid_values = []
    denied_values = []
    all_needed_scopes = set()
    for value in values:
        try:
            needed_scopes = policy.get_needed_scopes(value)
        except ValueError:
            invalid_values.append(value)
        else:
            all_needed_scopes.update(needed_scopes)
            if not user_scopes.issuperset(needed_scopes):
                denied_values.append(value)

    if invalid_values:
        raise ProblemJsonException(
            title="Een of meerdere veldnamen zijn niet correct.",
            detail=(
                f"Het veld '{field_name}' ondersteund niet"
                f" de waarde(s): {', '.join(invalid_values)}."
            ),
            code="paramsValidation",
            status=status.HTTP_400_BAD_REQUEST,
        )

    if denied_values:
        audit_log.info(
            "Denied access to %s=%s, missing %s",
            field_name,
            ",".join(denied_values),
            ",".join(sorted(all_needed_scopes - user_scopes)),
            extra={
                "field": field_name,
                "values": denied_values,
                "granted": sorted(user_scopes),
                "needed": sorted(all_needed_scopes),
            },
        )
        raise ProblemJsonException(
            title="U bent niet geautoriseerd voor deze operatie.",
            detail=f"U bent niet geautoriseerd voor {field_name} = {', '.join(denied_values)}.",
            code="permissionDenied",
            status=status.HTTP_403_FORBIDDEN,
        )

    return all_needed_scopes


class IsUserScope(BasePermission):
    """Permission check, wrapped in a DRF permissions adapter"""

    def __init__(self, needed_scopes):
        self.needed_scopes = frozenset(needed_scopes)

    def has_permission(self, request, view):
        """Check whether the user has all required scopes"""
        # This calls into 'authorization_django middleware':
        return request.is_authorized_for(*self.needed_scopes)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
