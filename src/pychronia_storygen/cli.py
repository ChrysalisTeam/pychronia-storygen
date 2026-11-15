# -*- coding: utf-8 -*-
"""A pythonic like make file """
import dataclasses
import fnmatch
import logging
import os
import re
import shutil
from collections import ChainMap
from pathlib import Path
from pprint import pprint

import click
import subprocess
import glob
from dataclasses import dataclass
from types import MappingProxyType


from pychronia_storygen.document_formats import load_yaml_file, load_jinja_environment, load_rst_file, \
    render_with_jinja_and_fact_tags, convert_rst_content_to_pdf, render_with_jinja, generate_rst_and_pdf_files, \
    render_with_jinja_and_convert_to_pdf, extract_text_from_odt_file, split_odt_file_into_separate_documents, \
    check_comment_sample, resolve_comment_sample, get_pdf_export_filter, \
    get_filename_language, expand_path_placeholders, LANGUAGE_VARIABLE, StorygenConfigError
from pychronia_storygen.data_files import load_data_files, run_variables_hook
from pychronia_storygen.inventory import analyze_and_normalize_game_items
from pychronia_storygen.story_tags import CURRENT_PLAYER_VARNAME, IS_CHEAT_SHEET_VARNAME, detect_game_item_errors, \
    detect_game_symbol_errors, detect_game_fact_errors


def ___frozenmap(map, **kwargs):  # FIXME REMOVE
    """Creates an immutable dict, used for hierarchical context variables"""
    new_dict = map.copy()
    new_dict.update(kwargs)
    return MappingProxyType(new_dict)


@dataclass
class ItemSelection:
    """
    Selection of the items (sheets, document bundles, inventory sheets, summaries) whose files are generated,
    by glob patterns (see fnmatch, "*" also matches "/") on their IDs, like "sheets/players/alice/cheat".

    Unselected sheets, documents and inventories are still rendered/parsed, so that the coherence analysis sees all story tags.
    In listing mode, nothing is rendered nor generated, items IDs are just collected.
    """
    only_patterns: tuple = ()  # If not empty, only the items matching one of them are selected
    skip_patterns: tuple = ()  # Items matching one of them are unselected, even if they match only_patterns
    listing: bool = False
    items: list = dataclasses.field(default_factory=list)  # (item_id, is_selected) of all items met, in processing order
    matched_patterns: set = dataclasses.field(default_factory=set)

    def is_selected(self, item_id):
        """Register this item, and return whether its files must be generated (never, in listing mode)."""
        only_matches = {pattern for pattern in self.only_patterns if fnmatch.fnmatchcase(item_id, pattern)}
        skip_matches = {pattern for pattern in self.skip_patterns if fnmatch.fnmatchcase(item_id, pattern)}
        self.matched_patterns.update(only_matches, skip_matches)
        selected = (not self.only_patterns or bool(only_matches)) and not skip_matches
        self.items.append((item_id, selected))
        if not selected and not self.listing:
            logging.debug("Skipping the generation of unselected item '%s'", item_id)
        return selected and not self.listing

    def get_unmatched_patterns(self):
        return [pattern for pattern in self.only_patterns + self.skip_patterns if pattern not in self.matched_patterns]


@dataclass
class StorygenSettings:
    """Settings for the whole processing pipeline"""
    project_root_dir: str
    build_root_dir: str
    output_root_dir: str
    jinja_env: object
    dynamic_variables: ChainMap
    dynamic_settings: ChainMap
    language: str = None  # Language of the generated documents (eg. "fr"), if the project is translated ("lang" variable)
    path_variables: object = dataclasses.field(default_factory=dict)  # Root variables, usable in "{name}" placeholders of configuration paths
    selection: ItemSelection = dataclasses.field(default_factory=ItemSelection)  # Shared by derived settings
    generate_pdf: bool = True  # If False, only the intermediate RST files are written, rst2pdf is not run

    def derive(self, new_config_level, default_variables=None, **extra_dynamic_variables):
        """
        Return a new StorygenSettings with nested variables/storygen_settings loaded from new_config_level fields

        extra_dynamic_variables are forced values, which override any other variable.
        default_variables only apply if the variable is not defined at the current level or in any ancestor level
        (even as None), eg. the sheet name is only the default "current_player_id" of a sheet.
        """
        _new_variables = new_config_level.get("variables") or {}
        dynamic_variables = self.dynamic_variables.new_child(_new_variables, **extra_dynamic_variables)
        _missing_defaults = {key: value for key, value in (default_variables or {}).items()
                             if key not in dynamic_variables}
        if _missing_defaults:
            dynamic_variables = ChainMap(*dynamic_variables.maps, _missing_defaults)  # Lowest priority
        _new_settings = new_config_level.get("settings") or {}
        dynamic_settings = self.dynamic_settings.new_child(_new_settings)
        return dataclasses.replace(self, dynamic_variables=dynamic_variables, dynamic_settings=dynamic_settings)


