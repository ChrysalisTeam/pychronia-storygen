
import copy
import functools
import logging
from pprint import pprint

import jinja2
import os
import re
import sys
import textwrap
import yaml
from jinja2 import nodes, lexer, pass_context, Template
from jinja2.ext import Extension
from jinja2.runtime import Context
from markupsafe import Markup


# Markers inserted into RST chunks, to be recognized later when generating full sheets
MARKER_FORMAT = r'{#>%(fact_name)s||%(as_what)s||%(player_id)s||%(is_cheat_sheet)s||%(no_output)s<#}'
MARKER_REGEX = r'\{#>(?P<fact_name>.+?)\|\|(?P<as_what>.*?)\|\|(?P<player_id>.*?)\|\|(?P<is_cheat_sheet>.+?)\|\|(?P<no_output>.+?)<#\}'

IS_CHEAT_SHEET_VARNAME = "is_cheat_sheet"
CURRENT_PLAYER_VARNAME = "current_player_id"
DUMMY_GAMEMASTER_NAME = "<master>"

AUTHORIZED_FACT_RECIPIENTS = ["author", "viewer"]
AUTHORIZED_ITEM_STATUSES = ['needed', 'provided']

ERROR_LEVEL_MARKER = "ERROR"
WARNING_LEVEL_MARKER = "WARNING"


