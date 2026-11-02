"""Venue style presets (user 2026-10-16: five reference cafe photos -> five cafes). A style steers three places at once:
the planner (a brief in the room payload, so it is part of the plan cache key), the procedural cafe assets (counter front/top,
back-bar wood) and the 2.0 wall/floor finishes (rematerial --style), plus which fixture kind hangs over the service."""

#: procedural counter finishes (linear RGB, roughness); the reference reader offers exactly these
COUNTER_FRONTS = {"white_panel": ((0.88, 0.87, 0.83), 0.5), "walnut_slat": ((0.22, 0.13, 0.07), 0.6), "oak_slat": ((0.55, 0.4, 0.24), 0.6), "amber_slat": ((0.5, 0.25, 0.07), 0.5), "sage_fluted": ((0.25, 0.33, 0.26), 0.5), "green_fluted": ((0.03, 0.14, 0.08), 0.5), "forest_fluted": ((0.013, 0.065, 0.036), 0.55),
                  "brick_red": ((0.42, 0.16, 0.1), 0.85), "matte_black": ((0.04, 0.04, 0.045), 0.5), "cream_tile": ((0.82, 0.79, 0.72), 0.3),
                  "concrete": ((0.5, 0.5, 0.48), 0.85)}
COUNTER_TOPS = {"white_stone": ((0.86, 0.85, 0.82), 0.25), "black_stone": ((0.07, 0.07, 0.07), 0.3), "butcher_block": ((0.5, 0.33, 0.18), 0.5), "amber_wood": ((0.62, 0.32, 0.09), 0.4),
                "steel": ((0.6, 0.6, 0.62), 0.25), "light_wood": ((0.62, 0.48, 0.32), 0.5), "dark_wood": ((0.2, 0.11, 0.06), 0.5)}


CAFE = {
    "nordic_bakery": {
        "brief": "Nordic bakery-cafe: a white wood-panelled counter with glass cake domes and baskets of bread on it, wine glasses "
                 "on the back shelves with bottles and stacked plates, a drinks fridge beside the counter, light and calm.",
        "counter_front": "white_panel", "counter_top": "butcher_block", "backbar": "oak_slat",
        "wall": "paint", "wall_rgb": [0.86, 0.84, 0.79], "floor": "wood", "fixture": "pendant", "clutter_exclude": ["wine_glass"]},
    "industrial_brick": {
        "brief": "Industrial brick cafe: exposed red brick, chalkboard menu boards, a row of black metal pendants, a long communal "
                 "table (break_table) with mixed chairs plus small tables, two velvet armchairs in a corner, plants on the tables, "
                 "cake domes on the counter.",
        "counter_front": "walnut_slat", "counter_top": "black_stone", "backbar": "walnut_slat",
        "wall": "brick", "floor": "wood", "fixture": "pendant"},
    "minimal_bar": {
        "brief": "Minimal modern coffee bar: a sage-green fluted counter with a white stone top and two bar stools in front, a "
                 "white tiled back wall with floating shelves of jars, bottles and coffee bags, espresso machine, big windows.",
        "counter_front": "sage_fluted", "counter_top": "white_stone", "backbar": "oak_slat",
        "wall": "paint", "wall_rgb": [0.92, 0.92, 0.9], "floor": "wood", "fixture": "pendant"},
    "chain_banquette": {
        "brief": "Bright chain cafe: a red brick counter, a long banquette (sofa) along one wall with a row of small tables and "
                 "metal cafe chairs opposite, a few mustard upholstered chairs, plants hanging and standing, a wood feature wall.",
        "counter_front": "brick_red", "counter_top": "steel", "backbar": "matte_black",
        "wall": "paint", "wall_rgb": [0.66, 0.64, 0.6], "floor": "wood", "fixture": "pendant",
        # the style's signature, added by the realizer when the plan leaves it out (cafe r1: 'no banquette in any tile')
        "require": [{"id": "req_banquette", "category": "banquette_row", "relation": "against_wall"}]},
    "floral_moody": {
        "brief": "Moody floral cafe: a black counter with a glass cake display, flowers in vases on every table and the counter, "
                 "dark wood panelling, warm low light, a chandelier over the counter.",
        "counter_front": "matte_black", "counter_top": "black_stone", "backbar": "walnut_slat",
        "wall": "paint", "wall_rgb": [0.1, 0.17, 0.13], "floor": "wood", "fixture": "chandelier",
        "table_extra": [["vase", 4]]},                            # flowers on every table (cafe r1: 'no florals')
}

STYLES = {"cafe": CAFE}


def get(venue, name):
    return STYLES.get(venue, {}).get(name)