def _recursively_generate_group_sheets(data_tree: dict, group_breadcrumb: tuple,
                                       storygen_settings: StorygenSettings):

    group_storygen_settings = storygen_settings.derive(data_tree)
    del storygen_settings  # Safety
    ###group_variables = frozenmap(data_tree.get("variables", {}))
    group_sheets = data_tree.get("sheets") or {}
    group_name = group_breadcrumb[-1] if group_breadcrumb else None  # LAST group name of the chain

    #group_cumulated_variables = frozenmap(variables, **group_variables)  # IMPORTANT

    relative_folders = Path().joinpath(*group_breadcrumb)

    for sheet_name, sheet_config in group_sheets.items():

        #_player_variables = frozenmap(sheet_config.get("variables", {}))
        player_storygen_settings = group_storygen_settings.derive(
            sheet_config,
            default_variables={CURRENT_PLAYER_VARNAME: sheet_name}  # Overridable, even by None, at group/sheet level
        )
        #player_cumulated_variables = frozenmap(group_cumulated_variables,
        #                                       )  # FIXME??
        logging.info("Processing sheet for group '%s' and sheet '%s'"  % (group_name or "<empty>", sheet_name))
        ##print(">>> ", character_name, character_sheet_files)

        for (sheet_parts, is_cheat_sheet) in [
            (sheet_config.get("full_sheet", None), False),
            (sheet_config.get("cheat_sheet", None), True),
        ]:

            if not sheet_parts:
                continue

            selection = player_storygen_settings.selection
            item_id = "/".join(("sheets",) + group_breadcrumb + (sheet_name, "cheat" if is_cheat_sheet else "full"))
            is_selected = selection.is_selected(item_id)
            if selection.listing:
                continue

            _sheet_name_tpl = "%s_cheat_sheet" if is_cheat_sheet else "%s_full_sheet"
            relative_filepath_base = relative_folders.joinpath(_sheet_name_tpl % sheet_name)

            jinja_context = dict(
                group_breadcrumb=group_breadcrumb,
                group_name=group_name,
                sheet_name=sheet_name,
                **{IS_CHEAT_SHEET_VARNAME: is_cheat_sheet},
                **player_storygen_settings.dynamic_variables
            )

            # Be tolerant if a single string was entered
            sheet_parts = (sheet_parts,) if isinstance(sheet_parts, str) else sheet_parts
            # Sheet parts may also use the "{sheet_name}" and "{group_name}" placeholders, eg. to share (with YAML
            # anchors) the list of parts of similar sheets, like "players/{sheet_name}/{sheet_name}_intro_{lang}.rst"
            sheet_path_variables = dict(player_storygen_settings.path_variables, sheet_name=sheet_name,
                                        **({"group_name": group_name} if group_name else {}))
            sheet_parts = [expand_path_placeholders(part, sheet_path_variables) for part in sheet_parts]

            full_rst_content = ""
            for sheet_part in sheet_parts:
                logging.debug("Rendering template file '%s' with jinja2", sheet_part)
                rst_content = render_with_jinja_and_fact_tags(
                    filename=sheet_part,
                    jinja_env=player_storygen_settings.jinja_env,
                    jinja_context=jinja_context)
                full_rst_content += "\n\n" + rst_content

            if not is_selected:
                continue  # Rendered anyway, for the story tags of the coherence analysis

            logging.debug("Writing RST and PDF files with filename base '%s'", relative_filepath_base)
            generate_rst_and_pdf_files(
                rst_content=full_rst_content, relative_path=relative_filepath_base, storygen_settings=player_storygen_settings)

        # convert_rst_content_to_pdf(filepath_base=filepath_base,
        #                            rst_content=full_rst_content,
        #                            conf_file="rst2pdf.conf",  # FIXME put a registry
        #                            extra_args=rst2pdf_extra_args)

    sub_data_tree = data_tree.get("groups", None)

    if sub_data_tree:
        for group_name, group_data_tree in sub_data_tree.items():
            _recursively_generate_group_sheets(group_data_tree,
                                               group_breadcrumb=group_breadcrumb + (group_name,),
                                               storygen_settings=group_storygen_settings)



