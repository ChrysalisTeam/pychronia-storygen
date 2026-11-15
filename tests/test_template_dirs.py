import pytest


def _write_project(storygen, extra_config=""):
    storygen.write("configuration.yaml", """
        template_dirs: [common, "common_{lang}"]
        sheet_generation:
          sheets:
            alice:
              full_sheet: [main.rst, shared.rst]
        """ + extra_config)
    storygen.write("main.rst", "Main <{ shared_greeting name='Alice' }/>")
    storygen.write("common/shared.rst", "Shared from common")
    storygen.write("common/macros.rst", """
        {% macro shared_greeting(name) %}Hello {{ name }}{% endmacro %}
        """)
    storygen.write("common_en/macros_en.rst", "{% macro other_macro() %}X{% endmacro %}")


def test_template_dirs_templates_and_macros(storygen):
    _write_project(storygen)
    storygen.run("--variable", "lang=en")
    text = storygen.build_text("alice_full_sheet.txt", lang="en")
    assert "Hello Alice" in text
    assert "Shared from common" in text


def test_project_dir_has_priority(storygen):
    _write_project(storygen)
    storygen.write("shared.rst", "Shared from project")
    storygen.run("--variable", "lang=en")
    text = storygen.build_text("alice_full_sheet.txt", lang="en")
    assert "Shared from project" in text and "common" not in text


def test_missing_template_dir_is_an_error(storygen):
    storygen.write("configuration.yaml", "template_dirs: [nowhere]\n")
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0 and "nowhere" in result.output


def test_build_dir_excluded_only_in_project_dir(storygen):
    from pychronia_storygen.document_formats import load_jinja_environment
    storygen.write("_build/stale.rst", "{% macro stale() %}x{% endmacro %}")
    storygen.write("common/_build/kept.rst", "{% macro kept() %}x{% endmacro %}")
    import os
    old = os.getcwd()
    os.chdir(storygen.project_dir)
    try:
        env = load_jinja_environment([".", "common"], use_macro_tags=True, excluded_dirs=["_build"])
    finally:
        os.chdir(old)
    names = set(env.macros.templates)
    assert "kept" in names and "stale" not in names
