
import copy
import functools
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
MARKER_FORMAT = r'{#>%(fact_name)s|%(as_what)s|%(player_id)s|%(is_cheat_sheet)s<#}'
MARKER_REGEX = r'\{#>(?P<fact_name>.*?)\|(?P<as_what>.*?)\|(?P<player_id>.*?)\|(?P<is_cheat_sheet>.*?)<#\}'


class StoryChecksExtension(Extension):
    """
    With this extension, used via render_with_jinja_and_fact_tags(), coherence of
    the script can be checked. Some duplicates might be found in registries, because jinja
    templates are loaded multiple times (when importing macros, especially).

    The tag {% fact "my_fact_description" [as author] %} gathers facts and their authors,
    and exposes the resulting data in jinja_env.facts_registry.

    Similarly, a tag {% symbol "value" for "name" %} ensures unicity of a value amongst
    different text files, and encountered values are exposed in jinja_env.symbols_registry.

    Last but not least, a tag {% hint "letter_from_x" is [needed/provided] %} exposes values in
    jinja_env.hints_registry, to check that hints required to solve enigmas are well listed in
    gamemaster checklists.
    """
    # a set of names that trigger the extension.
    tags = set(['fact', 'symbol', 'hint'])

    DUMMY_GAMEMASTER_NAME = "<master>"

    def __init__(self, environment):
        super(StoryChecksExtension, self).__init__(environment)

        self.facts_registry = {}
        self.symbols_registry = {}
        self.hints_registry = {}

        ## add registries to the environment
        environment.extend(
            facts_registry=self.facts_registry,  # (fact_name -> fact_data_dict) mapping
            symbols_registry=self.symbols_registry,  # (symbol_name -> symbol_values_set) mapping
            hints_registry=self.hints_registry,  # (hint_name -> hint_statuses_set) mapping
            extract_facts_from_intermediate_markup=functools.partial(extract_facts_from_intermediate_markup, facts_registry=self.facts_registry)
        )

    def parse(self, parser):

        template_name = parser.name
        # character_name = template_name.split("_")[0]

        # the first token is the token that started the tag.
        # We get the line number so that we can give
        # that line number to the nodes we create by hand.
        tag_name = next(parser.stream)  # gives a Token(lineno, type, value)
        lineno = tag_name.lineno
        context = nodes.ContextReference()

        if tag_name.value == 'fact':

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

            call = self.call_method('_fact_processing', [fact_name, as_what, context], [], lineno=lineno)

        elif tag_name.value == 'symbol':

            symbol_value = parser.parse_primary()

            for_token = parser.stream.expect('name:for').value
            # token = parser.stream.current
            # if not token.test('name:for'):
            #    raise

            symbol_name = parser.parse_primary()

            call = self.call_method('_symbol_processing', [symbol_name, symbol_value, context], [], lineno=lineno)

        else:

            assert tag_name.value == 'hint'

            hint_name = parser.parse_primary()

            is_token = parser.stream.expect('name:is').value

            hint_status_value = parser.stream.expect(lexer.TOKEN_NAME).value  # eg. "needed" or "provided"
            hint_status = nodes.Const(hint_status_value)

            call = self.call_method('_hint_processing', [hint_name, hint_status, context], [], lineno=lineno)

        return nodes.Output([call], lineno=lineno)  # or nodes.CallBlock

    def _fact_processing(self, fact_name, as_what, context):

        player_id = context.get("current_player_id", self.DUMMY_GAMEMASTER_NAME)
        is_cheat_sheet = context.get("is_cheat_sheet", False)

        # if "mytest" in fact_name:
        #    print(">> >> PROCESSING FACT", fact_name, as_what, player_id)
        #    import traceback
        #    traceback.print_stack()

        if player_id is None:
            return ""  # we abort registration of fact

        as_what = as_what or "viewer"  # default status
        marker = MARKER_FORMAT % dict(fact_name=fact_name, as_what=as_what,
                                      player_id=player_id, is_cheat_sheet=int(is_cheat_sheet))
        return marker  # special marker for final extraction

    def _symbol_processing(self, symbol_name, symbol_value, context):
        assert symbol_name, (symbol_name, symbol_value)
        symbols_list = self.symbols_registry.setdefault(symbol_name, set())
        symbols_list.add(symbol_value)
        return symbol_value  # output the symbol itself

    def _hint_processing(self, hint_name, hint_status, context):
        hint_statuses = self.hints_registry.setdefault(hint_name, set())
        hint_statuses.add(hint_status)
        return ""  # empty output