def _generate_inventory_files(inventory_name, inventory_config, storygen_settings: StorygenSettings):

    logging.info("Analysing data for game inventory '%s'" % inventory_name)

    storygen_settings = storygen_settings.derive(inventory_config, inventory_name=inventory_name)

    def _get_path(key):
        return expand_path_placeholders(inventory_config.get(key), storygen_settings.path_variables)

    inventory_data_path = _get_path("inventory_data")
    if not inventory_data_path:
        logging.info("No 'inventory_data' for game inventory '%s', skipping it" % inventory_name)
        return

    inventory_per_section_template_name = _get_path("inventory_per_section_template")
    inventory_per_section_destination = _get_path("inventory_per_section_destination")

    inventory_per_crate_template_name = _get_path("inventory_per_crate_template")
    inventory_per_crate_destination = _get_path("inventory_per_crate_destination")

    selection = storygen_settings.selection
    inventory_sheets = [  # (kind, template, destination, name of the items variable)
        ("per_section", inventory_per_section_template_name, inventory_per_section_destination, "items_per_section"),
        ("per_crate", inventory_per_crate_template_name, inventory_per_crate_destination, "items_per_crate"),
    ]
    inventory_sheets = [(kind, template_name, destination, items_varname,
                         selection.is_selected("inventories/%s/%s" % (inventory_name, kind)))
                        for (kind, template_name, destination, items_varname) in inventory_sheets
                        if template_name and destination]
    if selection.listing or not inventory_sheets:
        return

    inventory_data = load_yaml_file(Path(inventory_data_path))
    game_items_per_section, game_items_per_crate = analyze_and_normalize_game_items(
        inventory_data, important_marker="IMPORTANT")
    items_variables = dict(items_per_section=game_items_per_section, items_per_crate=game_items_per_crate)

    for kind, template_name, destination, items_varname, is_selected in inventory_sheets:
        logging.info("Processing %s sheet for game inventory '%s'" % (kind.replace("_", "-"), inventory_name))
        jinja_context = {items_varname: items_variables[items_varname], **storygen_settings.dynamic_variables}
        # Rendered anyway, since story tags of inventory data are registered via the "dangerous_render" filter
        rst_content = render_with_jinja(filename=template_name, jinja_env=storygen_settings.jinja_env,
                                        jinja_context=jinja_context)
        if is_selected:
            generate_rst_and_pdf_files(rst_content=rst_content, relative_path=Path(destination),
                                       storygen_settings=storygen_settings)

def _generate_document_files(document_bundle_name, document_config, storygen_settings: StorygenSettings,
                             skip_document_splitting=False):
    selection = storygen_settings.selection
    is_selected = selection.is_selected("documents/%s" % document_bundle_name)
    if selection.listing:
        return

    logging.info("Processing generation of game document bundle '%s'" % document_bundle_name)
    document_source = expand_path_placeholders(document_config["document_source"], storygen_settings.path_variables)
    get_pdf_export_filter(document_source)  # ODT, ODP or ODG only
    document_text = extract_text_from_odt_file(document_source)
    # Else the story tags of gamemaster comments would be silently missed
    check_comment_sample(document_text, resolve_comment_sample(document_config.get("comment_sample"), storygen_settings.language),
                         document_source)

    # No need for rendered output, we just fill game-tags registries
    render_with_jinja_and_fact_tags(
        content=document_text,
        jinja_env=storygen_settings.jinja_env,
        jinja_context=dict(document_bundle_name=document_bundle_name))

    if not is_selected:
        return  # Parsed anyway, for the story tags of the coherence analysis
    if skip_document_splitting:
        logging.info("Skipping the splitting of document bundle '%s' into PDF files" % document_bundle_name)
        return

    # We then split the PDF into parts
    output_relative_dir, ext = os.path.splitext(document_source)  # The basename becomes the name of the target FOLDER
    if get_filename_language(document_source):
        output_relative_dir = output_relative_dir[:-3]  # "game_clues_fr.odt" -> folder "game_clues" (already under _output/<lang>)
    output_dir = storygen_settings.output_root_dir.joinpath(output_relative_dir)
    document_splitting = document_config.get("document_splitting") or []
    split_odt_file_into_separate_documents(
        document_source,
        splits_config=document_splitting,
        output_dir=output_dir,
        language=storygen_settings.language)


# Subfolder of the output folder where email folders are prepared (it only contains generated files)
EMAILS_FOLDER = "emails"
MISSING_RECIPIENT_MARKER = "(MISSING)"


def _format_email_rst(subject, recipients, attachment_names, body):
    """Return the content of the RST file of an email, to be copied by hand into a mail client."""
    title = subject or "(no subject)"
    lines = [
        title,
        "=" * len(title),
        "",
        ":To: %s" % (", ".join(recipients) or MISSING_RECIPIENT_MARKER),
        ":Subject: %s" % subject,
        ":Attachments: %s" % (", ".join(attachment_names) or "(none)"),
        "",
        "----",
        "",
        body.strip("\n"),
        "",
    ]
    return "\n".join(lines)


