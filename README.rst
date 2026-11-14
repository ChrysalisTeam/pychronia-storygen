Pychronia Storygen
##################

Generates the PDF documents of a mystery party (character sheets, inventories, game documents, coherence summaries)
from the restructuredtext/jinja2 templates of a project folder, described by its "configuration.yaml" file.

Install it with pip (Python 3.11+), from a checkout of this repository::

    pip install .

Then launch it with the "pychronia_storygen" command (or equivalently "python -m pychronia_storygen")::

    pychronia_storygen example_project

Generated RST files go into the "_build/" subfolder of the project, and PDF files into its "_output/" subfolder.
LibreOffice must be installed to split ODT game documents into separate PDF files.

Translated projects name their files "<name>_<language>.<ext>" (eg. "intro_fr.rst" and "intro_en.rst"),
and are built one language at a time::

    pychronia_storygen my_project --lang en

With ``--lang``, the "configuration_<language>.yaml" file of the project is used if it exists (else "configuration.yaml"),
jinja2 macros are only loaded from templates which are language-neutral or in this language,
and files are generated in "_build/<language>/" and "_output/<language>/".

The ``--output-dir`` option forces the directory where output files are generated, used as-is
instead of the default "_output/" (or "_output/<language>/") subfolder of the project;
generated RST files then go into its "_build/" subfolder::

    pychronia_storygen my_project --lang en --output-dir ../dist/my_project_en

From a checkout without installing the package, "python main.py" works as well, provided the dependencies are installed.
