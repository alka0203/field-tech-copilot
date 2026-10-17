import pytest

from scripts.vision.normalize import normalize_brand, normalize_error_code, split_model


@pytest.mark.parametrize("raw,expected", [
    ("E1", "E1"), ("e1", "E1"), ("E 1", "E1"), ("F28", "F28"), ("U4", "U4"), ("L3", "L3"),
    ("AB1", "AB1"),          # already valid: never touched
    ("S1", "S1"),            # leading letter is the prefix, not a '5'
    ("E1O", "E10"), ("ES", "E5"), ("F2B", "F28"), ("EZ", "E2"), ("El", "E1"), ("4S", "45"),
])
def test_error_code_normalisation(raw, expected):
    assert normalize_error_code(raw)[0] == expected


def test_changes_are_logged():
    code, changes = normalize_error_code("E1O")
    assert code == "E10" and len(changes) == 1 and "'O'->'0'" in changes[0]
    assert normalize_error_code("E1")[1] == []


@pytest.mark.parametrize("raw", ["XYZ", "", "O", "HELLO1", "E1234567"])
def test_ambiguous_left_alone(raw):
    code, changes = normalize_error_code(raw)
    assert changes == [] and code == raw.upper()


def test_brand_and_model():
    assert normalize_brand("Mitsubishi Electric") == "mitsubishi"
    assert split_model("MXZ-4C36NA") == ("mitsubishi", "MXZ")
    assert split_model("40MAQ0361") == ("carrier", "40MAQ")
    assert split_model("nonsense") == ("", "")
