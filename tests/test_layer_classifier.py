"""Tests for src/layer_classifier.py. Run from the ArchLens folder: python -m pytest -v"""
import pytest

from src.layer_classifier import UNCLASSIFIED, LayerClassifier

CONFIG = {
    "layers": [
        {"name": "repo_api", "packages": ["app.repository"]},
        {"name": "repo_impl", "packages": ["app.repository.jdbc"]},
        {"name": "service", "packages": ["app.service"]},
        {"name": "special", "packages": []},
    ],
    "classes": {"app.service.LegacyDao": "repo_impl", "app.Main": "special"},
}


@pytest.fixture
def clf():
    return LayerClassifier(CONFIG)


def test_longest_package_prefix_wins(clf):
    assert clf.classify("app.repository.OwnerRepository").layer == "repo_api"
    c = clf.classify("app.repository.jdbc.JdbcOwnerRepository")
    assert (c.layer, c.matched_by, c.matched_value) == ("repo_impl", "package_prefix",
                                                        "app.repository.jdbc")


def test_explicit_class_mapping_beats_package(clf):
    c = clf.classify("app.service.LegacyDao")
    assert (c.layer, c.matched_by) == ("repo_impl", "class_mapping")
    assert clf.classify("app.Main").layer == "special"


def test_nested_class_follows_its_outer_class(clf):
    assert clf.classify("app.service.LegacyDao.Row").layer == "repo_impl"
    assert clf.classify("app.repository.jdbc.Jdbc.Mapper").layer == "repo_impl"


def test_prefix_must_match_whole_package_segment(clf):
    # "app.services" must not be treated as being inside "app.service"
    assert clf.classify("app.services.Foo").layer == UNCLASSIFIED
    assert clf.classify("other.Thing").matched_by == "none"


def test_conflicting_package_mapping_rejected():
    with pytest.raises(ValueError):
        LayerClassifier({"layers": [{"name": "a", "packages": ["x"]},
                                    {"name": "b", "packages": ["x"]}]})


def test_class_mapped_to_unknown_layer_rejected():
    with pytest.raises(ValueError):
        LayerClassifier({"layers": [{"name": "a", "packages": []}],
                         "classes": {"x.Y": "nope"}})