def _generate_email_folders(batch_name, batch_config, storygen_settings: StorygenSettings, allow_missing_attachments=False):
    """
    Prepare one folder per email of this batch, in "<output dir>/emails/<batch>/<email>/": an RST file with the
    recipients, subject and body of the email, and a copy of its attachments. Nothing is sent, the user creates and
    sends these emails with their own mail client.

    Missing attachments are an error, unless allow_missing_attachments is set (when the build doesn't generate all
    PDF files), in which case they are skipped with a warning.
    """
    batch_config = batch_config or {}
    batch_settings = storygen_settings.derive(batch_config)
    del storygen_settings  # Safety
    selection = batch_settings.selection

    emails = batch_config.get("emails") or {}
    if isinstance(emails, (list, tuple)):  # Be tolerant, a list of names means emails without overrides
        emails = {email_name: {} for email_name in emails}
    if not isinstance(emails, dict):
        raise StorygenConfigError("The 'emails' of email batch '%s' must be a mapping of email names" % batch_name)

    emails_without_recipients = []
    emails_per_recipient = {}

    for email_name, email_config in emails.items():

        # Unlike sheets, unselected emails are not rendered at all, since they have no story tags to register
        if not selection.is_selected("%s/%s/%s" % (EMAILS_FOLDER, batch_name, email_name)):
            continue

        email_config = email_config or {}
        logging.info("Preparing folder of email '%s' of batch '%s'" % (email_name, batch_name))
        email_settings = batch_settings.derive(email_config, email_name=email_name, email_batch_name=batch_name)
        jinja_env = email_settings.jinja_env
        jinja_context = dict(email_settings.dynamic_variables)
        email_label = "%s/%s" % (batch_name, email_name)

        def _get_entry(key):
            value = email_config.get(key, batch_config.get(key))  # Per-email values replace those of the batch
            if not value:
                raise StorygenConfigError("Email '%s' has no '%s' entry (in its batch or in itself)" % (email_label, key))
            return value

        def _render_string(template_string):
            if not isinstance(template_string, str):
                raise StorygenConfigError("Email '%s' has a non-string entry: %r" % (email_label, template_string))
            if not template_string.strip():
                return ""
            return render_with_jinja(content=template_string, jinja_env=jinja_env, jinja_context=jinja_context).strip()

        email_path_variables = dict(email_settings.path_variables, email_name=email_name, email_batch_name=batch_name,
                                    output_dir=email_settings.output_root_dir.as_posix())

        subject = _get_entry("subject")
        if isinstance(subject, dict):  # Per-language subjects, since a configuration may serve several languages
            if subject.get(email_settings.language) is None:
                raise StorygenConfigError("Email '%s' has no subject for language %r" % (email_label, email_settings.language))
            subject = subject[email_settings.language]
        subject = " ".join(_render_string(subject).split())  # On a single line

        recipients = _get_entry("recipients")
        recipients = [recipients] if isinstance(recipients, str) else recipients
        recipients = [recipient for recipient in (_render_string(x) for x in recipients) if recipient]
        if not recipients:
            emails_without_recipients.append(email_name)
        for recipient in recipients:
            if "@" not in recipient:
                logging.warning("Email '%s' has a recipient which doesn't look like an email address: %r",
                                email_label, recipient)
            emails_per_recipient.setdefault(recipient, []).append(email_name)

        body_template = expand_path_placeholders(_get_entry("body_template"), email_path_variables)
        body = render_with_jinja(filename=body_template, jinja_env=jinja_env, jinja_context=jinja_context)

        rst_filename = "%s_email.rst" % email_name
        attachments = list(batch_config.get("attachments") or []) + list(email_config.get("attachments") or [])
        attachment_files = {}  # Basename -> source path
        for attachment in attachments:
            attachment_file = Path(expand_path_placeholders(attachment, email_path_variables))
            if not attachment_file.is_file():
                if allow_missing_attachments:
                    logging.warning("Skipping missing attachment '%s' of email '%s' (PDF generation is partly disabled)",
                                    attachment_file, email_label)
                    continue
                raise StorygenConfigError("Attachment '%s' of email '%s' does not exist" % (attachment_file, email_label))
            if attachment_file.name in attachment_files or attachment_file.name == rst_filename:
                raise StorygenConfigError("Email '%s' has several attachments named '%s'" % (email_label, attachment_file.name))
            attachment_files[attachment_file.name] = attachment_file

        # The folder is recreated from scratch, so that no stale attachment is ever sent
        email_dir = email_settings.output_root_dir.joinpath(EMAILS_FOLDER, batch_name, email_name)
        if email_dir.exists():
            shutil.rmtree(email_dir)
        email_dir.mkdir(parents=True)
        for attachment_name, attachment_file in attachment_files.items():
            shutil.copy2(attachment_file, email_dir.joinpath(attachment_name))
        rst_content = _format_email_rst(subject, recipients=recipients, attachment_names=list(attachment_files), body=body)
        email_dir.joinpath(rst_filename).write_text(rst_content, encoding="utf8")

    if emails_without_recipients:  # A single warning, since it's normal when private data are not filled
        logging.warning("Emails of batch '%s' without any recipient (marked %s in their RST file): %s",
                        batch_name, MISSING_RECIPIENT_MARKER, ", ".join(emails_without_recipients))
    for recipient, email_names in emails_per_recipient.items():
        if len(email_names) > 1:
            logging.warning("Recipient %r receives several emails of batch '%s': %s",
                            recipient, batch_name, ", ".join(email_names))