class StoryChecksExtension(Extension):
    """
    With this extension, used via render_with_jinja_and_fact_tags(), coherence of
    the script can be checked. Some duplicates might be found in registries, because jinja
    templates are loaded multiple times (when importing macros, especially).

    The tag {% fact "my_fact_description" [as author] %} gathers facts and their authors,
    and exposes the resulting data in jinja_env.facts_registry.

    Similarly, a tag {% symbol "value" for "name" %} ensures unicity of a value amongst
    different text files, and encountered values are exposed in jinja_env.symbols_registry.

    Last but not least, a tag {% item "letter_from_x" is [needed/provided] %} exposes values in
    jinja_env.hints_registry, to check that hints required to solve enigmas are well listed in
    gamemaster checklists.

    These tags output the value they receive as first parameter. If no output is wanted, one must use
    the alternative tags *xfact, xsymbol or xitem*.
    """
    # a set of names that trigger the extension.
    tags = set(['fact','xfact', 'symbol', 'xsymbol', 'item', 'xitem'])

    @staticmethod
    def _normalize_title_string(title, normalize_case=True):
        """Important, else the fact-extractor REGEX will not work for example"""
        res = title.replace("\r\n", "").replace("\n", "").strip()
        return res.lower() if normalize_case else res

    def __init__(self, environment):
        super(StoryChecksExtension, self).__init__(environment)

        self.facts_registry = {}
        self.symbols_registry = {}
        self.items_registry = {}

        ## add registries to the environment
        environment.extend(
            facts_registry=self.facts_registry,  # (fact_name -> fact_data_dict) mapping
            symbols_registry=self.symbols_registry,  # (symbol_name -> symbol_values_set) mapping
            items_registry=self.items_registry,  # (items_name -> items_statuses_set) mapping
            extract_facts_from_intermediate_markup=functools.partial(extract_facts_from_intermediate_markup, facts_registry=self.facts_registry)
        )

    def parse(self, parser):

        template_name = parser.name
        # character_name = template_name.split("_")[0]

        # the first token is the token that started the tag.
        # We get the line number so that we can give
        # that line number to the nodes we create by hand.
        tag_name_token = next(parser.stream)  # gives a Token(lineno, type, value)
        lineno = tag_name_token.lineno
        tag_name = tag_name_token.value

        context = nodes.ContextReference()

        if tag_name in ('fact', 'xfact'):

            # now we parse a single expression
            fact_name = parser.parse_primary()

            token = parser.stream.current

            as_what_value = None
            if token.test('name:as'):
                next(parser.stream)
                as_what_value = parser.stream.expect(lexer.TOKEN_NAME).value  # eg "author"
            as_what = nodes.Const(as_what_value)

            # if "mytest" in fact_name.value:
            #    print(">> ENCOUNTERED FACT", fact_name.value, as_what.value, lineno, "in", parser.name)
            """
            # if there is a comma, the user provided a timeout.  If not use
            # None as second parameter.
            if parser.stream.skip_if('comma'):
                args.append(parser.parse_expression())
            else:
                args.append(nodes.Const(None))

            # now we parse the body of the cache block up to `endcache` and
            # drop the needle (which would always be `endcache` in that case)
            body = parser.parse_statements(['name:endcache'], drop_needle=True)

            # now return a `CallBlock` node that calls our _cache_support
            # helper method on this extension.
            return nodes.CallBlock(self.call_method('_cache_support', args),
                                   [], [], body).set_lineno(lineno)
            """

            # if parser.name:
            # IMPORTANT: we're not rendering from a string but from a template file,
            # so we assume we're in a macro import, so we DO NOT execute the Fact Tag!
            # return nodes.Output([])  # no output

            call = self.call_method('_fact_processing' if tag_name == "fact" else "_fact_processing_no_output", [fact_name, as_what, context], [], lineno=lineno)

        elif tag_name in ('symbol', 'xsymbol'):

            symbol_value = parser.parse_primary()

            for_token = parser.stream.expect('name:for').value
            # token = parser.stream.current
            # if not token.test('name:for'):
            #    raise

            symbol_name = parser.parse_primary()

            call = self.call_method('_symbol_processing' if tag_name == "symbol" else "_symbol_processing_no_output", [symbol_name, symbol_value, context], [], lineno=lineno)

        else:

            assert tag_name in ('item', 'xitem'), tag_name

            item_name = parser.parse_primary()

            is_token = parser.stream.expect('name:is').value

            item_status_value = parser.stream.expect(lexer.TOKEN_NAME).value  # eg. "needed" or "provided"
            item_status = nodes.Const(item_status_value)

            call = self.call_method('_item_processing' if tag_name == "item" else "_item_processing_no_output", [item_name, item_status, context], [], lineno=lineno)

        return nodes.Output([call], lineno=lineno)  # or nodes.CallBlock

    def _fact_processing(self, fact_name, as_what, context, no_output=False):

        fact_name = self._normalize_title_string(fact_name, normalize_case=False)

        player_id = context.get(CURRENT_PLAYER_VARNAME, DUMMY_GAMEMASTER_NAME)  # FIXME CHANGE THIS NAME
        is_cheat_sheet = context.get(IS_CHEAT_SHEET_VARNAME, False)

        ##print(">> >> PROCESSING FACT", fact_name, as_what, player_id)

        # if "mytest" in fact_name:
        #    print(">> >> PROCESSING FACT", fact_name, as_what, player_id)
        #    import traceback
        #    traceback.print_stack()

        if player_id is None:
            logging.debug("Aborting registration of fact '%s' because player-id is set to None", fact_name)
            return ""  # we abort registration of fact

        as_what = as_what or "viewer"  # default status

        if as_what not in AUTHORIZED_FACT_RECIPIENTS:
            raise RuntimeError("Abnormal fact status: %r for %r (authorized: %s)" % (as_what, fact_name, AUTHORIZED_FACT_RECIPIENTS))

        marker = MARKER_FORMAT % dict(fact_name=fact_name, as_what=as_what,
                                      player_id=player_id, is_cheat_sheet=int(is_cheat_sheet),
                                      no_output=int(no_output))
        return marker  # special marker for final extraction

    def _fact_processing_no_output(self, fact_name, as_what, context):
        return self._fact_processing(fact_name, as_what, context, no_output=True)

    def _symbol_processing(self, symbol_name, symbol_value, context, no_output=False):
        assert symbol_name, (symbol_name, symbol_value)
        symbol_name = self._normalize_title_string(symbol_name)
        symbols_list = self.symbols_registry.setdefault(symbol_name, set())
        symbols_list.add(symbol_value)
        return "" if no_output else symbol_value  # output the symbol itself if needed

    def _symbol_processing_no_output(self, symbol_name, symbol_value, context):
        return self._symbol_processing(symbol_name, symbol_value, context, no_output=True)

    def _item_processing(self, item_name, item_status, context, no_output=False):
        item_name = self._normalize_title_string(item_name, normalize_case=False)
        item_statuses = self.items_registry.setdefault(item_name.lower(), set())  # BEWARE we normalize case here!
        item_statuses.add(item_status)
        return "" if no_output else item_name  # output the item itself if needed

    def _item_processing_no_output(self, symbol_name, symbol_value, context):
        return self._item_processing(symbol_name, symbol_value, context, no_output=True)


def extract_facts_from_intermediate_markup(source, facts_registry):
    """
    Browse a transformed output, and extract facts from the special markup left in it by StoryChecksExtension.
    """

    def _process_fact(matchobj):
        ##print(">> WE GATHER FACT", matchobj.groups())
        fact_name = matchobj.group("fact_name")
        as_what = matchobj.group("as_what")
        player_id = matchobj.group("player_id")
        is_cheat_sheet = int(matchobj.group("is_cheat_sheet"))
        no_output = int(matchobj.group("no_output"))
        assert as_what in AUTHORIZED_FACT_RECIPIENTS, as_what
        is_author = (as_what == "author")

        fact_params = facts_registry.setdefault(fact_name.lower(), {})  # BEWARE we normalize case here!
        fact_player_params = fact_params.setdefault(player_id, {})

        fact_player_params['is_author'] = fact_player_params.get('is_author') or is_author
        fact_player_params['is_viewer'] = fact_player_params.get('is_viewer') or not is_author

        fact_player_params['in_cheat_sheet'] = fact_player_params.get('in_cheat_sheet') or is_cheat_sheet
        fact_player_params['in_normal_sheet'] = fact_player_params.get('in_normal_sheet') or not is_cheat_sheet

        return "" if no_output else fact_name  # output the fact itself if needed

    cleaned_source = re.sub(MARKER_REGEX, _process_fact, source, flags=0)
    return cleaned_source


