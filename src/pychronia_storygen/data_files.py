# -*- coding: utf-8 -*-
"""Loading of the YAML data files declared in the "data_files" entry of the project configuration."""
import logging
import os

from pychronia_storygen.document_formats import load_yaml_file, expand_lang_placeholder, StorygenConfigError


def deep_merge_localized_overlay(base, overlay, path=""):
    """
    Merge the (partial) translated tree "overlay" into the untranslated tree "base", in place.

    Every overlay key must already exist in the base, so that an obsolete overlay is detected when
    the base data gets regenerated.
    """
    for key, value in overlay.items():
        if key not in base:
            raise KeyError("Localized overlay key %r is missing from the untranslated data" % (path + str(key)))
        if isinstance(value, dict):
            if not isinstance(base[key], dict):
                raise TypeError("Localized overlay key %r is a mapping but the untranslated data is not" % (path + str(key)))
            deep_merge_localized_overlay(base[key], value, path=path + str(key) + ".")
        else:
            base[key] = value
    return base


def _find_first_existing_file(candidates):
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    raise StorygenConfigError("None of the data files %s exists" % ", ".join(repr(c) for c in candidates))


def load_data_files(data_files_config, language=None):
    """
    Load the "data_files" configuration entry (a list of mappings) and return the resulting dict of root variables.

    Each entry has a "file" (path, or list of candidate paths of which the first existing one is used),
    optionally an "overlay" (partial file, deep-merged over the data if it exists),
    and optionally a "variable" name under which the data is stored (else it must be a mapping, merged at the root).
    Paths may contain the "{lang}" placeholder, and are relative to the current directory (the project dir).
    Entries are processed in order, the following ones overriding the previous ones.
    """
    variables = {}
    for idx, entry in enumerate(data_files_config or []):
        if not isinstance(entry, dict) or not entry.get("file"):
            raise StorygenConfigError("Entry %d of 'data_files' must be a mapping with a 'file' key" % idx)

        candidates = entry["file"]
        candidates = [candidates] if isinstance(candidates, str) else list(candidates)
        candidates = [expand_lang_placeholder(candidate, language) for candidate in candidates]
        data_file = _find_first_existing_file(candidates)
        logging.info("Loading data file '%s'", data_file)
        data = load_yaml_file(data_file)

        overlay_file = expand_lang_placeholder(entry.get("overlay"), language)
        if overlay_file:
            if os.path.exists(overlay_file):
                logging.info("Merging data overlay '%s'", overlay_file)
                overlay = load_yaml_file(overlay_file)
                if overlay:
                    deep_merge_localized_overlay(data, overlay)
            else:
                logging.warning("No data overlay '%s' found, using base data only", overlay_file)

        variable_name = entry.get("variable")
        if variable_name:
            variables[variable_name] = data
        else:
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise StorygenConfigError("Data file '%s' must contain a mapping, since no 'variable' name is given" % data_file)
            variables.update(data)
    return variables