def extract_facts_from_intermediate_markup(source, facts_registry):
    """
    Browse a transformed output, and extract facts from the special markup left in it by StoryChecksExtension.
    """

    def process_fact(matchobj):

        fact_name = matchobj.group("fact_name")
        as_what = matchobj.group("as_what")
        player_id = matchobj.group("player_id")
        is_cheat_sheet = int(matchobj.group("is_cheat_sheet"))

        if as_what not in ("author", "viewer"):
            raise RuntimeError("Abnormal fact status: %r in %r" % (as_what, matchobj.group(0)))
        is_author = (as_what == "author")

        fact_params = facts_registry.setdefault(fact_name, {})
        player_params = fact_params.setdefault(player_id, {})

        if player_params:
            assert player_params['is_author'] == is_author, (fact_name, player_id)
        player_params['is_author'] = player_params.get('is_author') or is_author

        player_params['in_cheat_sheet'] = player_params.get('in_cheat_sheet') or is_cheat_sheet
        player_params['in_normal_sheet'] = player_params.get('in_normal_sheet') or not is_cheat_sheet

        return ""  # REMOVE OUTPUT

    cleaned_source = re.sub(MARKER_REGEX, process_fact, source, flags=0)
    return cleaned_source


def _display_and_check_story_hints(jinja_env):
    from pprint import pprint

    print("\nInline hints of scenario:")
    pprint(jinja_env.hints_registry)

    has_coherence_errors = False
    hints_registry_good_value = set(['needed', 'provided'])
    for k, v in sorted(jinja_env.hints_registry.items()):
        assert v <= hints_registry_good_value, (k, v)  # no weird values
        if 'needed' in v and 'provided' not in v:
            print("!!!!! ERROR IN hints registry for key", repr(k), ':', v, 'requires a provided hint')
            has_coherence_errors = True
        if 'provided' in v and 'needed' not in v:
            print("!!!!! WARNING IN hints registry for key", repr(k), ':', v, 'normally requires a needed hint')
            # It's not a blocking coherence error, do don't set has_coherence_errors here

    return has_coherence_errors


def _display_and_check_story_symbols(jinja_env):
    from pprint import pprint

    print("\nInline symbols of scenario:")
    pprint(jinja_env.symbols_registry)

    has_coherence_errors = False
    for k, v in jinja_env.symbols_registry.items():
        unique_values = set(x.strip().lower().replace("\n", "") for x in v)
        if len(unique_values) != 1:
            print("!!!!! ERROR IN symbols registry for key", k, ':', v)
            has_coherence_errors = True
    return has_coherence_errors


def _display_and_check_story_facts(jinja_env, masked_user_names):
    from pprint import pprint
    assert isinstance(masked_user_names, (set, tuple, list)), repr(masked_user_names)

    __masked_user_names = list(masked_user_names) + [StoryChecksExtension.DUMMY_GAMEMASTER_NAME]  # FIXME UNUSED

    facts_registry_stripped = [(k, sorted(v)) for (k, v) in jinja_env.facts_registry.items()]

    print("\nInline facts of scenario:")
    pprint(facts_registry_stripped)

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

    has_coherence_errors = False

    def _check_fact_leaf(fact_name, player_id, fact_node):
        """Ensure that the knowledge of a single player over a single fact is coherent"""
        assert fact_node["in_normal_sheet"] or fact_node["in_cheat_sheet"], fact_node
        _has_coherence_errors = False
        if fact_node["in_cheat_sheet"]:
            if not fact_node["in_normal_sheet"]:  # all facts must be explained in normal sheets
                print("!!!!! ERROR IN fact leaf for key", fact_name, ':', player_id, fact_node)
                _has_coherence_errors = True
        return _has_coherence_errors

    facts_items = sorted(jinja_env.facts_registry.items())

    for (fact_name, fact_data) in facts_items:
        for player_id, fact_node in fact_data.items():
            has_coherence_errors = _check_fact_leaf(fact_name, player_id=player_id, fact_node=fact_node) or has_coherence_errors

    facts_summary = [(fact_name,  # .replace("_", " "),
                      sorted((x, y) for (x, y) in fact_data.items()
                             if y["is_author"] and x not in masked_user_names),
                      sorted((x, y) for (x, y) in fact_data.items()
                             if not y["is_author"] and x not in masked_user_names))
                     for (fact_name, fact_data) in facts_items]

    return has_coherence_errors, facts_summary


def display_and_check_story_tags(jinja_env, masked_user_names):

    has_coherence_errors1, facts_summary = _display_and_check_story_facts(jinja_env, masked_user_names=masked_user_names)
    has_coherence_errors2 = _display_and_check_story_symbols(jinja_env)
    has_coherence_errors3 = _display_and_check_story_hints(jinja_env)

    has_any_coherence_error = has_coherence_errors1 or has_coherence_errors2 or has_coherence_errors3

    return has_any_coherence_error, facts_summary
