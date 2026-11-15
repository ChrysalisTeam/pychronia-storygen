import click
import pytest

from pychronia_storygen.cli import parse_cli_variables


CONFIG = """
    sheet_generation:
      sheets:
        alice:
          full_sheet: ["intro_{lang}.rst", common.rst]
    inventory_generation:
      main:
        inventory_data: inv_{lang}.yaml
        inventory_per_section_template: sec_{lang}.rst
        inventory_per_section_destination: inventories/sec_{lang}
    summary_generation:
      game_items_template: items_{lang}.rst
      game_items_destination: summaries/items_{lang}
    """


def _write_project(storygen, config=CONFIG):
    storygen.write("configuration.yaml", config)
    for lang in ("fr", "en"):
        storygen.write("intro_%s.rst" % lang, "Intro %s" % lang)
        storygen.write("inv_%s.yaml" % lang, "Section:\n  - Item %s\n" % lang)
        storygen.write("sec_%s.rst" % lang, "Sec {{ items_per_section }}")
        storygen.write("items_%s.rst" % lang, "Items %s" % lang)
    storygen.write("common.rst", "Common")


def test_lang_placeholder_expanded_everywhere(storygen):
    _write_project(storygen)
    storygen.run("--variable", "lang=en")
    assert "Intro en" in storygen.build_text("alice_full_sheet.txt", lang="en")
    assert "Item en" in storygen.build_text("inventories/sec_en.txt", lang="en")
    assert "Items en" in storygen.build_text("summaries/items_en.txt", lang="en")
    storygen.run("-V", "lang=fr")  # Short option
    assert "Intro fr" in storygen.build_text("alice_full_sheet.txt", lang="fr")


def test_lang_placeholder_without_language_is_an_error(storygen):
    _write_project(storygen)
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0
    assert "{lang}" in result.output and "--variable lang=<value>" in result.output


def test_lang_variable_of_configuration_file(storygen):
    _write_project(storygen, CONFIG + """
    variables:
      lang: en
    """)
    storygen.run()  # The language of the file drives placeholders, and output folders
    assert "Intro en" in storygen.build_text("alice_full_sheet.txt", lang="en")
    assert storygen.pdf_calls[0]["language"] == "en"
    storygen.run("--variable", "lang=fr")  # Overridden by the command line
    assert "Intro fr" in storygen.build_text("alice_full_sheet.txt", lang="fr")


def test_bad_language_is_rejected(storygen):
    _write_project(storygen)
    assert storygen.run("--variable", "lang=french", expect_ok=False).exit_code != 0
    assert storygen.run("--variable", "lang=12", expect_ok=False).exit_code != 0  # Parsed as a number


VARIANT_CONFIG = """
    variables:
      variant: basic
      title: Title from file
    sheet_generation:
      sheets:
        alice:
          full_sheet: "sheet.{variant}.rst"
    """


def _write_variant_project(storygen, config=VARIANT_CONFIG):
    storygen.write("configuration.yaml", config)
    storygen.write("sheet.basic.rst", "Basic sheet: {{ title }} ({{ variant }})")
    storygen.write("sheet.advanced.rst", "Advanced sheet: {{ title }} ({{ variant }})")


def test_cli_variables_override_those_of_configuration_file(storygen):
    _write_variant_project(storygen)
    storygen.run()
    assert "Basic sheet: Title from file (basic)" in storygen.build_text("alice_full_sheet.txt")
    storygen.run("--variable", "variant=advanced", "--variable", "title=Title = from CLI")
    assert "Advanced sheet: Title = from CLI (advanced)" in storygen.build_text("alice_full_sheet.txt")


def test_cli_variable_types_in_templates(storygen):
    storygen.write("configuration.yaml", """
        sheet_generation:
          sheets:
            alice:
              full_sheet: sheet.rst
        """)
    storygen.write("sheet.rst", "{% if flag %}ON{% else %}OFF{% endif %} {{ count + 1 }} {{ name }}")
    storygen.run("--variable", "flag=false", "--variable", "count=41", "--variable", "name=no")
    assert "OFF 42 no" in storygen.build_text("alice_full_sheet.txt")
    storygen.run("--variable", "flag=True", "--variable", "count=-2", "--variable", "name=")
    assert "ON -1" in storygen.build_text("alice_full_sheet.txt")


