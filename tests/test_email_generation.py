import logging
from pathlib import Path

import pytest

from pychronia_storygen.cli import cli


CONFIGURATION = """
    data_files:
      - file: data.yaml
    sheet_generation:
      groups:
        players:
          sheets:
            alice:
              full_sheet: sheet.rst
            bob:
              full_sheet: sheet.rst
    email_generation:
      players:
        subject: "Party - sheet of {{ characters[email_name].name }}"
        recipients: ["{{ characters[email_name].email }}", "gm@example.com"]
        body_template: "body_{lang}.rst"
        attachments:
          - "{output_dir}/players/{email_name}_full_sheet.pdf"
          - "handouts/rules.pdf"
        emails:
          alice: {}
          bob:
            subject: "Special subject for {{ email_name }} of {{ email_batch_name }}"
            attachments: ["handouts/map.pdf"]
    """

DATA = """
    characters:
      alice: {name: "Alice", email: "alice@example.com"}
      bob: {name: "Bob", email: ""}
    """


def _project(storygen, configuration=CONFIGURATION, data=DATA):
    storygen.write("configuration.yaml", configuration)
    storygen.write("data.yaml", data)
    storygen.write("sheet.rst", "Sheet of {{ sheet_name }}")
    storygen.write("body_en.rst", "Hello {{ characters[email_name].name }},\n\nHere is your sheet.\n")
    (storygen.project_dir / "handouts").mkdir()
    (storygen.project_dir / "handouts/rules.pdf").write_bytes(b"%PDF-rules")
    (storygen.project_dir / "handouts/map.pdf").write_bytes(b"%PDF-map")


def _email_dir(storygen, email_name, lang="en"):
    return storygen.project_dir / "_output" / lang / "emails" / "players" / email_name


def test_email_folders_contain_rst_file_and_attachments(storygen, caplog):
    _project(storygen)
    with caplog.at_level(logging.WARNING):
        storygen.run("--variable", "lang=en")

    alice_dir = _email_dir(storygen, "alice")
    assert sorted(p.name for p in alice_dir.iterdir()) == ["alice_email.rst", "alice_full_sheet.pdf", "rules.pdf"]
    assert alice_dir.joinpath("rules.pdf").read_bytes() == b"%PDF-rules"
    rst = alice_dir.joinpath("alice_email.rst").read_text(encoding="utf8")
    assert rst == (
        "Party - sheet of Alice\n"
        "======================\n"
        "\n"
        ":To: alice@example.com, gm@example.com\n"
        ":Subject: Party - sheet of Alice\n"
        ":Attachments: alice_full_sheet.pdf, rules.pdf\n"
        "\n"
        "----\n"
        "\n"
        "Hello Alice,\n"
        "\n"
        "Here is your sheet.\n")

    # Per-email subject replaces the batch one, per-email attachments are appended to the batch ones
    bob_dir = _email_dir(storygen, "bob")
    assert sorted(p.name for p in bob_dir.iterdir()) == ["bob_email.rst", "bob_full_sheet.pdf", "map.pdf", "rules.pdf"]
    bob_rst = bob_dir.joinpath("bob_email.rst").read_text(encoding="utf8")
    assert ":Subject: Special subject for bob of players\n" in bob_rst
    assert ":To: gm@example.com\n" in bob_rst  # Blank recipient dropped
    assert ":Attachments: bob_full_sheet.pdf, rules.pdf, map.pdf\n" in bob_rst

    # The gamemaster gets both emails, which is only worth a warning
    assert "'gm@example.com' receives several emails of batch 'players': alice, bob" in caplog.text


def test_emails_without_recipients_are_reported_in_a_single_warning(storygen, caplog):
    _project(storygen, configuration=CONFIGURATION.replace(', "gm@example.com"', ""),
             data=DATA.replace("alice@example.com", ""))
    with caplog.at_level(logging.WARNING):
        storygen.run("--variable", "lang=en")

    warnings = [record.getMessage() for record in caplog.records if "without any recipient" in record.getMessage()]
    assert warnings == ["Emails of batch 'players' without any recipient (marked (MISSING) in their RST file): alice, bob"]
    rst = _email_dir(storygen, "alice").joinpath("alice_email.rst").read_text(encoding="utf8")
    assert ":To: (MISSING)\n" in rst


