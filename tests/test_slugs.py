from moleculefinder_etl.transform.slugs import slugify, unique_slug


def test_slugify_basic():
    assert slugify("Caffeine") == "caffeine"
    assert slugify("β-Carotene") == "beta-carotene"
    assert slugify("N,N-Dimethyltryptamine") == "n-n-dimethyltryptamine"
    assert slugify("") == "molecule"


def test_unique_slug_collisions():
    taken: set[str] = set()
    assert unique_slug("Glucose", taken) == "glucose"
    assert unique_slug("Glucose", taken) == "glucose-2"
    assert unique_slug("Glucose", taken) == "glucose-3"
