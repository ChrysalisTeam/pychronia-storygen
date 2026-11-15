"""
Smoke tests of example_project/, built from a copy so that its _build/ and _output/ folders are left untouched.
"""

import logging
import os
import shutil
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from pychronia_storygen import document_formats
from pychronia_storygen.cli import cli

EXAMPLE_PROJECT_DIR = Path(__file__).resolve().parent.parent / "example_project"

SHEET_AND_SUMMARY_PDFS = {
    "world_history_full_sheet.pdf",
    "world_history_cheat_sheet.pdf",
    "playable_characters/hero_full_sheet.pdf",
    "playable_characters/hero_cheat_sheet.pdf",
    "playable_characters/villains/enemy_full_sheet.pdf",
    "non_playable_characters/goblin_full_sheet.pdf",
    "inventories/main_inventory_per_section.pdf",
    "inventories/main_inventory_per_crate.pdf",
    "summaries/game_facts_summary.pdf",
    "summaries/game_symbols_summary.pdf",
    "summaries/game_items_summary.pdf",
}

DOCUMENT_PDFS = {
    "documents/clues_for_game/recipes_of_potions.pdf",
    "documents/clues_for_game/useless_secret_messages.pdf",
    "documents/valley_documents/valley_map.pdf",
    "documents/valley_documents/wanted_poster.pdf",
}


def _copy_example_project(target_dir):
    shutil.copytree(EXAMPLE_PROJECT_DIR, target_dir, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("_build", "_output", "__pycache__"))


@pytest.fixture
def example(storygen, monkeypatch):
    """The storygen fixture (with a fake rst2pdf), on a copy of the example project."""
    _copy_example_project(storygen.project_dir)
    monkeypatch.delitem(sys.modules, "storygen_hooks", raising=False)  # else the hook of another copy is reused
    return storygen


def _warnings(caplog):
    return [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]


def test_example_project_default_build(example, caplog):
    example.run("--skip-document-splitting")
    assert not _warnings(caplog)

    pdf_files = {call["pdf_file"].relative_to(Path("_output", "en")).as_posix()  # relative to the project dir
                 for call in example.pdf_calls}
    assert pdf_files == SHEET_AND_SUMMARY_PDFS
    assert {call["extra_args"] for call in example.pdf_calls} == {"--stylesheets=decorated"}
    assert {Path(call["conf_file"]).name for call in example.pdf_calls} == {"rst2pdf.conf"}

    hero_sheet = example.build_text("playable_characters/hero_full_sheet.txt", lang="en")
    assert "Sheet of Aldric the Brave" in hero_sheet  # data file
    assert "20 years after the final battle" in hero_sheet  # variables hook
    assert "Your faction is: Knights of Dawn!" in hero_sheet  # macro tag
    assert ".. admonition:: Secret" in hero_sheet  # block macro tag
    assert "You must never lie" in hero_sheet  # "is_villain" of the root variables
    assert "you may lie" in example.build_text("playable_characters/villains/enemy_full_sheet.txt", lang="en")

    goblin_sheet = example.build_text("non_playable_characters/goblin_full_sheet.txt", lang="en")
    assert "PEANUTS FOR EVERYONE!" in goblin_sheet  # filter of the variables hook
    assert "Goblin secretly loves peanuts" not in goblin_sheet  # xfact outputs nothing
    assert "Hint for easy games" not in goblin_sheet

    facts = example.build_text("summaries/game_facts_summary.txt", lang="en")
    assert "**Some errors were detected**" not in facts
    assert "enemy, goblin, **hero**\\*" in facts  # the hero is author, and has the fact in his cheat sheet
    assert "<master>" in facts  # fact of the comments of the ODT document
    assert "world is old and magic" not in facts  # "current_player_id" is null for the world history

    symbols = example.build_text("summaries/game_symbols_summary.txt", lang="en")
    assert "JOLYFELLOW, Jolyfellow" in symbols  # deterministic order, despite the case-insensitive comparison

    items = example.build_text("summaries/game_items_summary.txt", lang="en")
    for item_name in ("map of the valley", "potion of octopus tentacle", "potions of fire"):
        assert "   * - %s\n     - needed, provided" % item_name in items


def test_example_project_variant_build(example, caplog):
    example.run("-V", "lang=fr", "-V", "difficulty=easy", "-V", "decorations=false", "--skip-document-splitting")
    assert not _warnings(caplog)
    assert {call["extra_args"] for call in example.pdf_calls} == {""}

    world_history = example.build_text("world_history_full_sheet.txt", lang="fr")
    assert "Histoire du monde de Pangea" in world_history
    assert "tout !" in world_history  # French typography
    assert "Hint for easy games" in example.build_text("world_history_cheat_sheet.txt", lang="fr")
    assert "Hint for easy games" in example.build_text("non_playable_characters/goblin_full_sheet.txt", lang="fr")
    assert "Chevaliers de l'Aube" in example.build_text("playable_characters/hero_full_sheet.txt", lang="fr")  # overlay


def test_example_project_full_build_with_real_tools(tmp_path):
    try:
        document_formats._find_soffice()
    except RuntimeError:
        pytest.skip("LibreOffice is not installed")
    project_dir = tmp_path / "example_project"
    _copy_example_project(project_dir)

    old_cwd, old_path, old_hooks = os.getcwd(), list(sys.path), sys.modules.pop("storygen_hooks", None)
    try:
        result = CliRunner().invoke(cli, [str(project_dir)])
    finally:
        os.chdir(old_cwd)
        sys.path[:] = old_path
        sys.modules.pop("storygen_hooks", None)
        if old_hooks is not None:
            sys.modules["storygen_hooks"] = old_hooks
    assert result.exit_code == 0, (result.exception, result.output)

    output_dir = project_dir / "_output" / "en"
    pdf_files = {path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*.pdf")}
    assert pdf_files == SHEET_AND_SUMMARY_PDFS | DOCUMENT_PDFS