def test_parse_cli_variables():
    assert parse_cli_variables([]) == {}
    assert parse_cli_variables(["a=b", "flag=FALSE", "n=007", "url=x=y", "f=1.5", "a=c"]) == \
           dict(a="c", flag=False, n=7, url="x=y", f="1.5")
    for bad_pair in ("foo", "=bar", "my-name=bar", "a b=c"):
        with pytest.raises(click.BadParameter):
            parse_cli_variables([bad_pair])


def test_bad_variable_syntax_is_an_error(storygen):
    _write_variant_project(storygen)
    result = storygen.run("--variable", "variant", expect_ok=False)
    assert result.exit_code != 0
    assert "NAME=VALUE" in result.output


def test_unknown_placeholder_is_an_error(storygen):
    _write_variant_project(storygen, VARIANT_CONFIG.replace("{variant}", "{flavour}"))
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0
    assert "{flavour}" in result.output and "--variable flavour=<value>" in result.output


def test_non_scalar_placeholder_is_an_error(storygen):
    _write_variant_project(storygen, VARIANT_CONFIG.replace("variant: basic", "variant: [basic]"))
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0
    assert "{variant}" in result.output


def test_only_root_variables_are_usable_in_placeholders(storygen):
    # Variables of data files, hooks and sheets are jinja2 variables, but not path placeholders
    storygen.write("my_hooks.py", "def hook(variables, **kwargs):\n    variables['variant'] = 'basic'\n")
    storygen.write("data.yaml", "variant: basic\ntitle: Title from data\n")
    _write_variant_project(storygen, """
        data_files:
          - file: data.yaml
        variables_hook: my_hooks.hook
        sheet_generation:
          variables:
            variant: basic
          sheets:
            alice:
              full_sheet: "sheet.{variant}.rst"
        """)
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0
    assert "{variant}" in result.output
    storygen.run("--variable", "variant=advanced")  # Only used for the path: the hook overrides the jinja2 variable
    assert "Advanced sheet" in storygen.build_text("alice_full_sheet.txt")


JINJA_SETTINGS_CONFIG = """
    variables:
      decorations: true
      decorated_style: "large,dark"
    settings:
      rst2pdf_extra_args: "--stylesheets={{ decorated_style if decorations else 'plain' }}"
      rst2pdf_conf_file: "{% if decorations %}fancy{% else %}basic{% endif %}_{lang}.conf"
    sheet_generation:
      sheets:
        alice:
          full_sheet: sheet.rst
        bob:
          settings:
            rst2pdf_extra_args: "--stylesheets=fixed"
          full_sheet: sheet.rst
    """


def test_jinja_markup_in_settings(storygen):
    storygen.write("configuration.yaml", JINJA_SETTINGS_CONFIG)
    storygen.write("sheet.rst", "Sheet")
    storygen.run("--variable", "lang=en")
    calls = {call["pdf_file"].stem: call for call in storygen.pdf_calls}
    assert calls["alice_full_sheet"]["extra_args"] == "--stylesheets=large,dark"
    assert calls["alice_full_sheet"]["conf_file"] == "fancy_en.conf"
    assert calls["bob_full_sheet"]["extra_args"] == "--stylesheets=fixed"

    storygen.run("--variable", "lang=en", "--variable", "decorations=false")
    calls = {call["pdf_file"].stem: call for call in storygen.pdf_calls}
    assert calls["alice_full_sheet"]["extra_args"] == "--stylesheets=plain"
    assert calls["alice_full_sheet"]["conf_file"] == "basic_en.conf"


def test_jinja_markup_in_settings_with_unknown_variable_is_an_error(storygen):
    storygen.write("configuration.yaml", JINJA_SETTINGS_CONFIG.replace("decorations: true", "other: true"))
    storygen.write("sheet.rst", "Sheet")
    result = storygen.run("--variable", "lang=en", expect_ok=False)
    assert result.exit_code != 0
    assert "Can't render setting 'rst2pdf_" in result.output and "'decorations' is undefined" in result.output
