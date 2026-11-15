Pychronia Storygen
##################

Generates the PDF documents of a mystery party or role-playing game (character sheets, gamemaster manuals, inventories,
in-game documents, coherence summaries) from the restructuredtext/jinja2 templates of a project folder, described by
its "configuration.yaml" file. It can also prepare the emails which send these documents to participants (see
`Emails`_).

Along the way, it checks the coherence of the scenario: who knows which facts, which items are needed and provided,
which secret values (codes, names...) are used, through story tags placed in templates and documents.

.. contents::
   :local:
   :depth: 1


Installation
============

Python 3.11+ is required. From a checkout of this repository, or directly from git::

    pip install .
    pip install "pychronia-storygen @ git+https://github.com/ChrysalisTeam/pychronia-storygen.git"

LibreOffice must be installed to split game documents (ODT, ODP, ODG) into PDF files; its "soffice" executable is
searched in the PATH, then in its usual installation folders.

The command is then available as "pychronia_storygen" (or "python -m pychronia_storygen"); from a checkout,
"python main.py" works too, provided the dependencies are installed.


Usage
=====

::

    pychronia_storygen example_project
    pychronia_storygen my_project --variable lang=en --only "sheets/players/*"
    pychronia_storygen clean my_project --variable lang=en --dry-run

The first form is a shortcut for the default "build" command (``pychronia_storygen build <project_dir> ...``).
Generated RST files go into the "_build/" subfolder of the project, and PDF files into its "_output/" subfolder
(or "_build/<lang>/" and "_output/<lang>/", see `Translated projects`_).

Build command
-------------

``-V NAME=VALUE``, ``--variable NAME=VALUE`` (repeatable)
    Set a root variable, overriding the "variables" entry of the configuration (see `Root variables`_).
    The values "true" and "false" (whatever their case) are booleans, integers like "42" are numbers, anything
    else is a string (eg. ``--variable lang=no``, ``--variable "title=My = title"``).

``-o DIR``, ``--output-dir DIR``
    Write output files into this directory, used as-is instead of "_output/" (or "_output/<lang>/");
    RST files then go into its "_build/" subfolder.

``--only PATTERN``, ``--skip PATTERN`` (repeatable)
    Only generate the files of some items, see `Item selection`_.

``--list``
    Print the IDs of all items, marking with "[x]" those selected by ``--only``/``--skip``, without rendering or
    generating anything.

``--skip-document-splitting``
    Parse game documents for story tags, but don't split them into PDF files (LibreOffice is then not needed);
    missing email attachments are then only warned about (see `Emails`_).

``--no-pdf``
    Only write the RST files, without running rst2pdf, and imply ``--skip-document-splitting``: a quick check of
    templates and of scenario coherence, but rst2pdf errors (eg. missing images) are then not detected.

``-v``, ``--verbose``
    Print debug logs.

Exit codes: 0 on success; 1 if the coherence analysis found serious errors (after all files were generated), or if
the generation failed (template error, rst2pdf or LibreOffice error...); 2 for invalid command line arguments.

Item selection
--------------

Each generated item has an ID, which ``--only`` and ``--skip`` select with glob patterns (where "*" also matches
"/"); ``--skip`` wins over ``--only``, and a pattern matching no item is an error::

    sheets/<group>/.../<sheet>/full                 (or /cheat)
    documents/<bundle>
    inventories/<inventory>/per_section             (or /per_crate)
    emails/<batch>/<email>
    summaries/facts                                 (or /symbols, /items)

For example::

    pychronia_storygen my_project --list
    pychronia_storygen my_project --only "*alice*" --only "summaries/*"
    pychronia_storygen my_project --only "sheets/players/*" --skip "*/cheat" --no-pdf

Unselected sheets, documents and inventories are still rendered (but not written), so the coherence analysis
remains complete, and its errors still give exit code 1. Unselected emails are not rendered at all; a selected email
attaches the files present at that time, so ``--only "emails/*"`` prepares the emails from the PDFs of a former
full build.

Clean command
-------------