def _generate_summary_files(summary_config, storygen_settings: StorygenSettings):

    summary_config = summary_config or {}
    storygen_settings = storygen_settings.derive(summary_config)

    def _get_path(key):
        return expand_path_placeholders(summary_config.get(key), storygen_settings.path_variables)

    jinja_env = storygen_settings.jinja_env
    selection = storygen_settings.selection
    summaries = [  # (summary kind, registry, error detector)
        ("facts", jinja_env.facts_registry, detect_game_fact_errors),
        ("symbols", jinja_env.symbols_registry, detect_game_symbol_errors),
        ("items", jinja_env.items_registry, detect_game_item_errors),
    ]

    has_serious_errors = False
    all_error_messages = []
    for kind, registry, detect_errors in summaries:
        template_name = _get_path("game_%s_template" % kind)
        destination = _get_path("game_%s_destination" % kind)
        is_selected = bool(template_name and destination and selection.is_selected("summaries/%s" % kind))
        if selection.listing:
            continue
        # The coherence analysis is always done, even if the matching summary sheet is not configured or selected
        kind_has_serious_errors, error_messages = detect_errors(registry)
        has_serious_errors = has_serious_errors or kind_has_serious_errors
        all_error_messages += error_messages
        if is_selected:
            logging.info("Processing special sheet for game %s", kind)
            jinja_context = {"%s_registry" % kind: registry,
                             "has_serious_errors": kind_has_serious_errors,
                             "error_messages": error_messages,
                             **storygen_settings.dynamic_variables}
            render_with_jinja_and_convert_to_pdf(template_name,
                                                 relative_path=Path(destination),
                                                 jinja_context=jinja_context,
                                                 storygen_settings=storygen_settings)

    if selection.listing:
        return False
    logging.info("Processing final results of scenario coherence analysis")
    return _handle_analysis_results(has_serious_errors=has_serious_errors, error_messages=all_error_messages
    )


def _handle_analysis_results(has_serious_errors, error_messages):
    if has_serious_errors:
        logging.critical("*** Serious coherence errors were detected during the processing of scenario data, see details below ***")
    for criticity, message in error_messages:
        logger_func = logging.error if criticity == "ERROR" else logging.warning
        logger_func(message)
    return has_serious_errors


class _DefaultCommandGroup(click.Group):
    """Command group which runs its default command when the first argument is not a command name,
    so that "pychronia_storygen <project_dir>" stays a shortcut for "pychronia_storygen build <project_dir>"."""

    default_command_name = "build"

    def parse_args(self, ctx, args):
        if args and args[0] not in self.commands and args[0] not in ctx.help_option_names:
            args = [self.default_command_name] + list(args)
        return super().parse_args(ctx, args)


@click.group(cls=_DefaultCommandGroup)
def cli():
    """Generate (default "build" command) or remove ("clean" command) the files of a storygen project."""


VARIABLE_OPTION_HELP = ("Set a root variable, as NAME=VALUE (can be repeated). It overrides the 'variables' entry of "
                        "the configuration, and can be used in jinja2 templates and in '{NAME}' placeholders of "
                        "configuration paths. Values 'true'/'false' are booleans, integers are numbers, others "
                        "are strings.")


def parse_cli_variables(variable_pairs):
    """
    Turn the "NAME=VALUE" strings of --variable options into a dict of root variables.

    Values "true"/"false" (whatever their case) become booleans, integer literals become integers,
    and all others stay strings (eg. "fr", or "no" which YAML would turn into a boolean).
    """
    variables = {}
    for pair in variable_pairs or ():
        name, separator, value = pair.partition("=")
        name = name.strip()
        if not separator or not re.fullmatch(r"\w+", name):
            raise click.BadParameter("Expected NAME=VALUE (eg. 'lang=fr'), not %r" % pair, param_hint="--variable")
        if value.lower() in ("true", "false"):
            value = (value.lower() == "true")
        elif re.fullmatch(r"-?\d+", value):
            value = int(value)
        variables[name] = value
    return variables


