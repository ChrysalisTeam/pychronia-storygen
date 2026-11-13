Pychronia Storygen
##################

Generates the PDF documents of a mystery party (character sheets, inventories, game documents, coherence summaries)
from the restructuredtext/jinja2 templates of a project folder, described by its "configuration.yaml" file::

    python main.py example_project

Generated RST files go into the "_build/" subfolder of the project, and PDF files into its "_output/" subfolder.
LibreOffice must be installed to split ODT game documents into separate PDF files.

Translated projects name their files "<name>_<language>.<ext>" (eg. "intro_fr.rst" and "intro_en.rst"),
and are built one language at a time::

    python main.py my_project --lang en

With ``--lang``, the "configuration_<language>.yaml" file of the project is used if it exists (else "configuration.yaml"),
jinja2 macros are only loaded from templates which are language-neutral or in this language,
and files are generated in "_build/<language>/" and "_output/<language>/".