Removes the PDF files of the output folder, all the files of its "emails/" folder (see `Emails`_), and the RST
(".txt") files of the build folder, along with the subfolders they leave empty; any other file is kept. Options:

- ``--variable lang=..``: only clean this language (else all languages are cleaned; other variables are ignored);
- ``--output-dir DIR``: the output directory given to the build, if any;
- ``--dry-run``: only list the files which would be removed;
- ``-v``, ``--verbose``: print debug logs.

Translated projects
-------------------

Translated projects name their files "<name>_<lang>.<ext>" (eg. "intro_fr.rst" and "intro_en.rst"), and are built
one language at a time, selected by the "lang" root variable (a 2-letter lowercase code)::

    pychronia_storygen my_project --variable lang=en

With a "lang" variable:

- files are generated in "_build/<lang>/" and "_output/<lang>/";
- if "lang" is given on the command line, the "configuration_<lang>.yaml" file of the project is used if it exists
  (else "configuration.yaml");
- jinja2 macros are only loaded from templates which are language-neutral or in this language;
- the ``{lang}`` placeholder can be used in configuration paths (see `Paths with placeholders`_);
- rst2pdf gets a ``--language`` option (for hyphenation and smart quotes);
- templates also receive it as the "language" variable (``None`` if no language is set).


Project configuration
=====================

All top-level sections of "configuration.yaml" are optional, and unknown top-level entries are ignored
(eg. to hold YAML anchors)::

    "variables": {...}             # root variables
    "settings": {...}              # rst2pdf settings, see "RST to PDF settings"
    "template_dirs": [...]         # extra template directories
    "data_files": [...]            # YAML files loaded as variables
    "variables_hook": "..."        # Python function preparing the variables
    "sheet_generation": {...}      # full sheets and cheat sheets
    "document_generation": {...}   # splitting of ODT/ODP/ODG files
    "inventory_generation": {...}  # lists of game items
    "email_generation": {...}      # folders of emails to send by hand
    "summary_generation": {...}    # coherence summaries

See "example_project/" for a complete project.

Root variables
--------------

::

    "variables":
      "lang": "fr"                  # default language, if any
      "game_type": "standard"
      "decorations": true

The root variables are those of the top-level "variables" entry, overridden (or completed) by the ``--variable``
options of the command line; names are made of letters, digits and underscores. They are available:

- as jinja2 variables in all templates (``{{ game_type }}``, ``{% if decorations %}``);
- as ``{name}`` placeholders in the paths of the configuration (see below);
- as jinja2 variables in some string settings (see `RST to PDF settings`_).

Variables coming from elsewhere (data files, Python hook, "variables" of groups and sheets) are only available
in templates, NOT in path placeholders nor in settings. Templates also receive "project_dir" (absolute path of the
project folder, with forward slashes).

Paths with placeholders
-----------------------

Every path-valued entry (sheet parts, "document_source", "inventory_*" and "game_*" templates/destinations/data,
"template_dirs", "data_files", the "rst2pdf_conf_file" and "docutils_conf_file" settings) may contain ``{name}``
placeholders, replaced by the value of the root variable of that name (a boolean becomes "true"/"false")::

    "full_sheet": ["intro.{game_type}_{lang}.rst", "common_{lang}.rst"]

So one configuration serves all languages and variants of a project. A placeholder without matching root
variable is an error (eg. ``{lang}`` when no language is set). In YAML, quote values with braces inside flow lists.

Sheet parts may also use the ``{sheet_name}`` and ``{group_name}`` placeholders (the names of the current sheet
and of its innermost group), so that similar sheets can share their list of parts through YAML anchors, aliases
and ``<<`` merge keys::

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
and also scanned for jinja2 macros (with the same language filtering).

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

Entries are loaded in order (later ones override earlier ones), and have a lower priority than the root variables.
Every key of an overlay must exist in the base data.

Python hook
-----------

::

    "variables_hook": "my_hooks.prepare_variables"

The module is imported with the project folder and the "template_dirs" at the front of "sys.path". The function is
called once, after data files are loaded and before any generation, as
``prepare_variables(variables, *, language, jinja_env)``, where "variables" is the dict of all variables available
to templates at this point. It may mutate it or return a new dict, and can register jinja2 filters on ``jinja_env``.

