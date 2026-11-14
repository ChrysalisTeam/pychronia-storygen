import pytest
import yaml

from pychronia_storygen.document_formats import load_yaml_file


def test_load_yaml_file_accepts_python_tuples(tmp_path):
    yaml_file = tmp_path / "data.yaml"
    yaml_file.write_text("key: !!python/tuple [a, 1]\nnested: {? !!python/tuple [x, y] : value}\n", encoding="utf8")
    data = load_yaml_file(yaml_file)
    assert data["key"] == ("a", 1)
    assert data["nested"] == {("x", "y"): "value"}


def test_load_yaml_file_still_refuses_arbitrary_python_objects(tmp_path):
    yaml_file = tmp_path / "data.yaml"
    yaml_file.write_text("key: !!python/object/apply:os.system [echo]\n", encoding="utf8")
    with pytest.raises(yaml.constructor.ConstructorError):
        load_yaml_file(yaml_file)
