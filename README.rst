Pychronia Storygen
##################

Generates the PDF documents of a mystery party (character sheets, inventories, game documents, coherence summaries)
from the restructuredtext/jinja2 templates of a project folder, described by its "configuration.yaml" file.

Install it with pip (Python 3.11+), from a checkout of this repository::

    pip install .

Then launch it with the "pychronia_storygen" command (or equivalently "python -m pychronia_storygen")::

    pychronia_storygen example_project

Generated RST files go into the "_build/" subfolder of the project, and PDF files into its "_output/" subfolder.
LibreOffice must be installed to split game documents (ODT, ODP or ODG) into separate PDF files.

The ``--variable NAME=VALUE`` option (or ``-V``, repeatable) sets a root variable of the project, overriding
the "variables" entry of its configuration (see "Root variables" below)::

    pychronia_storygen my_project --variable lang=en --variable decorations=false

Translated projects name their files "<name>_<language>.<ext>" (eg. "intro_fr.rst" and "intro_en.rst"),
and are built one language at a time, selected by the "lang" variable::

    pychronia_storygen my_project --variable lang=en

With a "lang" variable, jinja2 macros are only loaded from templates which are language-neutral or in this language,
and files are generated in "_build/<language>/" and "_output/<language>/". When it is given on the command line,
the "configuration_<language>.yaml" file of the project is used if it exists (else "configuration.yaml").

The ``--output-dir`` option forces the directory where output files are generated, used as-is
instead of the default "_output/" (or "_output/<language>/") subfolder of the project;
generated RST files then go into its "_build/" subfolder::

    pychronia_storygen my_project --variable lang=en --output-dir ../dist/my_project_en

The ``--only PATTERN`` and ``--skip PATTERN`` options (both repeatable) restrict the generated files to some items
of the project, selected by glob patterns (where "*" also matches "/") on their IDs; ``--skip`` wins over ``--only``.
``--list`` prints the IDs of all items, marking those selected, without rendering or generating anything::

    pychronia_storygen my_project --list
    pychronia_storygen my_project --only "sheets/players/*" --skip "*/cheat"
    pychronia_storygen my_project --only "*alice*" --only "summaries/*"

Item IDs are "sheets/<group>/.../<sheet>/full" (or "/cheat"), "documents/<bundle>",
"inventories/<inventory>/per_section" (or "/per_crate") and "summaries/facts" (or "/symbols", "/items").
Unselected sheets and game documents are still rendered and parsed (but not written nor converted to PDF), so the
coherence analysis remains complete, and its errors still give a non-zero exit code. A pattern which matches no item
is an error.

The ``--no-pdf`` option only writes the intermediate RST files, without running rst2pdf, and doesn't split game
documents (it implies ``--skip-document-splitting``): it is a quick check of templates and of scenario coherence,
which can be combined with ``--only``/``--skip``, but rst2pdf errors (e.g. missing images) are then not detected.

The command above is a shortcut for the default "build" command (``pychronia_storygen build my_project ...``).
The "clean" command removes the generated files: the PDF files of the output folder, and the RST (".txt")
files of the build folder, along with the subfolders they leave empty; any other file is kept.
It accepts the same ``--variable lang=..`` (to only clean one language, else all languages are cleaned; other
variables are ignored) and ``--output-dir`` options as the build, and ``--dry-run`` lists the files without
removing them::

    pychronia_storygen clean my_project --variable lang=en --dry-run

From a checkout without installing the package, "python main.py" works as well, provided the dependencies are installed.

Configuration reference
=======================

All top-level sections of "configuration.yaml" are optional ("sheet_generation", "document_generation",
"inventory_generation", "summary_generation"), as are the "sheets" of a group, all keys of an inventory,
and each of the three summary templates (facts, symbols, items, each with its destination).
The coherence analysis runs at the end even if no summary template is configured.

Root variables
--------------

::

    "variables":
      "lang": "fr"                  # default language, if any
      "game_type": "standard"
      "decorations": true

The root variables are those of the top-level "variables" entry of the configuration, overridden (or completed)
by the ``--variable NAME=VALUE`` options of the command line. Names are made of letters, digits and underscores.
On the command line, the values "true" and "false" (whatever their case) are booleans, integers like "42" are
numbers, and anything else is a string (eg. ``--variable lang=no``, ``--variable "title=My = title"``).

Root variables are exposed in three places:

- as jinja2 variables in all templates (``{{ game_type }}``, ``{% if decorations %}``), like the variables of
  data files, hooks, groups and sheets;
- as ``{name}`` placeholders in the paths of the configuration (see below);
- as jinja2 variables in some string settings (see "RST to PDF settings").

Variables coming from elsewhere (data files, Python hook, "variables" of groups and sheets) are only available
in templates, NOT in path placeholders nor in settings.

The "lang" variable is special: it must be a 2-letter lowercase code (eg. "fr"), and is the language of the
generated documents (see above). Templates and hooks also receive it as "language" (``None`` if no language is set).

