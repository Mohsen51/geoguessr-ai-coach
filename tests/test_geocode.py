from geocoach.geocode import country_name, country_of


def test_country_of_known_points():
    assert country_of(48.8566, 2.3522) == "fr"
    assert country_of(-23.55, -46.63) == "br"


def test_country_name():
    assert country_name("fr") == "France"
    assert country_name("") == ""