Sheets
------

::

    "sheet_generation":
      "variables": {"intro_message": "Welcome!"}
      "sheets":
        "world_history":
          "full_sheet": "lore/world_history_full.rst"       # a template, or a list of templates
          "cheat_sheet": "lore/world_history_summary.rst"
      "groups":
        "players":
          "variables": {"is_player": true}
          "settings": {"rst2pdf_extra_args": "--stylesheets=dark"}
          "sheets":
            "alice":
              "variables": {"faction": "rebels"}
              "full_sheet": ["characters/intro.rst", "characters/alice.rst"]
          "groups": {...}                                    # nested subgroups

Groups nest freely. Each sheet may have a "full_sheet" and/or a "cheat_sheet", whose templates are rendered and
concatenated into "<group>/.../<sheet>_full_sheet.pdf" (and "_cheat_sheet.pdf"). "variables" and "settings" may be
set at every level (root, group, sheet), the innermost ones winning.

Besides all variables, sheet templates receive "sheet_name", "group_name" (innermost group, or ``None``),
"group_breadcrumb" (tuple of group names), "is_cheat_sheet", and "current_player_id": the character to whom the
story tags of the sheet are attributed. It defaults to the sheet name, but can be set in the "variables" of a group
(for all its sheets, unless they define their own) or of a sheet; an explicit ``null`` disables the registration
of facts, eg. for gamemaster documents.

Game documents
--------------

A "document_generation" bundle exports an OpenDocument file to PDF with LibreOffice, then splits it into one PDF
per document::

    "document_generation":
      "game_clues":
        "document_source": "documents/game_clues_{lang}.odt"
        "comment_sample":             # optional, a string or a per-language mapping
          "fr": "{% xfact"
          "en": "{% xfact"
        "document_splitting":
          - [recipes_of_potions, 2]                       # name, page count
          - [null, 1]                                     # null name: these pages are skipped
          - [useless_messages, 1, "Dear diary"]           # name, page count, text of the first page
          - [oracle_vision, 3, {fr: "Vision", en: "Vision of"}]  # per-language text ("lang" variable)
          - [map, 1, null]                                # null text: the first page must have no text

The source may be a text document (".odt"), a presentation (".odp", eg. a map drawn in Impress, one page per slide)
or a drawing (".odg"), or their flat XML variants (".fodt", ".fodp", ".fodg"); other formats are rejected.
The PDFs go into a folder named after the source file, without its language suffix
(eg. "_output/en/documents/game_clues/recipes_of_potions.pdf").

The text of the document, gamemaster comments included, is first rendered with jinja2 to register its story tags
(only the tags, and the "document_bundle_name" variable, are available there). "comment_sample" is a text which
it must contain, else the generation fails: it proves that the story tags written in comments were extracted.

The source file is then exported once (without its gamemaster comments), and each part is extracted with pypdf,
keeping only the images and fonts it uses. The generation fails if the exported file has comment annotations, if the
declared page counts don't add up to the number of pages, or if the first page of a part doesn't contain its text
snippet (compared ignoring case and whitespace). Entries with only a name and a page count are not checked on their
first page, and a language missing from a per-language mapping disables the check for that language. The PDFs of the
parts are removed before each export.

Inventories
-----------

::

    "inventory_generation":
      "main_inventory":
        "inventory_data": "inventories/game_inventory_data.yaml"
        "inventory_per_section_template": "inventories/game_inventory_per_section.rst"
        "inventory_per_section_destination": "inventories/main_inventory_per_section"
        "inventory_per_crate_template": "inventories/game_inventory_per_crate.rst"
        "inventory_per_crate_destination": "inventories/main_inventory_per_crate"

The data file maps section titles (eg. places) to lists of item titles::

    "@WEAPONS Armory IMPORTANT":
      - "Long sword"
      - "Potion of Fire {% item 'potion of fire' is provided %}"
    "Abandoned house":
      - "@POTIONS Old potion IMPORTANT"