Paths with ``{name}`` placeholders
----------------------------------

Every path-valued entry (sheet parts, "document_source", "inventory_*" and "game_*" templates/destinations/data,
"template_dirs", "data_files", the "rst2pdf_conf_file" and "docutils_conf_file" settings) may contain ``{name}``
placeholders, replaced by the value of the root variable of that name (a string, a number, or a boolean
rendered as "true"/"false")::

    "full_sheet": ["intro.{game_type}_{lang}.rst", "common_{lang}.rst"]

So one configuration serves all languages and variants of a project. A placeholder without matching root
variable is an error (eg. ``{lang}`` when no language is set).
In YAML, quote values with braces inside flow lists: ``["intro_{lang}.rst"]``.

Sheet parts may also use the ``{sheet_name}`` and ``{group_name}`` placeholders (the names of the current sheet
and of its innermost group), so that similar sheets can share their list of parts through YAML anchors, aliases
and ``<<`` merge keys (unknown top-level entries of the configuration are ignored, eg. to hold such anchors)::

    "sheet_templates":
      "player_sheet": &player_sheet
        "full_sheet": ["players/{sheet_name}/{sheet_name}_intro_{lang}.rst", "common_rules_{lang}.rst"]

    "sheet_generation":
      "groups":
        "players":
          "sheets":
            "alice": *player_sheet
            "bob":
              <<: *player_sheet
              "variables": {"has_secret_weapon": true}

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
(data files, then configuration "variables", ``--variable`` options, "project_dir" and "language"). It may mutate it, or return a new dict.
It can also register jinja2 filters on ``jinja_env``.

current_player_id
-----------------

The name of a sheet is only the DEFAULT value of its "current_player_id" variable. A "variables" entry
"current_player_id" at group level applies to the sheets of the group (and subgroups) unless a sheet defines its own;
an explicit ``null`` disables the registration of story tags for that sheet.

RST to PDF settings
-------------------

In French (or without "lang" variable), the space before "!", "?", ";" and before ":" (when followed by a space or a line break) becomes a non-breaking space in the final RST file; byte order marks (BOM) of the templates are removed.

Hierarchical "settings" (project, group, sheet levels):

- "rst2pdf_conf_file": rst2pdf configuration file (``--config`` option).
- "rst2pdf_extra_args": extra command line arguments given to rst2pdf, eg. "--stylesheets=simple_large,dark".
- "rst2pdf_smart_quotes": value of the rst2pdf ``--smart-quotes`` option (default 2); use 0 to let docutils handle quotes.
- "docutils_conf_file": docutils configuration file, given to rst2pdf through the ``DOCUTILSCONFIG`` environment variable.
- "unlink_unknown_rst_targets": if true, references like \`text\`_ to unknown targets are turned into plain text
  in the final RST file, before the PDF conversion.

The string settings "rst2pdf_extra_args", "rst2pdf_conf_file" and "docutils_conf_file" may contain jinja2 markup,
rendered with the root variables only (an undefined variable is an error). For example, to let
``--variable decorations=false`` switch all documents to a printer-friendly style::

    "variables":
      "decorations": true
    "settings":
      "rst2pdf_extra_args": "--stylesheets={{ 'simple_large,dark_background' if decorations else 'simple_tight' }}"

PDF files are always generated compressed (rst2pdf ``--compressed`` option, whatever the rst2pdf configuration file says).

rst2pdf errors (missing images, unknown targets...) are detected in its output even when it exits with code 0:
the generation fails, and no stale PDF is left behind.

Game documents (ODT, ODP, ODG)
------------------------------

A "document_generation" bundle exports an OpenDocument file (``document_source``, which may contain "{lang}") to PDF
with LibreOffice, then splits it into one PDF per document, in a folder named after the source file. The source may be
a text document (".odt"), a presentation (".odp", e.g. a map drawn in Impress, one page per slide) or a drawing
(".odg"), or their flat XML variants (".fodt", ".fodp", ".fodg"); other formats are rejected::

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
          - [oracle_vision, 3, {fr: "Vision", en: "Vision of"}]  # per-language text ("lang" variable)
          - [map, 1, null]                                # null text: the first page must have no text

The source file is exported once (without its gamemaster comments), then each part is extracted with pypdf, keeping
only the images and fonts it uses. The generation fails if the exported file has comment annotations, if the declared
page counts don't add up to the number of pages, or if the first page of a part doesn't contain its text snippet
(compared ignoring case and whitespace). Entries with only a name and a page count are not checked on their first page,
and a language missing from a per-language mapping disables the check for that language.
The PDFs of the parts are removed before each export.

"comment_sample" (optional) is a text which the document text, gamemaster comments included, must contain, else the
generation fails: it proves that the story tags written in comments were extracted.

Command line
------------

Storygen exits with a non-zero code if the coherence analysis finds serious errors, after all files were generated.
With ``--skip-document-splitting``, game documents are still parsed for story tags, but not split into PDFs
(LibreOffice is then not needed).

Tests are run with "pytest" (a dev dependency).