def _check_language(language):
    """Validate the value of the "lang" root variable, and return it (None if no language is set)."""
    if language is None or language == "":
        return None
    if not isinstance(language, str) or not re.fullmatch(r"[a-z]{2}", language):
        raise click.BadParameter("Language must be a 2-letter lowercase code (eg. 'lang=fr'), not %r" % (language,),
                                 param_hint="variable '%s'" % LANGUAGE_VARIABLE)
    return language


def _get_output_and_build_root_dirs(language, output_dir):
    """Return the (output_root_dir, build_root_dir) paths, relative to the project dir unless output_dir is given."""
    output_root_dir = Path("./_output")
    build_root_dir = Path("./_build")
    if language:
        output_root_dir = output_root_dir.joinpath(language)
        build_root_dir = build_root_dir.joinpath(language)
    if output_dir:
        output_root_dir = Path(output_dir)
        build_root_dir = output_root_dir.joinpath("_build")
    return output_root_dir, build_root_dir


@cli.command()
@click.argument('project_dir', type=click.Path(exists=True, file_okay=False))
@click.option('--verbose', '-v', is_flag=True, help="Print more output.")
@click.option("-V", "--variable", "variable_pairs", multiple=True, metavar="NAME=VALUE",
              help=VARIABLE_OPTION_HELP + " The 'lang' variable (eg. 'lang=fr') is the language of a translated "
                   "project: its 'configuration_<lang>.yaml' file is used if it exists (else 'configuration.yaml'), "
                   "only the macros of language-neutral or '_<lang>' templates are loaded, and files are generated "
                   "in '_build/<lang>/' and '_output/<lang>/'.")
@click.option("-o", "--output-dir", "output_dir", default=None, type=click.Path(file_okay=False),
              help="Directory where generated output files are written, used as-is instead of the default "
                   "'<project_dir>/_output/' (or '<project_dir>/_output/<lang>/' when a language is set); "
                   "intermediate build files then go into its '_build/' subfolder.")
@click.option("--skip-document-splitting", "skip_document_splitting", is_flag=True,
              help="Parse ODT game documents for story tags, but don't split them into PDF files "
                   "(LibreOffice is then not needed); missing email attachments are then only warned about.")
@click.option("--only", "only_patterns", multiple=True, metavar="PATTERN",
              help="Only generate the files of the items whose ID matches this glob pattern (can be repeated), "
                   "eg. 'sheets/players/*', '*alice*' or '*/cheat'; see --list for the IDs. Unselected items "
                   "are still rendered (except summaries), so the coherence analysis stays complete.")
@click.option("--skip", "skip_patterns", multiple=True, metavar="PATTERN",
              help="Don't generate the files of the items whose ID matches this glob pattern (can be repeated), "
                   "even if they match an --only pattern.")
@click.option("--list", "listing", is_flag=True,
              help="Only print the IDs of the items of the project, marking those selected by --only/--skip, "
                   "without rendering or generating anything.")
@click.option("--no-pdf", "no_pdf", is_flag=True,
              help="Only write the intermediate RST files, without converting them to PDF files, and don't split "
                   "game documents (implies --skip-document-splitting): a quick check of templates and of scenario "
                   "coherence, but rst2pdf errors (eg. missing images) are then not detected.")
