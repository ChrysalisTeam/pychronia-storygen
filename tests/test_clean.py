from pathlib import Path

from click.testing import CliRunner

from pychronia_storygen.cli import cli


def _touch(path: Path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _clean(*args):
    result = CliRunner().invoke(cli, ["clean"] + [str(arg) for arg in args])
    return result


def _make_generated_tree(project_dir: Path):
    files = dict(
        pdf_fr=_touch(project_dir / "_output/fr/players/alice_full_sheet.pdf"),
        pdf_en=_touch(project_dir / "_output/en/players/alice_full_sheet.pdf"),
        pdf_root=_touch(project_dir / "_output/summary.pdf"),
        rst_fr=_touch(project_dir / "_build/fr/players/alice_full_sheet.txt"),
        rst_en=_touch(project_dir / "_build/en/players/alice_full_sheet.txt"),
        kept_output=_touch(project_dir / "_output/fr/notes.odt"),
        kept_build=_touch(project_dir / "_build/fr/image.png"),
        kept_source_pdf=_touch(project_dir / "handouts/map.pdf"),
        kept_source_txt=_touch(project_dir / "sheet.txt"),
    )
    return files


def test_clean_removes_only_generated_files_of_all_languages(tmp_path):
    project_dir = tmp_path / "project"
    files = _make_generated_tree(project_dir)

    result = _clean(project_dir)
    assert result.exit_code == 0, result.output

    for name in ("pdf_fr", "pdf_en", "pdf_root", "rst_fr", "rst_en"):
        assert not files[name].exists(), name
    for name in ("kept_output", "kept_build", "kept_source_pdf", "kept_source_txt"):
        assert files[name].exists(), name

    # Folders left empty are removed, but not the root output/build folders, nor non-empty ones
    assert not (project_dir / "_output/en").exists()
    assert not (project_dir / "_output/fr/players").exists()
    assert (project_dir / "_output/fr").is_dir()
    assert (project_dir / "_build").is_dir()


def test_clean_with_language_only_removes_files_of_this_language(tmp_path):
    project_dir = tmp_path / "project"
    files = _make_generated_tree(project_dir)

    result = _clean(project_dir, "--lang", "en")
    assert result.exit_code == 0, result.output

    assert not files["pdf_en"].exists()
    assert not files["rst_en"].exists()
    for name in ("pdf_fr", "pdf_root", "rst_fr", "kept_output"):
        assert files[name].exists(), name


def test_clean_dry_run_removes_nothing(tmp_path):
    project_dir = tmp_path / "project"
    files = _make_generated_tree(project_dir)

    result = _clean(project_dir, "--dry-run")
    assert result.exit_code == 0, result.output
    assert all(path.exists() for path in files.values())


def test_clean_with_output_dir(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    output_dir = tmp_path / "elsewhere"
    generated_pdf = _touch(output_dir / "players/alice_full_sheet.pdf")
    generated_rst = _touch(output_dir / "_build/players/alice_full_sheet.txt")
    kept_txt = _touch(output_dir / "readme.txt")  # Not in the build folder
    default_output_pdf = _touch(project_dir / "_output/summary.pdf")

    result = _clean(project_dir, "-o", output_dir)
    assert result.exit_code == 0, result.output

    assert not generated_pdf.exists()
    assert not generated_rst.exists()
    assert kept_txt.exists()
    assert default_output_pdf.exists()


def test_clean_refuses_output_dir_containing_project(tmp_path):
    project_dir = tmp_path / "project"
    source_pdf = _touch(project_dir / "handouts/map.pdf")

    result = _clean(project_dir, "-o", tmp_path)
    assert result.exit_code != 0
    assert "must not contain the project directory" in result.output
    assert source_pdf.exists()


def test_clean_without_generated_folders(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    result = _clean(project_dir)
    assert result.exit_code == 0, result.output


def test_clean_rejects_bad_language(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    result = _clean(project_dir, "--lang", "french")
    assert result.exit_code != 0


def test_build_then_clean(storygen):
    storygen.write("configuration.yaml", """
        sheet_generation:
          sheets:
            alice:
              full_sheet: [intro.rst]
    """)
    storygen.write("intro.rst", "Hello Alice")
    storygen.run("--lang", "en")  # Default command, without "build"
    assert list((storygen.project_dir / "_output").rglob("*.pdf"))
    assert list((storygen.project_dir / "_build").rglob("*.txt"))

    storygen.run_command("build", "--lang", "en")  # Explicit command
    assert list((storygen.project_dir / "_output").rglob("*.pdf"))

    result = _clean(storygen.project_dir, "--lang", "en")
    assert result.exit_code == 0, result.output
    assert not list((storygen.project_dir / "_output").rglob("*.pdf"))
    assert not list((storygen.project_dir / "_build").rglob("*.txt"))
    assert (storygen.project_dir / "intro.rst").exists()
    assert (storygen.project_dir / "configuration.yaml").exists()
