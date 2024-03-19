import re


def _extract_important_marker_from_title(title, important_marker):
    new_title = title
    assert new_title, repr(new_title)
    is_important = (important_marker in new_title)
    if is_important:
        new_title = new_title.replace(important_marker, "")
    return is_important, new_title.strip()


def _extract_crate_name_from_title(title):
    crate_name = None
    new_title = title
    assert new_title, repr(new_title)
    # print(">>>>> SEARCHING CRATE IN TITLE", _title)
    match = re.search(r"^@\S+\s", new_title)
    if match:
        crate_name = match.group(0)
        new_title = new_title.replace(crate_name, "", 1)
        crate_name = crate_name.strip()  # Remove traling space
    return crate_name, new_title.strip()


def analyze_and_normalize_game_items(game_items_raw, important_marker: str):

    # Nowadays Python3 preserves ORDERING of keys!
    game_items_per_section = {}
    game_items_per_crate = {}

    for section_title, item_titles in game_items_raw.items():

        section_is_important, section_title = _extract_important_marker_from_title(section_title, important_marker=important_marker)
        section_crate, section_title = _extract_crate_name_from_title(section_title)
        section_crate = section_crate or section_title  # Fallback if none is specified
        assert section_title == section_title.strip()

        for item_title in item_titles:

            item_is_important, item_title = _extract_important_marker_from_title(item_title, important_marker=important_marker)
            item_crate, item_title = _extract_crate_name_from_title(item_title)
            item_crate = item_crate or section_crate  # Fallback if none is specified
            assert item_title == item_title.strip()

            item_data = dict(
                item_is_important=(section_is_important or item_is_important),
                item_title=item_title,
            )

            game_items_per_section_sublist = game_items_per_section.setdefault(section_title, [])
            game_items_per_section_sublist.append(item_data)

            game_items_per_crate_sublist = game_items_per_crate.setdefault(item_crate, [])
            game_items_per_crate_sublist.append(item_data)

    return (game_items_per_section, game_items_per_crate)