A title starting with "@NAME " puts the item (or all items of the section) in the crate "NAME" (by default, items
of a section go into a crate named after it); the "IMPORTANT" marker flags the item (or all items of the section)
as important. Templates receive "inventory_name", and "items_per_section" (or "items_per_crate"): a mapping of
section (or crate) titles to lists of ``{"item_title": ..., "item_is_important": ...}``. Render item titles with
the "dangerous_render" filter (see `Templates`_) to process their story tags. Each destination is a path without
extension, relative to the build and output folders; "variables" and "settings" may be set per inventory.

Emails
------

Storygen doesn't send any email: it prepares one folder per email, with an RST file holding its recipients, subject
and body, and a copy of its attachments. You then create and send each email with your own mail client::

    "email_generation":
      "players":                                  # email batch
        "subject": "Mystery party - your sheet for {{ characters[email_name].name }}"
        "recipients": ["{{ characters[email_name].email }}"]
        "body_template": "emails/player_email_{lang}.rst"
        "attachments":
          - "{output_dir}/common/game_rules_full_sheet.pdf"
          - "{output_dir}/players/{email_name}_full_sheet.pdf"
        "emails":                                 # email names, with optional overrides
          "alice": {}
          "bob":
            "subject": "Mystery party - your sheet, and a secret map"
            "attachments": ["{output_dir}/documents/game_clues/map.pdf"]

Each email gets a folder "<output folder>/emails/<batch>/<email>/" (eg. "_output/en/emails/players/bob/"),
containing its attachments and a "<email>_email.rst" file::

    Mystery party - your sheet for Bob
    ==================================

    :To: bob@example.com
    :Subject: Mystery party - your sheet for Bob
    :Attachments: game_rules_full_sheet.pdf, bob_full_sheet.pdf, map.pdf

    ----

    <body rendered from the body template>

To send it, create a new email in your mail client, copy the recipients, the subject and the body (below the
horizontal line), and attach all the other files of the folder.

Entries of an email:

- "subject" and "recipients" are jinja2 strings (a single one, or a list for recipients), "body_template" is a
  template file; they may be set on the batch, or on an email, which then replaces the value of the batch. In
  translated projects, "subject" may be a per-language mapping (eg. ``{fr: "Votre fiche", en: "Your sheet"}``);
- "attachments" are paths, relative to the project folder; those of an email are added to those of its batch.
  Besides root variables, these paths and "body_template" may use the ``{email_name}``, ``{email_batch_name}`` and
  ``{output_dir}`` (the output folder of the build, eg. "_output/en") placeholders, to attach the PDF files
  generated by the same build (emails are prepared after sheets, documents and inventories);
- "variables" may be set per batch and per email; templates also receive "email_name" and "email_batch_name".

Beware, jinja2 renders a null value as "None": write ``{{ person.email or '' }}`` for data which may be null, so that
such recipients are seen as empty.

Checks:

- the folder of an email is removed and recreated at each build, so an attachment removed from the configuration is
  never left there;
- a missing attachment is an error, except with ``--no-pdf`` or ``--skip-document-splitting`` (generated PDFs may
  be missing then), where it is only skipped with a warning; two attachments with the same file name are an error;
- empty recipients are ignored (eg. placeholder data of participants), and an email left without recipient gets
  "(MISSING)" in its RST file, with a single warning per batch listing these emails; a recipient without "@", or
  receiving several emails of the same batch, gives a warning.

The RST file is written as-is (no typographic conversion), so that it can be copied into a mail client. Since these
folders usually contain personal data (names and emails of participants), keep the output folder out of version
control.

Summaries
---------

::

    "summary_generation":
      "game_facts_template": "summaries/game_facts_summary.rst"
      "game_facts_destination": "summaries/game_facts_summary"
      "game_symbols_template": "summaries/game_symbols_summary.rst"
      "game_symbols_destination": "summaries/game_symbols_summary"
      "game_items_template": "summaries/game_items_summary.rst"
      "game_items_destination": "summaries/game_items_summary"

Each summary is optional, and generated after all other items. Its template receives the matching registry (see
`Story tags and coherence analysis`_), "has_serious_errors", and "error_messages" (a list of
``(level, message)`` pairs, level being "ERROR" or "WARNING"):