def detect_game_item_errors(items_registry):
    has_serious_errors = False
    error_messages = []
    items_registry_good_value = set(AUTHORIZED_ITEM_STATUSES)
    for k, v in sorted(items_registry.items()):
        assert v <= items_registry_good_value, (k, v)  # no weird values
        if 'needed' in v and 'provided' not in v:
            error_messages.append((ERROR_LEVEL_MARKER, "Game item '%s' is needed but not provided" % k))
            has_serious_errors = True
        if 'provided' in v and 'needed' not in v:
            # It's not a blocking coherence error
            error_messages.append((WARNING_LEVEL_MARKER, "Game item '%s' is provided but not needed" % k))
    return has_serious_errors, error_messages


def detect_game_symbol_errors(symbols_registry):
    has_serious_errors = False
    error_messages = []
    for k, v in sorted(symbols_registry.items()):
        unique_values = set(x.lower() for x in v)  # Case-isnensitive, and we could go further to NORMALIZE
        if len(unique_values) != 1:
            error_messages.append((ERROR_LEVEL_MARKER, "Game symbol '%s' has several different values: %s" % (k, v)))
            has_serious_errors = True
    return has_serious_errors, error_messages


def detect_game_fact_errors(facts_registry):
    '''
    def __UNUSED_replace_all_players_set(names):
        """When all real players know a fact, replace their names by a symbol"""
        names_set = set(names)
        if all_player_names <= names_set:
            new_set = (names_set - all_player_names) | {"ALL-PLAYERS"}
        else:
            new_set = names_set
        return new_set
    '''

    ##print(">> FACTS")
    ##pprint(facts_registry)

    has_serious_errors = False
    error_messages = []

    def _check_fact_leaf(fact_name, player_id, fact_node):
        """Ensure that the knowledge of a single player over a single fact is coherent"""
        assert fact_node["in_normal_sheet"] or fact_node["in_cheat_sheet"], fact_node  # Sanity check
        assert fact_node["is_author"] or fact_node["is_viewer"], fact_node  # Sanity check
        _has_serious_errors = False
        _error_messages = []

        if fact_node["in_cheat_sheet"]:
            if not fact_node["in_normal_sheet"]:  # all facts must be explained in normal sheets
                _error_messages.append((ERROR_LEVEL_MARKER, "Game fact '%s' is in cheat-sheet but not in full-sheet for character '%s'" % (fact_name, player_id)))
                _has_serious_errors = True
        if fact_node["is_author"] and fact_node["is_viewer"]:
            _error_messages.append((ERROR_LEVEL_MARKER, "Game fact '%s' has character '%s' marked as both author and viewer for it" % (fact_name, player_id)))
            _has_serious_errors = True
        return _has_serious_errors, _error_messages

    facts_items = sorted(facts_registry.items())

    for (fact_name, fact_data) in facts_items:
        for player_id, fact_node in fact_data.items():
            _has_serious_errors, _error_messages = _check_fact_leaf(
                fact_name, player_id=player_id, fact_node=fact_node)
            has_serious_errors = has_serious_errors or _has_serious_errors
            error_messages.extend(_error_messages)

    return has_serious_errors, error_messages
    '''
    facts_summary = [(fact_name,  # .replace("_", " "),
                      sorted((x, y) for (x, y) in fact_data.items()
                             if y["is_author"] and x not in masked_user_names),
                      sorted((x, y) for (x, y) in fact_data.items()
                             if not y["is_author"] and x not in masked_user_names))
                     for (fact_name, fact_data) in facts_items]
    '''

def display_and_check_story_tags(jinja_env, masked_user_names):

    has_coherence_errors1, facts_summary = _display_and_check_story_facts(jinja_env, masked_user_names=masked_user_names)
    has_coherence_errors2 = _display_and_check_story_symbols(jinja_env)
    has_coherence_errors3 = _display_and_check_story_items(jinja_env)

    has_any_coherence_error = has_coherence_errors1 or has_coherence_errors2 or has_coherence_errors3

    return has_any_coherence_error, facts_summary
