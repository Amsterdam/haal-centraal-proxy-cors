import orjson
from django.urls import reverse

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


class TestViews:
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