- "facts_registry": ``{fact_name: {player_id: {"is_author", "is_viewer", "in_cheat_sheet", "in_normal_sheet"}}}``;
- "symbols_registry": ``{symbol_name: set_of_values}``;
- "items_registry": ``{item_name: set_of_statuses}``.

RST to PDF settings
-------------------

Hierarchical "settings" (project, group, sheet, inventory and summary levels):

- "rst2pdf_conf_file": rst2pdf configuration file (``--config`` option).
- "rst2pdf_extra_args": extra command line arguments given to rst2pdf, eg. "--stylesheets=simple_large,dark".
- "rst2pdf_smart_quotes": value of the rst2pdf ``--smart-quotes`` option (default 2); use 0 to let docutils handle quotes.
- "docutils_conf_file": docutils configuration file, given to rst2pdf through the ``DOCUTILSCONFIG`` environment variable.
- "unlink_unknown_rst_targets": if true, references like \`text\`_ to unknown targets are turned into plain text
  in the final RST file, before the PDF conversion.

The settings "rst2pdf_extra_args", "rst2pdf_conf_file" and "docutils_conf_file" may contain jinja2 markup,
rendered with the root variables only (an undefined variable is an error). For example, to let
``--variable decorations=false`` switch all documents to a printer-friendly style::

    "variables":
      "decorations": true
    "settings":
      "rst2pdf_extra_args": "--stylesheets={{ 'simple_large,dark_background' if decorations else 'simple_tight' }}"

PDF files are always compressed, and rst2pdf also gets the options ``--fit-background-mode=scale``,
``--first-page-on-right``, ``--break-side=any`` and ``--fit-literal-mode=shrink``, as well as a fixed version of its
"dotted_toc" extension. rst2pdf errors (missing images, unknown targets...) are detected in its output even when it
exits with code 0: the generation then fails, and no stale PDF is left behind.


Templates
=========

Templates are restructuredtext files rendered with jinja2, where an undefined variable is an error.

- **Macros**: the macros defined in any ".rst" or ".txt" template of the project folder and of the "template_dirs"
  (except "_build/" and "_output/") are available everywhere, as macro tags: ``<{ my_macro "value" key=other }/>``,
  or ``<{ my_macro }>body, available through caller()</{ my_macro }>``.
- **dangerous_render** filter: renders a string (eg. coming from a data file) as a jinja2 template, with the current
  variables, so that the story tags it contains are processed: ``{{ item.item_title|dangerous_render }}``.
- **Special markup**: ``[BR]`` becomes a vertical space, and ``[PAGEBREAK]`` a page break, in the final RST file.
- **Typography**: in French (or without "lang" variable), the space before "!", "?", ";" and before ":" (when
  followed by a space or a line break) becomes a non-breaking space; byte order marks (BOM) of templates are removed.


Story tags and coherence analysis
=================================

Story tags can be placed in templates, in data rendered with "dangerous_render", and in the text or gamemaster
comments of game documents. Each tag outputs its first argument; its "x" variant (``xfact``, ``xsymbol``,
``xitem``) outputs nothing. Names are case-insensitive.

``{% fact "alice_stole_the_key" %}``, ``{% fact "alice_stole_the_key" as author %}``
    The current character ("current_player_id") knows this fact, as a viewer (default) or as its author.

``{% symbol "1256" for "vault_code" %}``
    A secret value, which must be the same everywhere it is used.

``{% item "vault_key" is needed %}``, ``{% item "vault_key" is provided %}``
    A game item, needed by the scenario (eg. to solve an enigma) or provided (eg. in the gamemaster checklist).

After all items were rendered, the analysis reports these errors, which make the command exit with code 1:

- a fact is in the cheat sheet of a character, but not in their full sheet;
- a character is both author and viewer of a fact;
- a symbol has several different values (compared ignoring case and surrounding whitespace);
- an item is needed but never provided.

An item provided but never needed is only a warning. All errors are logged, and passed to the summary templates.


Development
===========

Install the dependencies with ``poetry install``, and run the tests with ``pytest``.