def build(project_dir, verbose, variable_pairs, output_dir, skip_document_splitting, only_patterns, skip_patterns,
          listing, no_pdf):
    """Generate the files of the project folder PROJECT_DIR (default command).

    Items whose files can be selected with --only/--skip have IDs like "sheets/<group>/.../<sheet>/full" (or
    "/cheat"), "documents/<bundle>", "inventories/<inventory>/per_section" (or "/per_crate"),
    "emails/<batch>/<email>" and "summaries/facts" (or "/symbols", "/items").
    """
    project_dir = os.path.abspath(project_dir).rstrip("\\/") + os.path.sep
    if output_dir:
        output_dir = os.path.abspath(output_dir)  # Resolved BEFORE we chdir into the project dir

    selection = ItemSelection(only_patterns=tuple(only_patterns), skip_patterns=tuple(skip_patterns), listing=listing)
    skip_document_splitting = skip_document_splitting or no_pdf  # Splitting produces PDF files with LibreOffice

    logging.basicConfig(level=(logging.DEBUG if verbose else (logging.WARNING if listing else logging.INFO)))

    cli_variables = parse_cli_variables(variable_pairs)
    cli_language = _check_language(cli_variables.get(LANGUAGE_VARIABLE))

    logging.debug("Switching to current working directory: %s", project_dir)
    os.chdir(project_dir)

    yaml_conf_file = "./configuration.yaml"   # FIXME
    if cli_language and os.path.exists("./configuration_%s.yaml" % cli_language):
        yaml_conf_file = "./configuration_%s.yaml" % cli_language
    logging.info("Loading project configuration file '%s'", yaml_conf_file)

    project_data_tree = load_yaml_file(yaml_conf_file) or {}

    # Root variables of the configuration, overridden by those of the command line: besides being jinja2 variables,
    # they are the only ones usable in the "{name}" placeholders of configuration paths (and in jinja2 settings)
    path_variables = dict(project_data_tree.get("variables") or {})
    path_variables.update(cli_variables)
    language = _check_language(path_variables.get(LANGUAGE_VARIABLE))

    output_root_dir, build_root_dir = _get_output_and_build_root_dirs(language, output_dir)
    excluded_template_dirs = [Path("./_output"), Path("./_build")]  # They contain generated files, not templates
    if output_dir:
        if output_root_dir.is_relative_to(project_dir):  # Excluded dirs must be relative to the templates root
            excluded_template_dirs.append(output_root_dir.relative_to(project_dir))
    if not listing:
        os.makedirs(output_root_dir, exist_ok=True)
        os.makedirs(build_root_dir, exist_ok=True)

    # Extra template directories are searched AFTER the project dir, and are also scanned for macros
    template_dirs = [expand_path_placeholders(template_dir, path_variables)
                     for template_dir in (project_data_tree.get("template_dirs") or [])]
    for template_dir in template_dirs:
        if not os.path.isdir(template_dir):
            raise StorygenConfigError("Template directory %r of 'template_dirs' does not exist" % template_dir)

    jinja_env = load_jinja_environment(["."] + template_dirs, use_macro_tags=True, language=language,
                                       excluded_dirs=excluded_template_dirs)

    # Jinja2 variables: data files are below the root variables (configuration, then command line), which take precedence
    root_variables = load_data_files(project_data_tree.get("data_files"), path_variables=path_variables)
    root_variables.update(path_variables)
    root_variables.update(project_dir=project_dir.replace("\\", "/"), language=language)  # "language" mirrors "lang"

    variables_hook = project_data_tree.get("variables_hook")
    if variables_hook:
        root_variables = run_variables_hook(variables_hook, root_variables, language=language, jinja_env=jinja_env,
                                            import_dirs=[project_dir] + [os.path.abspath(d) for d in template_dirs])

    storygen_settings = StorygenSettings(
        project_root_dir=project_dir,
        build_root_dir=build_root_dir,
        output_root_dir=output_root_dir,
        jinja_env=jinja_env,
        dynamic_variables=ChainMap(root_variables),
        dynamic_settings=ChainMap(project_data_tree.get("settings") or {}),
        language=language,
        path_variables=MappingProxyType(path_variables),
        selection=selection,
        generate_pdf=not no_pdf,
    )

    # GENERATE FULL SHEETS AND CHEAT SHEETS
    sheet_generation_tree = project_data_tree.get("sheet_generation")
    if sheet_generation_tree:
        _recursively_generate_group_sheets(sheet_generation_tree,
                                           group_breadcrumb=(),
                                           storygen_settings=storygen_settings)

    # GENERATE GAME DOCUMENTS
    # No derivation of storygen_settings here, since jinja/rst2pdf is not used
    document_generation_tree = project_data_tree.get("document_generation")
    if document_generation_tree:
        for document_bundle_name, document_config in document_generation_tree.items():
            _generate_document_files(document_bundle_name, document_config=document_config,
                                     storygen_settings=storygen_settings,
                                     skip_document_splitting=skip_document_splitting)

    # GENERATE INVENTORIES
    inventory_generation_tree = project_data_tree.get("inventory_generation")
    if inventory_generation_tree:
        for inventory_name, inventory_config in inventory_generation_tree.items():
            _generate_inventory_files(inventory_name,
                                      inventory_config=inventory_config,
                                      storygen_settings=storygen_settings)

    # PREPARE EMAIL FOLDERS (after sheets and documents, which provide their attachments)
    email_generation_tree = project_data_tree.get("email_generation")
    if email_generation_tree:
        for batch_name, batch_config in email_generation_tree.items():
            _generate_email_folders(batch_name, batch_config=batch_config, storygen_settings=storygen_settings,
                                    allow_missing_attachments=no_pdf or skip_document_splitting)

    # GENERATE SUMMARIES, and analyse scenario coherence (after all other items, which register story tags)
    summary_config = project_data_tree.get("summary_generation") or {}
    has_serious_errors = _generate_summary_files(summary_config, storygen_settings=storygen_settings)

    if listing:
        for item_id, is_selected in selection.items:
            click.echo("%s %s" % ("[x]" if is_selected else "[ ]", item_id))

    unmatched_patterns = selection.get_unmatched_patterns()
    if unmatched_patterns:  # Probably typos, which must not go unnoticed
        raise click.BadParameter("Pattern(s) %s match no item ID (see --list)" % ", ".join(map(repr, unmatched_patterns)),
                                 param_hint="--only/--skip")

    if has_serious_errors:
        raise click.exceptions.Exit(1)  # After all files were generated