def test_email_folder_is_recreated_from_scratch(storygen):
    _project(storygen)
    storygen.run("--variable", "lang=en")
    stale_file = _email_dir(storygen, "bob").joinpath("stale_attachment.pdf")
    stale_file.write_bytes(b"%PDF-stale")

    storygen.run("--variable", "lang=en")
    assert not stale_file.exists()
    assert _email_dir(storygen, "bob").joinpath("map.pdf").exists()


def test_missing_attachment_is_an_error_unless_pdf_generation_is_disabled(storygen, caplog):
    _project(storygen)
    (storygen.project_dir / "handouts/map.pdf").unlink()

    # Without PDF generation, the PDFs of sheets are missing too, missing attachments are skipped with a warning
    with caplog.at_level(logging.WARNING):
        storygen.run("--variable", "lang=en", "--no-pdf")
    assert sorted(p.name for p in _email_dir(storygen, "bob").iterdir()) == ["bob_email.rst", "rules.pdf"]
    assert "Skipping missing attachment" in caplog.text

    result = storygen.run("--variable", "lang=en", expect_ok=False)
    assert result.exit_code != 0
    assert "handouts/map.pdf' of email 'players/bob' does not exist" in result.output.replace("\\", "/")

    # Same tolerance when game documents are not split
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        storygen.run("--variable", "lang=en", "--skip-document-splitting")
    assert "Skipping missing attachment 'handouts" in caplog.text


def test_attachments_with_same_name_are_an_error(storygen):
    _project(storygen, configuration=CONFIGURATION.replace('["handouts/map.pdf"]', '["other/rules.pdf"]'))
    storygen.write("other/rules.pdf", "%PDF-other")

    result = storygen.run("--variable", "lang=en", expect_ok=False)
    assert result.exit_code != 0
    assert "Email 'players/bob' has several attachments named 'rules.pdf'" in result.output


def test_subject_can_be_a_per_language_mapping(storygen):
    _project(storygen, configuration=CONFIGURATION.replace(
        'subject: "Party - sheet of {{ characters[email_name].name }}"',
        'subject: {fr: "Fiche de {{ email_name }}", en: "Sheet of {{ email_name }}"}'))
    storygen.write("body_fr.rst", "Bonjour")
    storygen.run("--variable", "lang=fr")
    storygen.run("--variable", "lang=en")

    fr_rst = _email_dir(storygen, "alice", lang="fr").joinpath("alice_email.rst").read_text(encoding="utf8")
    assert ":Subject: Fiche de alice\n" in fr_rst
    en_rst = _email_dir(storygen, "alice").joinpath("alice_email.rst").read_text(encoding="utf8")
    assert ":Subject: Sheet of alice\n" in en_rst

    result = storygen.run("--variable", "lang=de", expect_ok=False)
    assert "Email 'players/alice' has no subject for language 'de'" in result.output


def test_missing_entry_is_an_error(storygen):
    _project(storygen, configuration=CONFIGURATION.replace('body_template: "body_{lang}.rst"', ""))

    result = storygen.run("--variable", "lang=en", expect_ok=False)
    assert result.exit_code != 0
    assert "Email 'players/alice' has no 'body_template' entry" in result.output


def test_emails_can_be_selected_and_listed(storygen):
    _project(storygen)
    storygen.run("--variable", "lang=en")  # Provides the PDFs to attach
    alice_rst = _email_dir(storygen, "alice").joinpath("alice_email.rst")
    alice_rst.unlink()
    bob_rst = _email_dir(storygen, "bob").joinpath("bob_email.rst")
    bob_rst.unlink()

    storygen.run("--variable", "lang=en", "--only", "emails/*/bob")
    assert storygen.pdf_calls == []  # Sheets were not regenerated
    assert bob_rst.exists()
    assert not alice_rst.exists()

    result = storygen.run("--variable", "lang=en", "--list", "--skip", "emails/players/alice")
    assert "[ ] emails/players/alice" in result.output
    assert "[x] emails/players/bob" in result.output


def test_clean_removes_email_folders(storygen):
    _project(storygen)
    storygen.run("--variable", "lang=en")
    extra_file = _email_dir(storygen, "alice").joinpath("notes.txt")
    extra_file.write_text("generated anyway")

    storygen.run_command("clean")
    assert not (storygen.project_dir / "_output/en/emails").exists()
    assert (storygen.project_dir / "handouts/map.pdf").exists()  # Source attachments are kept
