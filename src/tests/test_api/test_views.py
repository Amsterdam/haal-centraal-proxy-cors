import orjson
from django.urls import reverse
from haal_centraal_proxy.api import views

from tests.utils import build_jwt_token

RESPONSE_POSTCODE_HUISNUMMER = {
    "type": "ZoekMetPostcodeEnHuisnummer",
    "personen": [
        {
            "naam": {
                "voornamen": "Ronald Franciscus Maria",
                "geslachtsnaam": "Moes",
                "voorletters": "R.F.M.",
                "volledigeNaam": "Ronald Franciscus Maria Moes",
                "aanduidingNaamgebruik": {
                    "code": "E",
                    "omschrijving": "eigen geslachtsnaam",
                },
            }
        }
    ],
}


class TestHaalCentraalBRP:
    """Prove that the BRP view works as advertised."""

    def test_bsn_search_no_login(self, api_client, caplog):
        """Prove that accessing the view fails without a login token."""
        url = reverse("brp-personen")
        response = api_client.post(url)
        assert response.status_code == 403
        assert response.data == {
            "type": "https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.3",
            "code": "not_authenticated",
            "title": "Authentication credentials were not provided.",
            "detail": "",
            "status": 403,
            "instance": "/api/brp/personen",
        }

    def test_bsn_search(self, api_client, urllib3_mocker):
        """Prove that search is possible"""
        url = reverse("brp-personen")
        token = build_jwt_token(["BRP/RO", "BRP/zoek-postcode"])
        urllib3_mocker.add(
            "POST",
            "/haalcentraal/api/brp/personen",
            body=orjson.dumps(RESPONSE_POSTCODE_HUISNUMMER),
            content_type="application/json",
        )

        response = api_client.post(
            url,
            {
                "type": "ZoekMetPostcodeEnHuisnummer",
                "postcode": "1074VE",
                "huisnummer": 1,
                "fields": ["naam"],
            },
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 200
        assert response.json() == RESPONSE_POSTCODE_HUISNUMMER

    def test_invalid_api_key(self, api_client, urllib3_mocker):
        """Prove that incorrect API-key settings are handled gracefully."""
        url = reverse("brp-personen")
        token = build_jwt_token(["BRP/RO", "BRP/zoek-postcode"])
        urllib3_mocker.add(
            "POST",
            "/haalcentraal/api/brp/personen",
            body=orjson.dumps(
                {
                    "type": "https://datatracker.ietf.org/doc/html/rfc7235#section-3.1",
                    "title": "Niet correct geauthenticeerd.",
                    "status": 401,
                    "instance": "/haalcentraal/api/brp/personen",
                    "code": "authentication",
                }
            ),
            status=401,
            content_type="application/json",
        )

        response = api_client.post(
            url,
            {
                "type": "ZoekMetPostcodeEnHuisnummer",
                "postcode": "1074VE",
                "huisnummer": 1,
                "fields": ["naam"],
            },
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 403
        assert response.json() == {
            "type": "https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.3",
            "title": "You do not have permission to perform this action.",
            "status": 403,
            "detail": "401 from remote: Niet correct geauthenticeerd.",
            "code": "permission_denied",
            "instance": "/api/brp/personen",
        }

    def test_add_gemeente_filter(self):
        """Prove that gemeente-filter is added."""
        view = views.BrpPersonenView()
        hc_request = {"type": "RaadpleegMetBurgerservicenummer"}
        view.transform_request(hc_request, user_scopes={"BRP/zoek-bsn"})
        assert hc_request == {
            "type": "RaadpleegMetBurgerservicenummer",
            "gemeenteVanInschrijving": "0363",
        }
