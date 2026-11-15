import pytest

from pychronia_storygen.data_files import deep_merge_localized_overlay


def _config(data_files, variables=""):
    return """
        data_files:
%s
        variables:
%s
        sheet_generation:
          sheets:
            alice:
              full_sheet: sheet.rst
        """ % (data_files, variables)


def test_data_files_forms(storygen):
    storygen.write("configuration.yaml", _config("""
          - file: base_{lang}.yaml
          - variable: manual
            file: manual.yaml
          - file: [local.yaml, local.yaml.example]
          - file: dump.yaml
            overlay: dump_{lang}.yaml
        """, """          title: from config
          shadowed: config"""))
    storygen.write("base_en.yaml", "title: from data\nshadowed: data\nroot_only: R\n")
    storygen.write("manual.yaml", "chapter: One\n")
    storygen.write("local.yaml.example", "phone: 123\n")
    storygen.write("dump.yaml", "chars:\n  bob:\n    name: Bobby\n    age: 5\n")
    storygen.write("dump_en.yaml", "chars:\n  bob:\n    name: Bob\n")
    storygen.write("sheet.rst", "{{ title }}|{{ shadowed }}|{{ root_only }}|{{ manual.chapter }}|{{ phone }}"
                                "|{{ chars.bob.name }}|{{ chars.bob.age }}")
    storygen.run("--variable", "lang=en")
    assert "from config|config|R|One|123|Bob|5" in storygen.build_text("alice_full_sheet.txt", lang="en")


def test_missing_overlay_is_tolerated_and_missing_file_is_not(storygen):
    storygen.write("configuration.yaml", _config("          - {file: dump.yaml, overlay: nothing.yaml}\n"))
    storygen.write("dump.yaml", "x: 1\n")
    storygen.write("sheet.rst", "{{ x }}")
    storygen.run()

    storygen.write("configuration.yaml", _config("          - file: [a.yaml, b.yaml]\n"))
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0 and "a.yaml" in result.output


def test_non_mapping_without_variable_is_an_error(storygen):
    storygen.write("configuration.yaml", _config("          - file: list.yaml\n"))
    storygen.write("list.yaml", "- 1\n- 2\n")
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0 and "list.yaml" in result.output


def test_overlay_with_unknown_key_is_rejected():
    with pytest.raises(KeyError):
        deep_merge_localized_overlay({"a": {"b": 1}}, {"a": {"c": 2}})