# Patterns of the files generated by the "build" command: PDF documents, and intermediate RST files
GENERATED_OUTPUT_FILE_PATTERN = "*.pdf"
GENERATED_BUILD_FILE_PATTERN = "*.txt"


def _remove_empty_subfolders(root_dir: Path, dry_run):
    """Remove the subfolders of root_dir left empty (deepest first), but not root_dir itself."""
    subfolders = sorted((p for p in root_dir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True)
    for subfolder in subfolders:
        if not any(subfolder.iterdir()):
            logging.debug("Removing empty folder %s", subfolder)
            if not dry_run:
                subfolder.rmdir()


@cli.command()
@click.argument('project_dir', type=click.Path(exists=True, file_okay=False))
@click.option('--verbose', '-v', is_flag=True, help="Print more output.")
@click.option("-V", "--variable", "variable_pairs", multiple=True, metavar="NAME=VALUE",
              help="Root variable given to the 'build' command; only 'lang' matters here (eg. 'lang=fr'), to only "
                   "remove the files generated for this language (by default, those of all languages).")
@click.option("-o", "--output-dir", "output_dir", default=None, type=click.Path(file_okay=False),
              help="Output directory which was given to the 'build' command, if any.")
@click.option("--dry-run", "dry_run", is_flag=True, help="Only list the files which would be removed.")
def clean(project_dir, verbose, variable_pairs, output_dir, dry_run):
    """Remove the files generated from the project folder PROJECT_DIR.

    Only the PDF files of the output folder, all the files of its "emails/" folder, and the intermediate RST
    (".txt") files of the build folder, are removed, along with the subfolders they leave empty; any other file
    is kept.
    """
    logging.basicConfig(level=(logging.DEBUG if verbose else logging.INFO))
    language = _check_language(parse_cli_variables(variable_pairs).get(LANGUAGE_VARIABLE))

    project_dir = Path(project_dir).resolve()
    output_root_dir, build_root_dir = _get_output_and_build_root_dirs(
            language, output_dir=(os.path.abspath(output_dir) if output_dir else None))
    output_root_dir = project_dir.joinpath(output_root_dir).resolve()  # Absolute output_dir is kept as-is
    build_root_dir = project_dir.joinpath(build_root_dir).resolve()

    if project_dir.is_relative_to(output_root_dir):  # Source PDFs of the project would be removed too
        raise click.BadParameter("Output directory %s must not contain the project directory" % output_root_dir,
                                 param_hint="--output-dir")

    removed_count = 0

    # Email folders only contain generated files, whatever their type (RST files, copied attachments)
    email_roots = [output_root_dir.joinpath(EMAILS_FOLDER)]
    if not language and not output_dir:
        email_roots += sorted(output_root_dir.glob("*/" + EMAILS_FOLDER))  # Those of each language
    for email_root in email_roots:
        if not email_root.is_dir():
            continue
        for generated_file in sorted(email_root.rglob("*")):
            if not generated_file.is_file() or generated_file.suffix.lower() == ".pdf":
                continue  # PDF files are removed below, with those of the whole output folder
            logging.info("%s %s", "Would remove" if dry_run else "Removing", generated_file)
            if not dry_run:
                generated_file.unlink()
            removed_count += 1

    for root_dir, pattern in [(output_root_dir, GENERATED_OUTPUT_FILE_PATTERN),
                              (build_root_dir, GENERATED_BUILD_FILE_PATTERN)]:
        if not root_dir.is_dir():
            logging.info("Skipping missing folder %s", root_dir)
            continue
        for generated_file in sorted(root_dir.rglob(pattern)):
            if not generated_file.is_file():
                continue
            logging.info("%s %s", "Would remove" if dry_run else "Removing", generated_file)
            if not dry_run:
                generated_file.unlink()
            removed_count += 1
        _remove_empty_subfolders(root_dir, dry_run=dry_run)

    logging.info("%s %d generated file(s)", "Would remove" if dry_run else "Removed", removed_count)


if __name__ == "__main__":
    cli()