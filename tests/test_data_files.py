import pytest

from pychronia_storygen.data_files import deep_merge, deep_merge_localized_overlay


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


def test_missing_files_are_errors(storygen):
    storygen.write("configuration.yaml", _config("          - {file: dump.yaml, overlay: nothing.yaml}\n"))
    storygen.write("dump.yaml", "x: 1\n")
    storygen.write("sheet.rst", "{{ x }}")
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0 and "nothing.yaml" in result.output  # else a wrong path would go unnoticed

    storygen.write("configuration.yaml", _config("          - file: [a.yaml, b.yaml]\n"))
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0 and "a.yaml" in result.output


@pytest.mark.parametrize("overlay_content", ["", "{}\n"])
def test_empty_overlay_is_accepted(storygen, overlay_content):
    storygen.write("configuration.yaml", _config("          - {file: dump.yaml, overlay: dump_overlay.yaml}\n"))
    storygen.write("dump.yaml", "x: 1\n")
    storygen.write("dump_overlay.yaml", overlay_content)  # eg. for the language of the base data
    storygen.write("sheet.rst", "{{ x }}")
    storygen.run()
    assert "1" in storygen.build_text("alice_full_sheet.txt")


def test_non_mapping_overlay_is_an_error(storygen):
    storygen.write("configuration.yaml", _config("          - {file: dump.yaml, overlay: dump_overlay.yaml}\n"))
    storygen.write("dump.yaml", "x: 1\n")
    storygen.write("dump_overlay.yaml", "- 1\n")
    storygen.write("sheet.rst", "{{ x }}")
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0 and "dump_overlay.yaml" in result.output


def test_non_mapping_without_variable_is_an_error(storygen):
    storygen.write("configuration.yaml", _config("          - file: list.yaml\n"))
    storygen.write("list.yaml", "- 1\n- 2\n")
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0 and "list.yaml" in result.output


def test_overlay_with_unknown_key_is_rejected():
    with pytest.raises(KeyError):
        deep_merge_localized_overlay({"a": {"b": 1}}, {"a": {"c": 2}})


def test_deep_merge_of_data_files(storygen):
    storygen.write("configuration.yaml", _config("""
          - file: characters.yaml
            merge: deep
          - file: items.yaml
            merge: deep
          - file: overrides.yaml
            merge: deep
          - file: shallow.yaml
        """))
    storygen.write("characters.yaml", """
        props:
          bob: {name: Bob, tags: [a, b], age: 5}
          eve: {name: Eve}
        flat: {kept: 1}
        """)
    storygen.write("items.yaml", """
        props:
          bob: {weapon: sword}
        items: {ring: Ring}
        """)
    storygen.write("overrides.yaml", """
        props:
          bob: {tags: [c], age: null, extra: {x: 1}}
          zoe: {name: Zoe}
        """)
    storygen.write("shallow.yaml", "flat: {replaced: 2}\n")
    storygen.write("sheet.rst", "{{ props.bob.name }}|{{ props.bob.tags }}|{{ props.bob.age }}|{{ props.bob.weapon }}"
                                "|{{ props.bob.extra.x }}|{{ props.eve.name }}|{{ props.zoe.name }}|{{ items.ring }}"
                                "|{{ flat }}")
    storygen.run()
    assert "Bob|['c']|None|sword|1|Eve|Zoe|Ring|{'replaced': 2}" in storygen.build_text("alice_full_sheet.txt")


def test_invalid_merge_modes_are_errors(storygen):
    storygen.write("data.yaml", "x: 1\n")
    storygen.write("sheet.rst", "{{ x }}")

    storygen.write("configuration.yaml", _config("          - {file: data.yaml, merge: deep, variable: data}\n"))
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0 and "can't have both a 'variable' and a 'merge' mode" in result.output

    storygen.write("configuration.yaml", _config("          - {file: data.yaml, merge: wide}\n"))
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0 and "unknown 'merge' mode 'wide'" in result.output


def test_deep_merge_replaces_non_mapping_values():
    base = {"a": {"b": [1, 2], "c": {"d": 1}}, "e": {"f": 1}}
    merged = deep_merge(base, {"a": {"b": [3], "c": {"g": 2}}, "e": "scalar"})
    assert merged is base
    assert base == {"a": {"b": [3], "c": {"d": 1, "g": 2}}, "e": "scalar"}


def test_data_file_with_bom_is_loaded(storygen):
    storygen.write("configuration.yaml", _config("          - file: bom.yaml\n"))
    (storygen.project_dir / "bom.yaml").write_bytes("\ufeffname: Zoé\n".encode("utf8"))
    storygen.write("sheet.rst", "{{ name }}")
    storygen.run()
    assert "Zoé" in storygen.build_text("alice_full_sheet.txt")

