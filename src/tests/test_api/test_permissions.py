import pytest
from haal_centraal_proxy.api.exceptions import ProblemJsonException
from haal_centraal_proxy.api.permissions import transform_request


class TestTransformRequest:
    """Test how the request is checked and transformed."""

    def test_add_gemeente_filter(self):
        """Prove that gemeente-filter is added."""
        hc_request = transform_request(
            {"type": "RaadpleegMetBurgerservicenummer"},
            user_scopes={"BRP/zoek-bsn"},
        )
        assert hc_request == {
            "type": "RaadpleegMetBurgerservicenummer",
            "gemeenteVanInschrijving": "0363",
        }

    def test_parameter_value_scope_check(self, caplog):
        """Prove that 'type' field is checked for authorization."""
        with pytest.raises(ProblemJsonException, match="ZoekMetPostcodeEnHuisnummer"):
            transform_request(
                {"type": "ZoekMetPostcodeEnHuisnummer"},
                user_scopes=set(),
            )
        assert (
            caplog.messages[0]
            == "Denied access to type=ZoekMetPostcodeEnHuisnummer, missing BRP/zoek-postcode"
        )

    def test_deny_other_gemeente(self, caplog):
        """Prove that search outside Amsterdam is denied."""
        with pytest.raises(ProblemJsonException, match="gemeenteVanInschrijving"):
            transform_request(
                {
                    "type": "RaadpleegMetBurgerservicenummer",
                    "gemeenteVanInschrijving": "0111",
                },
                user_scopes={"BRP/zoek-bsn"},
            )
        assert (
            caplog.messages[0]
            == "Denied access to gemeenteVanInschrijving=0111, missing BRP/buiten-gemeente"
        )

    def test_deny_field_access(self, caplog):
        """Prove that searching 'verblijfplaats' is not possible without extra permissions."""
        with pytest.raises(ProblemJsonException, match="verblijfplaats"):
            transform_request(
                {
                    "type": "ZoekMetPostcodeEnHuisnummer",
                    "fields": ["verblijfplaats"],
                },
                user_scopes={"BRP/zoek-postcode"},
            )
        assert (
            caplog.messages[0]
            == "Denied access to fields=verblijfplaats, missing BRP/adres-buitenland"
        )
