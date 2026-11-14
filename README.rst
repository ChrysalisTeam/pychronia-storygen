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

The command above is a shortcut for the default "build" command (``pychronia_storygen build my_project ...``).
The "clean" command removes the generated files: the PDF files of the output folder, and the RST (".txt")
files of the build folder, along with the subfolders they leave empty; any other file is kept.
It accepts the same ``--lang`` (to only clean one language, else all languages are cleaned) and ``--output-dir``
options as the build, and ``--dry-run`` lists the files without removing them::

    pychronia_storygen clean my_project --lang en --dry-run

From a checkout without installing the package, "python main.py" works as well, provided the dependencies are installed.

Configuration reference
=======================

All top-level sections of "configuration.yaml" are optional ("sheet_generation", "document_generation",
"inventory_generation", "summary_generation"), as are the "sheets" of a group, all keys of an inventory,
and each of the three summary templates (facts, symbols, items, each with its destination).
The coherence analysis runs at the end even if no summary template is configured.

Paths with ``{lang}``
---------------------

Every path-valued entry (sheet parts, "document_source", "inventory_*" and "game_*" templates/destinations/data,
"template_dirs", "data_files", the "rst2pdf_conf_file" and "docutils_conf_file" settings) may contain the ``{lang}``
placeholder, replaced by the ``--lang`` code, so that one configuration serves all languages.
Using it without ``--lang`` is an error. In YAML, quote values with braces inside flow lists: ``["intro_{lang}.rst"]``.

Extra template directories
--------------------------

::

    "template_dirs": ["../common/templates"]

Directories relative to the project folder, searched for templates AFTER the project folder (which has priority),
and also scanned for jinja2 macros (with the same language filtering). The "_build"/"_output" exclusions
only concern the project folder.

Data files
----------

::

    "data_files":
      - file: game_data_{lang}.yaml              # a mapping, merged at the root of the variables
      - variable: manual                         # or stored under this variable name
        file: manual_{lang}.yaml
      - file: [local.yaml, local.yaml.example]   # list of candidates: the first existing one is used, else error
      - file: dump.yaml
        overlay: dump_{lang}.yaml                # optional partial translation, deep-merged if the file exists

Entries are loaded in order (later ones override earlier ones). Root variables loaded from data files have
a lower priority than the "variables" of the configuration. Every key of an overlay must exist in the base data.

Python hook
-----------

::

    "variables_hook": "my_hooks.prepare_variables"

The module is imported with the project folder and the "template_dirs" at the front of "sys.path".
The function is called once, after data files are loaded and before any generation, as
``prepare_variables(variables, *, language, jinja_env)``, where "variables" is the dict of root variables
(data files, then configuration "variables", "project_dir" and "language"). It may mutate it, or return a new dict.
It can also register jinja2 filters on ``jinja_env``.

current_player_id
-----------------

The name of a sheet is only the DEFAULT value of its "current_player_id" variable. A "variables" entry
"current_player_id" at group level applies to the sheets of the group (and subgroups) unless a sheet defines its own;
an explicit ``null`` disables the registration of story tags for that sheet.

RST to PDF settings
-------------------

In French (or without --lang), the space before "!", "?", ";" and before ":" (when followed by a space or a line break) becomes a non-breaking space in the final RST file; byte order marks (BOM) of the templates are removed.

Hierarchical "settings" (project, group, sheet levels):

- "rst2pdf_smart_quotes": value of the rst2pdf ``--smart-quotes`` option (default 2); use 0 to let docutils handle quotes.
- "docutils_conf_file": docutils configuration file, given to rst2pdf through the ``DOCUTILSCONFIG`` environment variable.
- "unlink_unknown_rst_targets": if true, references like \`text\`_ to unknown targets are turned into plain text
  in the final RST file, before the PDF conversion.

rst2pdf errors (missing images, unknown targets...) are detected in its output even when it exits with code 0:
the generation fails, and no stale PDF is left behind.

ODT game documents
------------------

A "document_generation" bundle exports an ODT file (``document_source``, which may contain "{lang}") to PDF with
LibreOffice, then splits it into one PDF per document, in a folder named after the ODT file::

    document_generation:
      game_clues:
        document_source: "documents/game_clues_{lang}.odt"
        comment_sample:               # optional, a string or a per-language mapping
          fr: "{% xfact"
          en: "{% xfact"
        document_splitting:
          - [recipes_of_potions, 2]                       # name, page count
          - [null, 1]                                     # null name: these pages are skipped
          - [useless_messages, 1, "Dear diary"]           # name, page count, text of the first page
          - [oracle_vision, 3, {fr: "Vision", en: "Vision of"}]  # per-language text (see --lang)
          - [map, 1, null]                                # null text: the first page must have no text

The ODT file is exported once (without its gamemaster comments), then each part is extracted with pypdf, keeping
only the images and fonts it uses. The generation fails if the exported file has comment annotations, if the declared
page counts don't add up to the number of pages, or if the first page of a part doesn't contain its text snippet
(compared ignoring case and whitespace). Entries with only a name and a page count are not checked on their first page,
and a language missing from a per-language mapping disables the check for that language.
The PDFs of the parts are removed before each export.

"comment_sample" (optional) is a text which the ODT text, gamemaster comments included, must contain, else the
generation fails: it proves that the story tags written in comments were extracted.

Command line
------------

Storygen exits with a non-zero code if the coherence analysis finds serious errors, after all files were generated.
With ``--skip-document-splitting``, ODT game documents are still parsed for story tags, but not split into PDFs
(LibreOffice is then not needed).

Tests are run with "pytest" (a dev dependency).
