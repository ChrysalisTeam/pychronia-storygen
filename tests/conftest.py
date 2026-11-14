import os
import sys
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pychronia_storygen import document_formats
from pychronia_storygen.cli import cli


class StorygenRun:
    """Builds small throwaway projects in tmp_path, and runs the storygen CLI on them (rst2pdf is faked)."""

    def __init__(self, tmp_path, monkeypatch):
        self.project_dir = tmp_path / "project"
        self.project_dir.mkdir()
        self.monkeypatch = monkeypatch
        self.pdf_calls = []  # kwargs of each (fake) rst2pdf conversion

        def fake_convert(rst_file, pdf_file, **kwargs):
            self.pdf_calls.append(dict(rst_file=Path(rst_file), pdf_file=Path(pdf_file), **kwargs))
            document_formats._create_missing_parent_folders(pdf_file)
            Path(pdf_file).write_bytes(b"%PDF-fake")

        monkeypatch.setattr(document_formats, "convert_rst_file_to_pdf", fake_convert)

    def write(self, relpath, content):
        path = self.project_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf8")
        return path

    def run(self, *args, expect_ok=True):
        self.pdf_calls.clear()
        old_cwd = os.getcwd()
        old_path = list(sys.path)
        try:
            result = CliRunner().invoke(cli, [str(self.project_dir)] + list(args))
        finally:
            os.chdir(old_cwd)
            sys.path[:] = old_path
        if expect_ok and result.exception is not None:
            raise AssertionError("storygen failed: %r\n%s" % (result.exception, result.output)) from result.exception
        return result

    def build_file(self, relpath, lang=None):
        base = self.project_dir / "_build"
        return (base / lang / relpath if lang else base / relpath)

    def build_text(self, relpath, lang=None):
        return self.build_file(relpath, lang).read_text(encoding="utf8")


@pytest.fixture
def storygen(tmp_path, monkeypatch):
    return StorygenRun(tmp_path, monkeypatch)
