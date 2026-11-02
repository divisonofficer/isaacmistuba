"""What the realizer can place: the vocabulary the room planner (LLM) is allowed to use.

Each category names where its geometry comes from -- an ABO product pool (furnish_rooms.POOLS key / abo_assets factory) or an
Infinigen factory -- and a typical size (m, width x depth x height) the planner can reason about clearances with.
"""

FURNITURE = {
    # seating
    "sofa":           {"src": "abo:sofa",        "size": [2.0, 0.9, 0.85], "rooms": ["living-room", "cafe"]},
    "bed":            {"src": "inf:BedFactory",  "size": [2.1, 1.7, 0.9], "rooms": ["bedroom"]},                  # home bedrooms had no bed (P2 r1 FUN-01)
    "dining_table":   {"src": "inf:TableDiningFactory", "size": [1.8, 0.9, 0.75], "rooms": ["dining-room", "kitchen"]},
    "armchair":       {"src": "abo:armchair",    "size": [0.85, 0.85, 0.9], "rooms": ["living-room", "bedroom", "cafe", "boutique"]},
    "dining_chair":   {"src": "copy:dining",     "size": [0.45, 0.5, 0.85], "rooms": ["dining-room", "kitchen"]},
    "conference_chair": {"src": "inf:OfficeChairFactory", "size": [0.6, 0.6, 1.0], "rooms": ["meeting-room", "office", "exam-room"]},
    "desk_chair":     {"src": "inf:OfficeChairFactory", "size": [0.6, 0.6, 1.0], "rooms": ["bedroom", "living-room", "office", "open-office", "meeting-room", "clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy"]},
    # tables
    "coffee_table":   {"src": "abo:coffee",      "size": [1.1, 0.6, 0.45], "rooms": ["living-room"]},
    "side_table":     {"src": "abo:side",        "size": [0.5, 0.5, 0.6], "rooms": ["living-room", "bedroom"]},
    "nightstand":     {"src": "abo:nightstand",  "size": [0.5, 0.4, 0.6], "rooms": ["bedroom"]},
    "desk":           {"src": "abo:desk", "size": [1.2, 0.6, 0.75], "rooms": ["bedroom", "living-room"]},
    "office_desk":    {"src": "proc:OfficeDeskFactory", "size": [1.6, 0.8, 0.75], "rooms": ["office", "open-office"]},   # critic r3
    # storage
    "dresser":        {"src": "abo:dresser",     "size": [1.2, 0.5, 0.9], "rooms": ["bedroom"]},
    "sideboard":      {"src": "abo:dresser",     "size": [1.4, 0.45, 0.85], "rooms": ["dining-room", "living-room"]},
    "bookshelf":      {"src": "abo:bookcase", "size": [0.8, 0.3, 1.8], "rooms": ["living-room", "bedroom", "cafe", "office"]},
    "office_bookcase": {"src": "proc:OfficeShelfFactory", "size": [0.9, 0.35, 1.8], "rooms": ["office"]},   # plain, stocked (floor C r4: an
                                                                                                         # ABO ladder shelf read residential, empty)
    "tv_stand":       {"src": "inf:TVStandFactory", "size": [1.6, 0.4, 0.5], "rooms": ["living-room"]},
    # lighting, textiles, plants
    "floor_lamp":     {"src": "abo:floorlamp",   "size": [0.4, 0.4, 1.6], "rooms": ["living-room", "bedroom"]},
    "rug":            {"src": "abo:rug",         "size": [2.0, 1.4, 0.01], "rooms": ["living-room", "bedroom", "dining-room", "boutique"]},
    "floor_plant":    {"src": "inf:LargePlantContainerFactory", "size": [0.5, 0.5, 1.1], "rooms": ["balcony", "living-room", "bedroom", "dining-room", "office", "open-office", "meeting-room", "cafe", "grocery", "clinic-reception", "physio-room", "boutique", "pharmacy"]},
    # workplaces: warehouse / garage / utility
    "storage_rack":   {"src": "proc:StorageRackFactory", "size": [2.1, 0.7, 2.3], "rooms": ["warehouse", "garage", "utility"]},
    "stock_shelf":    {"src": "proc:StockShelfFactory", "size": [1.8, 0.55, 2.1], "rooms": ["warehouse", "utility"]},   # back stockrooms
    "supply_shelf":   {"src": "proc:SupplyShelfFactory", "size": [1.2, 0.45, 2.0], "rooms": ["utility", "warehouse"]},   # clinic sterilisation / supply
    "wide_shelf":     {"src": "proc:StorageRackFactory", "size": [2.1, 0.7, 2.3], "rooms": ["warehouse", "garage"]},
    "pallet":         {"src": "proc:PalletFactory", "size": [1.2, 0.8, 0.14], "rooms": ["warehouse"]},
    "box_pile":       {"src": "proc:BoxPileFactory", "size": [1.2, 0.8, 0.9], "rooms": ["warehouse", "garage", "grocery"]},
    "workbench":      {"src": "proc:WorkbenchFactory", "size": [1.8, 0.75, 0.9], "rooms": ["warehouse", "garage"]},
    "ladder":         {"src": "proc:StepLadderFactory", "size": [0.6, 0.5, 1.5], "rooms": ["warehouse", "garage", "utility"]},
    "stool":          {"src": "proc:ShopStoolFactory", "size": [0.35, 0.35, 0.7], "rooms": ["warehouse", "garage"]},
    "utility_cart":   {"src": "proc:PlatformCartFactory", "size": [0.95, 0.6, 1.0], "rooms": ["warehouse", "grocery"]},
    "fan":            {"src": "abo:fan",         "size": [0.4, 0.3, 1.0], "rooms": ["warehouse", "garage"]},
    # offices
    "meeting_table":  {"src": "proc:ConferenceTableFactory",   "size": [2.4, 1.1, 0.75], "rooms": ["meeting-room", "office"]},   # open office: inside glass_meeting_room only (critic r3)
    "filing_cabinet": {"src": "proc:FilingCabinetFactory",      "size": [0.5, 0.6, 1.0], "rooms": ["office", "open-office", "clinic-reception", "exam-room"]},
    "break_table":    {"src": "proc:BreakTableFactory", "size": [1.6, 0.9, 0.75], "rooms": ["break-room", "cafe"]},
    "break_chair":    {"src": "proc:CafeChairFactory",     "size": [0.45, 0.5, 0.85], "rooms": ["break-room"]},
    # cafe / grocery store (single-room layouts relabelled with plan_scene --venue)
    "counter":        {"src": "proc:CafeCounterFactory", "size": [2.4, 0.65, 1.0], "rooms": ["cafe", "grocery", "convenience", "boutique"]},
    "backbar_shelf":  {"src": "proc:BackBarShelfFactory", "size": [2.0, 0.28, 2.2], "rooms": ["cafe", "pharmacy"]},
    "cafe_table":     {"src": "proc:CafeTableFactory", "size": [0.7, 0.7, 0.75], "rooms": ["cafe"]},
    "balloon_sign":   {"src": "inf:BalloonFactory", "size": [0.15, 1.6, 0.4], "rooms": ["_internal"]},   # foil letter balloons (inf)
    "menu_board":     {"src": "proc:MenuBoardFactory",       "size": [1.0, 0.4, 1.6], "rooms": ["cafe", "convenience"]},
    "window_bar":     {"src": "proc:WindowBarFactory", "size": [2.4, 0.4, 1.05], "rooms": ["cafe"]},
    "coffee_bar":     {"src": "zone:coffee_bar", "size": [2.6, 1.9, 2.2], "rooms": ["cafe"]},
    "gondola":        {"src": "proc:GondolaFactory", "size": [1.9, 0.9, 1.5], "rooms": ["grocery", "convenience", "pharmacy"]},
    "banquette_row":  {"src": "zone:banquette_row", "size": [3.0, 1.9, 1.0], "rooms": ["cafe"]},
    "banquette":      {"src": "proc:BanquetteFactory", "size": [3.0, 0.55, 1.0], "rooms": ["_internal"]},
    # clinics and shops (non-home 20, 2026-10-16)
    "clinic_desk":    {"src": "proc:ClinicDeskFactory", "size": [1.2, 0.65, 0.75], "rooms": ["exam-room", "dental-room", "physio-room"]},
    "reception_desk": {"src": "proc:ReceptionDeskFactory", "size": [2.4, 0.75, 1.12], "rooms": ["clinic-reception", "pharmacy", "break-room", "open-office"]},
    "oak_vanity":      {"src": "proc:OakBasinVanityFactory", "size": [0.5, 1.3, 2.1], "rooms": ["restroom"]},     # floors G/H restroom refs: oak vanity + vessel basin + round brass mirror
    "wc_cubicle":      {"src": "proc:TiledWcCubicleFactory", "size": [2.0, 1.2, 2.0], "rooms": ["restroom"]},     # white-tiled WC cubicle with an ajar oak door
    "water_heater":    {"src": "proc:WaterHeaterFactory", "size": [0.55, 0.55, 1.6], "rooms": ["utility"]},     # floors G/H utility refs: cylindrical tank with pipes
    "mop_sink":        {"src": "proc:MopSinkFactory", "size": [0.55, 0.65, 1.4], "rooms": ["utility"]},        # stainless service basin, tall tap, mop + broom
    "oak_credenza":    {"src": "proc:OakCredenzaFactory", "size": [0.4, 1.8, 0.75], "rooms": ["office", "meeting-room"]},     # B refs: long low oak side cabinet instead of a tall bookcase
    "open_wardrobe":   {"src": "proc:OpenWardrobeFactory", "size": [0.55, 2.4, 2.3], "rooms": ["closet", "bedroom"]},     # P2b closet ref: open rails with hanging garments + shelves
    "bed_bench":       {"src": "proc:BedBenchFactory", "size": [0.45, 1.5, 0.46], "rooms": ["bedroom"]},         # P2b suite refs: upholstered bench at the foot of the bed
    "bedroom_media":   {"src": "proc:BedroomMediaFactory", "size": [0.4, 2.4, 2.4], "rooms": ["bedroom"]},      # P2b master: TV panel + long floating oak console
    "oak_vanity_long": {"src": "proc:LongOakVanityFactory", "size": [0.5, 2.6, 2.1], "rooms": ["restroom", "bathroom"]},     # B / P2b master bath: ONE long double-basin oak vanity + continuous mirror with an LED edge
    "food_stall_row":  {"src": "proc:FoodStallRowFactory", "size": [1.4, 6.0, 2.7], "rooms": ["cafe", "grocery"]},      # M refs: a row of three red food-court stalls with striped awnings
    "lp_grid_wall":    {"src": "proc:LpGridWallFactory", "size": [0.34, 4.9, 4.9], "rooms": ["cafe"]},      # S34 LP cafe: floor-to-ceiling black grid cubbies of face-out LP sleeves
    "raised_platform": {"src": "proc:RaisedPlatformFactory", "size": [2.4, 4.0, 1.2], "rooms": ["cafe"]},   # S34: a 16 cm oak-herringbone platform with a glass balustrade
    "vehicle_ramp":    {"src": "proc:VehicleRampFactory", "size": [7.0, 4.0, 1.4], "rooms": ["warehouse", "hallway"]},      # S28F: a concrete ramp with white arrows and yellow-black kerbs
    "ramen_kitchen":   {"src": "proc:RamenKitchenFactory", "size": [1.2, 6.0, 2.6], "rooms": ["cafe"]},      # S32: the open kitchen block (tile wall, hood, range, steel tables, bowl shelves, walnut canopy box)
    "desk_bench":      {"src": "proc:DeskBenchFactory", "size": [1.5, 4.8, 1.2], "rooms": ["open-office", "break-room"]},      # O3/O4: back-to-back bench desks with a planter divider; layout 'seats' = desks per side; its chairs follow (facing = the +x row)
    "white_island":    {"src": "proc:WhiteIslandFactory", "size": [1.0, 4.0, 1.0], "rooms": ["break-room", "cafe"]},      # O4: a long white cafe island, oak slat stool side (layout counter + note 'cafe_island' / 'white island')
    "accent_armchair": {"src": "proc:AccentArmchairFactory", "size": [0.8, 0.8, 0.9], "rooms": ["bedroom"]},      # hotel: a tub chair in the room's accent colour (kit STYLE armchair_rgb_by_room; realize swaps "armchair" for it)
    "loveseat":        {"src": "proc:LoveseatFactory", "size": [0.8, 1.5, 0.85], "rooms": ["bedroom"]},      # hotel: a two-seat accent loveseat (kit STYLE sofa_rgb_by_room; realize swaps "sofa" for it)
    "luggage_rack":    {"src": "proc:LuggageRackFactory", "size": [0.45, 0.7, 0.5], "rooms": ["bedroom"]},      # hotel: an oak X-frame rack with black straps
    "ticket_machine":  {"src": "proc:TicketMachineFactory", "size": [0.34, 0.44, 1.5], "rooms": ["break-room", "cafe", "restaurant", "grocery", "convenience"]},      # ramen-shop meal-ticket vending machine (S32 r15 R7): layout category "ticket_machine" (the old register was a monitor on a ribbed box)
    "open_chiller":    {"src": "proc:OpenChillerFactory", "size": [0.8, 1.8, 2.0], "rooms": ["grocery", "convenience", "cafe", "break-room", "pharmacy"]},      # an open-front (doorless) multideck chiller, stocked with chilled goods; layout size_m[0] = its length
    "pouf":            {"src": "proc:PoufFactory", "size": [0.6, 0.6, 0.45], "rooms": ["break-room", "open-office"]},      # O5: a patterned round pouf (kit STYLE pouf_rgb)
    "wire_stool":      {"src": "proc:WireStoolFactory", "size": [0.4, 0.4, 0.66], "rooms": ["break-room", "open-office", "cafe"]},      # O5: a round-wire stool (kit STYLE wire_stool_rgb)
    "globe_pendant":   {"src": "proc:GlobePendantFactory", "size": [0.5, 0.5, 1.4], "rooms": []},      # O5: a white globe on a cord; hung by the ceiling pass, origin at the mount
    "island_counter":  {"src": "proc:IslandCounterFactory", "size": [1.6, 4.2, 1.5], "rooms": ["cafe"]},      # S34: the curved central coffee-counter island (stadium shape, LP sleeve front, pastry case + machines)
    "standing_lamp":   {"src": "proc:StandingLampFactory", "size": [0.4, 0.4, 1.75], "rooms": ["cafe", "break-room"]},      # layout floor_lamp: brass pole, pleated cream shade, warm glow
    "bar_portal":      {"src": "proc:BarPortalFactory", "size": [0.7, 4.2, 2.5], "rooms": ["cafe"]},      # S33 cottage bar: wide timber portal frame + a dark stone step marking the raised bar zone
    "standing_ac":     {"src": "proc:StandingAcFactory", "size": [0.35, 0.5, 1.8], "rooms": ["cafe", "break-room"]},     # S33: a freestanding floor air-conditioner
    "atrium_planter":  {"src": "proc:AtriumPlanterFactory", "size": [0.9, 3.4, 2.1], "rooms": ["utility"]},     # O2 atrium ref: one long raised planter, white stone cover, dense tall palms
    "floor_drain":     {"src": "proc:FloorDrainFactory", "size": [0.2, 0.2, 0.02], "rooms": ["utility", "kitchen"]},     # G/H utility ref: a floor drain
    "optical_table":   {"src": "proc:OpticalTableFactory", "size": [1.2, 2.4, 0.95], "rooms": ["utility"]},     # N2 lab refs: stainless optical table with mounts, mirrors, laser, beam lines
    "vacuum_chamber":  {"src": "proc:VacuumChamberFactory", "size": [1.0, 1.4, 1.45], "rooms": ["utility"]},     # horizontal vacuum chamber with CF flanges, viewport, roughing line
    "instrument_rack": {"src": "proc:InstrumentRackFactory", "size": [0.8, 0.6, 1.9], "rooms": ["utility"]},     # 19-inch instrument rack with display / LED front units
    "modular_sofa":   {"src": "proc:ModularSofaFactory", "size": [1.8, 2.7, 0.85], "rooms": []},      # atrium lounge (atrium_lobby_01): modular dark blue-grey lounge group
    "round_stool":    {"src": "proc:RoundStoolFactory", "size": [0.4, 0.4, 0.43], "rooms": []},
    "shell_chair":    {"src": "proc:ShellChairFactory", "size": [0.6, 0.6, 0.85], "rooms": []},
    "book_tower":     {"src": "proc:BookTowerFactory", "size": [0.8, 0.6, 1.9], "rooms": []},
    "round_rug":      {"src": "proc:RoundRugFactory", "size": [4.6, 4.6, 0.012], "rooms": []},
    "glass_bench":    {"src": "proc:GlassBenchFactory", "size": [0.4, 1.5, 0.4], "rooms": []},
    "stone_column":   {"src": "proc:StoneColumnFactory", "size": [0.9, 0.9, 7.8], "rooms": []},
    "round_pillar":   {"src": "proc:RoundPillarFactory", "size": [0.64, 0.64, 7.8], "rooms": []},
    "mezzanine":      {"src": "proc:MezzanineFactory", "size": [4.0, 9.0, 5.5], "rooms": []},
    "copper_duct":    {"src": "proc:CopperDuctFactory", "size": [9.0, 3.0, 1.3], "rooms": []},
    "book_wall":      {"src": "proc:BookWallFactory", "size": [0.4, 3.0, 2.4], "rooms": []},
    "staircase":       {"src": "proc:StairFlightFactory", "size": [1.3, 3.6, 2.4], "rooms": ["break-room", "hallway"]},     # N2 lobby: a stair flight with steel stringers + handrails
    "notice_panel":    {"src": "proc:NoticePanelFactory", "size": [0.03, 0.6, 0.85], "rooms": ["break-room", "hallway"]},     # N2 lobby: a pin-up notice board (wall-mounted)
    "prep_table":     {"src": "proc:PrepTableFactory", "size": [0.7, 1.8, 1.3], "rooms": ["_internal"]},
    "pallet_rack":    {"src": "proc:PalletRackFactory", "size": [1.1, 2.7, 4.4], "rooms": ["_internal"]},
    "dock_door":      {"src": "proc:RollerShutterFactory", "size": [0.5, 4.1, 4.75], "rooms": ["_internal"]},
    "clinic_low_table": {"src": "proc:ClinicLowTableFactory", "size": [1.1, 0.55, 0.42], "rooms": ["_internal"]},
    "exercise_mat":   {"src": "proc:ExerciseMatFactory", "size": [1.8, 0.6, 0.02], "rooms": ["_internal"]},
    "waiting_bench":  {"src": "proc:UpholsteredBenchFactory", "size": [2.2, 0.6, 0.85], "rooms": ["clinic-reception", "pharmacy"]},   # not exam rooms:
                                                                                     # a 3-seat beam bench read as a second waiting room (floor D3 r2)
    "exam_table":     {"src": "proc:ExamTableFactory", "size": [0.65, 1.9, 0.9], "rooms": ["exam-room", "physio-room"]},
    "supply_cart":    {"src": "proc:ExamSupplyCartFactory", "size": [0.5, 0.8, 1.0], "rooms": ["exam-room"]},          # generated prop (data/venue_refs/generated_props)
    "rolling_stool":  {"src": "proc:RollingStoolFactory", "size": [0.55, 0.55, 0.55], "rooms": ["exam-room", "physio-room"]},
    "wall_diagnostic": {"src": "proc:WallDiagnosticSetFactory", "size": [0.1, 0.5, 0.5], "rooms": ["exam-room"]},
    "curtain_divider": {"src": "proc:CurtainDividerFactory", "size": [2.4, 0.12, 2.3], "rooms": ["physio-room", "exam-room"]},     # generated prop: a curtain run perpendicular to the wall between beds
    "wall_monitor":   {"src": "proc:WallMonitorFactory", "size": [0.06, 0.54, 0.34], "rooms": ["dental-room", "exam-room"]},     # generated prop
    "lounge_sofa":    {"src": "proc:VelvetSofaFactory", "size": [0.9, 2.0, 0.8], "rooms": ["open-office", "office"]},            # generated prop
    "toilet":         {"src": "proc:ToiletStallFactory", "size": [1.5, 0.95, 1.95], "rooms": ["restroom"]},   # floor scenes: a cubicle
    "wc":             {"src": "inf:ToiletFactory", "size": [0.7, 0.45, 0.8], "rooms": ["restroom", "bathroom"]},   # a single-user restroom: no cubicle
    "urinal":         {"src": "proc:UrinalFactory", "size": [0.42, 1.6, 1.6], "rooms": ["restroom"]},
    "wash_basin":     {"src": "proc:WashBasinFactory", "size": [0.45, 0.6, 1.9], "rooms": ["restroom"]},
    "vanity":         {"src": "proc:HomeVanityFactory", "size": [0.52, 0.92, 1.9], "rooms": ["bathroom"]},     # home bathroom (P2 r1 FUN-01: empty tiled bathrooms)
    "home_kitchen_run": {"src": "proc:HomeKitchenRunFactory", "size": [0.72, 3.6, 2.4], "rooms": ["kitchen"]},     # hob + sink + base / wall cabinets + fridge in one run (P2 r1: 'kitchen lacks cooker/sink/counters')
    # home balcony set (P2 ref varanda_01): a round white table + four teal chairs
    "balcony_table":   {"src": "proc:BalconyTableFactory", "size": [1.1, 1.1, 0.74], "rooms": ["balcony"]},
    "balcony_chair":   {"src": "proc:BalconyChairFactory", "size": [0.5, 0.5, 0.85], "rooms": ["balcony"]},
    # P2 suite 2: two single beds side by side (ref suite2_01), head against the wall, a 0.45 m bedside gap
    "single_bed":      {"src": "proc:SingleBedFactory", "size": [2.05, 0.95, 1.05], "rooms": ["bedroom"]},
    # P2 gaps (user r17 review): laundry run, island, big fridge, fitted oak wardrobe, curtains, towel rail, media wall
    "laundry_run":     {"src": "proc:LaundryRunFactory", "size": [0.62, 2.8, 2.2], "rooms": ["utility", "laundry"]},
    "prep_table":      {"src": "proc:SteelPrepTableFactory", "size": [0.9, 1.8, 0.95], "rooms": ["kitchen"]},     # floor G/H commercial kitchen: stainless prep island
    "oven_tower":      {"src": "proc:OvenTowerFactory", "size": [0.62, 0.6, 2.1], "rooms": ["kitchen"]},     # P2b kitchen ref: built-in oven + microwave stack
    "kitchen_island":  {"src": "proc:KitchenIslandFactory", "size": [0.9, 1.8, 0.95], "rooms": ["kitchen"]},
    "big_fridge":      {"src": "proc:BigFridgeFactory", "size": [0.75, 0.9, 1.85], "rooms": ["kitchen"]},
    "oak_wardrobe":    {"src": "proc:OakWardrobeFactory", "size": [0.6, 2.4, 2.4], "rooms": ["bedroom", "closet"]},
    "curtain":         {"src": "proc:CurtainFactory", "size": [0.12, 2.4, 2.6], "rooms": ["bedroom", "living-room"]},
    "towel_rail":      {"src": "proc:TowelRailFactory", "size": [0.1, 0.7, 0.55], "rooms": ["bathroom"]},
    "media_wall":      {"src": "proc:MediaWallFactory", "size": [0.4, 3.2, 2.4], "rooms": ["living-room"]},
    "shower_glass":   {"src": "proc:ShowerEnclosureFactory", "size": [0.96, 0.95, 2.1], "rooms": ["bathroom"]},
    "bathtub":        {"src": "inf:BathtubFactory", "size": [0.8, 1.7, 0.6], "rooms": ["bathroom"]},
    "locker":         {"src": "proc:LockerFactory", "size": [0.5, 1.4, 1.8], "rooms": ["closet", "break-room"]},
    "changing_bench": {"src": "proc:ChangingBenchFactory", "size": [0.35, 1.3, 0.47], "rooms": ["closet"]},
    "medical_cabinet": {"src": "proc:MedicalCabinetFactory", "size": [3.0, 0.6, 2.2], "rooms": ["exam-room", "dental-room", "physio-room"]},
    "privacy_curtain": {"src": "proc:PrivacyCurtainFactory", "size": [1.6, 2.2, 2.35], "rooms": ["exam-room", "physio-room"]},
    "dental_chair":   {"src": "proc:DentalChairFactory", "size": [0.9, 1.9, 2.0], "rooms": ["dental-room"]},
    "wall_bars":      {"src": "proc:WallBarsFactory", "size": [0.95, 0.12, 2.4], "rooms": ["physio-room"]},
    "exercise_set":   {"src": "proc:ExerciseSetFactory", "size": [0.7, 2.0, 0.66], "rooms": ["physio-room"]},
    "parallel_bars":  {"src": "proc:ParallelBarsFactory", "size": [0.9, 3.0, 0.95], "rooms": ["physio-room"]},
    "exercise_bike":  {"src": "proc:ExerciseBikeFactory", "size": [0.95, 0.5, 1.1], "rooms": ["physio-room"]},
    "clothing_rack":  {"src": "proc:ClothingRackFactory", "size": [1.6, 0.5, 1.55], "rooms": ["boutique"]},
    "display_table":  {"src": "proc:DisplayTableFactory", "size": [1.4, 0.8, 0.9], "rooms": ["boutique"]},
    "mirror":         {"src": "proc:MirrorFactory", "size": [0.65, 0.3, 1.85], "rooms": ["boutique", "closet"]},
    "fitting_room":   {"src": "proc:FittingRoomFactory", "size": [1.25, 1.1, 2.2], "rooms": ["boutique"]},
    # offices: zones (a set placed as one) and their internal parts
    "workstation_pod": {"src": "zone:workstation_pod", "size": [2.8, 2.4, 1.2], "rooms": ["open-office", "office"]},
    "glass_meeting_room": {"src": "zone:glass_meeting_room", "size": [4.5, 3.5, 2.8], "rooms": ["open-office"]},
    "meeting_set":    {"src": "zone:meeting_set", "size": [4.0, 2.6, 0.75], "rooms": ["meeting-room"]},
    "pantry_run":     {"src": "zone:pantry_run", "size": [3.0, 0.6, 2.2], "rooms": ["break-room", "kitchen"]},
    "pod_unit":       {"src": "proc:WorkstationPodFactory", "size": [2.8, 1.4, 1.2], "rooms": ["_internal"]},
    "pantry_unit":    {"src": "proc:PantryRunFactory", "size": [3.0, 0.6, 2.2], "rooms": ["_internal"]},
    "wall_display":   {"src": "proc:WallDisplayFactory", "size": [1.5, 0.05, 0.9], "rooms": ["_internal"]},
    "whiteboard":     {"src": "proc:WhiteboardFactory", "size": [1.5, 0.05, 1.0], "rooms": ["meeting-room", "office", "open-office", "physio-room"]},
    # flagship boutique (reference set boutique_large_flagship_01): rooms [] keeps them out of the planner vocabulary; realize._fill_boutique
    # places them when ROOM_FLAGSHIP=1
    # underground bookstore (docs/bookstore_underground_design_proposal.md): realize._fill_bookstore places them when ROOM_BOOKSTORE=1
    "book_island":     {"src": "proc:BookIslandTableFactory", "size": [1.0, 2.4, 0.9], "rooms": []},
    "book_wall_shelf": {"src": "proc:BookWallShelfFactory", "size": [0.35, 2.4, 2.4], "rooms": []},
    "section_sign":    {"src": "proc:SectionSignFactory", "size": [0.26, 0.37, 1.3], "rooms": []},
    "stepped_plinth": {"src": "proc:SteppedPlinthFactory", "size": [1.2, 1.8, 0.44], "rooms": []},
    # rooftop fine-dining restaurant (docs/rooftop_fine_dining_design_proposal.md): realize._fill_rooftop places them when ROOM_ROOFTOP=1
    "rt_banquette":   {"src": "proc:CreamBanquetteFactory", "size": [3.0, 0.6, 1.0], "rooms": []},   # cream leather + orange cushions (VLM gap)
    "rt_booth":       {"src": "proc:VelvetBoothFactory", "size": [0.8, 2.2, 1.05], "rooms": []},
    "rt_table_low":   {"src": "proc:MarbleTableLowFactory", "size": [0.7, 1.2, 0.75], "rooms": []},
    "rt_table_high":  {"src": "proc:MarbleTableHighFactory", "size": [0.7, 0.7, 1.05], "rooms": []},
    "rt_table_round": {"src": "proc:MarbleTableRoundFactory", "size": [0.7, 0.7, 1.05], "rooms": []},
    "rt_stool_white": {"src": "proc:BarStoolWhiteFactory", "size": [0.42, 0.42, 1.0], "rooms": []},
    "rt_stool_gold":  {"src": "proc:BarStoolGoldFactory", "size": [0.42, 0.42, 1.0], "rooms": []},
    "rt_ottoman":     {"src": "proc:CubeOttomanFactory", "size": [0.5, 0.5, 0.45], "rooms": []},
    "rt_mirror_column": {"src": "proc:MirrorColumnFactory", "size": [0.7, 0.7, 3.2], "rooms": []},
    "rt_floor_ac":    {"src": "proc:FloorAcFactory", "size": [0.35, 0.5, 1.9], "rooms": []},
    "rt_heater":      {"src": "proc:PatioHeaterFactory", "size": [0.64, 0.64, 2.1], "rooms": []},
    "rt_setting":     {"src": "proc:FineDiningSettingFactory", "size": [0.34, 0.4, 0.17], "rooms": []},
    # underground wine pub (docs/wine_pub_underground_design_proposal.md): realize._fill_winepub places them when ROOM_WINEPUB=1
    "wp_column":      {"src": "proc:MirrorPillarFactory", "size": [0.7, 0.7, 3.2], "rooms": []},
    "wp_table":       {"src": "proc:WhiteMarbleRoundTableFactory", "size": [0.7, 0.7, 0.74], "rooms": []},
    "wp_chair":       {"src": "proc:VelvetShellChairFactory", "size": [0.55, 0.55, 0.8], "rooms": []},
    "wp_bar":         {"src": "proc:BarCounterBlackFactory", "size": [0.68, 3.6, 1.05], "rooms": []},
    "wp_shelf":       {"src": "proc:BottleShelfFactory", "size": [0.4, 1.5, 1.9], "rooms": []},
    "wp_bottle_row":  {"src": "proc:BottleRowFactory", "size": [0.14, 2.4, 0.36], "rooms": []},
    "wp_mirror_wall": {"src": "proc:WrinkledMirrorWallFactory", "size": [0.07, 2.4, 2.3], "rooms": []},
    # warm clinic reception lobby (ROOM_CLINIC_LOBBY=1, venue stays clinic-reception): realize._fill_clinic_lobby places them
    "cl_wood_wall":   {"src": "proc:WoodPanelWallFactory", "size": [0.2, 3.6, 2.5], "rooms": []},
    "cl_desk":        {"src": "proc:OakLouverDeskFactory", "size": [0.9, 3.2, 1.05], "rooms": []},
    "cl_sofa":        {"src": "proc:BeigeSofaFactory", "size": [0.9, 2.0, 0.85], "rooms": []},
    "cl_armchair":    {"src": "proc:OakArmchairFactory", "size": [0.85, 0.8, 0.83], "rooms": []},
    "cl_table":       {"src": "proc:RoundOakCoffeeTableFactory", "size": [1.0, 1.0, 0.43], "rooms": []},
    "cl_rug":         {"src": "proc:JuteRugFactory", "size": [1.7, 2.4, 0.012], "rooms": []},
    "cl_art":         {"src": "proc:FramedBotanicalArtFactory", "size": [0.06, 0.9, 1.2], "rooms": []},
    "rt_timber":      {"src": "proc:TimberColumnFactory", "size": [0.6, 0.6, 3.2], "rooms": []},
    "book_pop":       {"src": "proc:PopStandFactory", "size": [0.5, 0.6, 1.55], "rooms": []},
    "bestseller_table": {"src": "proc:BestsellerTableFactory", "size": [1.0, 2.4, 0.9], "rooms": []},
    "bestseller_sign": {"src": "proc:BestsellerSignFactory", "size": [0.26, 0.37, 1.3], "rooms": []},
    "wall_poster":     {"src": "proc:WallPosterFactory", "size": [0.06, 0.86, 1.2], "rooms": []},
    "fl_wood_wall":   {"src": "proc:FlagshipWoodWallFactory", "size": [0.2, 3.6, 2.5], "rooms": []},
    # science museum (docs/space_museum_design_proposal.md): realize._fill_museum places them when ROOM_MUSEUM=1
    "mu_elements":    {"src": "proc:ElementWallFactory", "size": [0.25, 5.0, 2.8], "rooms": []},
    "mu_bench":       {"src": "proc:MarbleBenchFactory", "size": [0.5, 1.6, 0.46], "rooms": []},
    "mu_rail":        {"src": "proc:RotundaRailFactory", "size": [4.2, 4.2, 1.04], "rooms": []},
    "mu_ring":        {"src": "proc:GlowRingFactory", "size": [3.6, 3.6, 0.04], "rooms": []},
    "mu_pendulum":    {"src": "proc:PendulumFactory", "size": [0.3, 0.3, 6.0], "rooms": []},
    "mu_nebula":      {"src": "proc:NebulaWallPanelFactory", "size": [0.1, 3.3, 2.2], "rooms": []},
    "mu_pic_blue":    {"src": "proc:PictureFrameNebulaBlueFactory", "size": [0.08, 0.7, 0.85], "rooms": []},
    "mu_pic_ring":    {"src": "proc:PictureFrameNebulaRingFactory", "size": [0.08, 0.7, 0.85], "rooms": []},
    "mu_pic_earth":   {"src": "proc:PictureFrameEarthFactory", "size": [0.08, 1.1, 0.72], "rooms": []},
    "stone_table":    {"src": "proc:StoneSlabTableFactory", "size": [2.2, 1.1, 0.78], "rooms": []},
    "wall_rail":      {"src": "proc:WallRailFlatFactory", "size": [3.0, 0.16, 0.1], "rooms": []},
    "lattice_screen": {"src": "proc:SteelLatticeScreenFactory", "size": [1.9, 0.45, 2.6], "rooms": []},
    "wall_gondola":   {"src": "proc:WallGondolaFactory", "size": [1.9, 0.45, 1.5], "rooms": ["grocery", "convenience", "pharmacy", "boutique"]},
    "ceramic_shelf":   {"src": "proc:CeramicBirdShelfFactory", "size": [0.28, 1.8, 1.8], "rooms": ["grocery"]},     # market ref: wall shelves of glazed ceramic birds
    "basket_stack":    {"src": "proc:BasketStackFactory", "size": [0.4, 0.46, 0.7], "rooms": ["grocery"]},     # market ref: blue plastic basket stacks by the entrance
    "bread_display":   {"src": "proc:BreadDisplayFactory", "size": [0.8, 1.6, 0.9], "rooms": ["grocery", "cafe"]},     # market ref: plywood bread table with loaf rows
    # underground parking level (ROOM_MODE=parking, S28)
    "parked_car":      {"src": "proc:ParkedCarFactory", "size": [4.6, 1.85, 1.5], "rooms": []},
    "parking_column":  {"src": "proc:ColumnWithPlateFactory", "size": [0.69, 0.66, 3.0], "rooms": []},
    "traffic_cone":    {"src": "proc:TrafficConeFactory", "size": [0.36, 0.36, 0.7], "rooms": []},
    "bollard":         {"src": "proc:BollardFactory", "size": [0.09, 0.09, 0.9], "rooms": []},
    "wheel_stop":      {"src": "proc:WheelStopFactory", "size": [0.15, 1.6, 0.1], "rooms": []},
    "bay_lines":       {"src": "proc:BayLinesFactory", "size": [5.0, 15.6, 0.005], "rooms": []},
    "floor_arrow":     {"src": "proc:FloorArrowFactory", "size": [1.95, 0.55, 0.005], "rooms": []},
    # university cafeteria (ROOM_MODE=cafeteria, S27)
    "serving_line":    {"src": "proc:ServingLineFactory", "size": [0.82, 6.0, 1.6], "rooms": []},
    "long_oak_table":  {"src": "proc:LongOakTableFactory", "size": [0.9, 3.6, 0.75], "rooms": []},
    "ply_shell_chair": {"src": "proc:PlywoodShellChairFactory", "size": [0.45, 0.47, 0.88], "rooms": []},
    "uv_trap_column":  {"src": "proc:UvTrapColumnFactory", "size": [0.74, 0.7, 3.0], "rooms": []},
    "pharmacy_drawer_wall": {"src": "proc:PharmacyDrawerWallFactory", "size": [0.36, 2.4, 2.3], "rooms": ["pharmacy"]},     # S16 ref: a full-height wall of small drawers
    "pharmacy_counter":     {"src": "proc:PharmacyCounterFactory", "size": [0.79, 5.0, 1.1], "rooms": ["pharmacy"]},      # long dispensing counter: green base band, LED strip, 2 monitors
    # building lounge (ROOM_MODE=lounge, S29): realize._fill_mode places them
    "lp_shelf":        {"src": "proc:LpShelfWallFactory", "size": [0.38, 2.4, 2.3], "rooms": []},
    "red_high_table":  {"src": "proc:RedHighTableFactory", "size": [0.7, 3.0, 1.05], "rooms": []},
    "red_high_table_long": {"src": "proc:RedHighTableLongFactory", "size": [0.7, 4.8, 1.05], "rooms": []},       # S29 reference plan: two long red tables with a row of stools each side
    # tall building lobby (ROOM_MODE=lobby, S30): realize._fill_mode places them
    "leather_bench":   {"src": "proc:LeatherBenchFactory", "size": [0.75, 2.4, 0.45], "rooms": []},
    "display_wall":    {"src": "proc:DisplayWallFactory", "size": [0.08, 5.0, 1.8], "rooms": []},
    "mosaic_panel":    {"src": "proc:MosaicPanelFactory", "size": [0.11, 1.7, 2.6], "rooms": []},
    "revolving_door":  {"src": "proc:RevolvingDoorFactory", "size": [2.8, 2.8, 2.9], "rooms": []},
    "glass_cafe_box":  {"src": "proc:GlassCafeBoxFactory", "size": [4.5, 8.0, 3.6], "rooms": []},
    "wood_stool":      {"src": "proc:WoodStoolFactory", "size": [0.41, 0.41, 0.77], "rooms": []},
    "round_pendant":   {"src": "proc:RoundAmberPendantFactory", "size": [0.4, 0.4, 0.95], "rooms": []},
    "elevator_door":   {"src": "proc:ElevatorDoorFactory", "size": [0.08, 1.5, 2.4], "rooms": []},
    "exit_sign":       {"src": "proc:ExitSignFactory", "size": [0.04, 0.34, 0.18], "rooms": []},
    # office floor (floor O): house-shaped lounge booth and paper bunting
    "house_booth":     {"src": "proc:HouseBoothFactory", "size": [1.1, 1.9, 1.75], "rooms": ["break-room"]},
    "bunting":         {"src": "proc:BuntingFactory", "size": [0.02, 3.0, 0.22], "rooms": []},
    "diamond_pendant": {"src": "proc:DiamondPendantFactory", "size": [0.34, 0.34, 1.2], "rooms": []},
    "cooler_wall":     {"src": "proc:CoolerWallFactory", "size": [0.78, 4.4, 2.45], "rooms": ["grocery", "convenience", "pharmacy"]},     # S13 ref: a continuous wall of glass-door coolers with category signs
    "pegboard_endcap": {"src": "proc:PegboardEndcapFactory", "size": [0.5, 0.9, 1.7], "rooms": ["grocery", "convenience", "pharmacy"]},
    "category_sign":   {"src": "proc:CategorySignFactory", "size": [0.04, 1.22, 0.32], "rooms": []},
    "gas_rack":        {"src": "proc:GasCylinderRackFactory", "size": [0.7, 1.2, 1.4], "rooms": ["hallway", "utility", "office"]},         # lab corridor (floor N)
    "lab_cabinet":    {"src": "proc:LabCabinetFactory", "size": [0.55, 1.2, 2.1], "rooms": []},       # N r3: dense lab cabinets along the corridor
    "gas_cart":       {"src": "proc:GasCylinderCartFactory", "size": [0.66, 0.92, 1.4], "rooms": []},
    "door_sign":      {"src": "proc:DoorSafetySignFactory", "size": [0.02, 0.32, 0.46], "rooms": []},
    "lab_chamber":     {"src": "proc:LabChamberFactory", "size": [0.8, 1.2, 2.0], "rooms": ["hallway", "utility", "office"]},
    "fire_ext":        {"src": "proc:FireExtinguisherFactory", "size": [0.2, 0.16, 0.5], "rooms": ["hallway", "utility", "break-room"]},
    "vending_machine": {"src": "proc:VendingMachineFactory", "size": [0.8, 0.9, 1.85], "rooms": ["break-room", "hallway"]},
    "water_dispenser": {"src": "proc:WaterDispenserFactory", "size": [0.36, 0.34, 1.05], "rooms": ["break-room", "hallway"]},
    "crate_stack":     {"src": "proc:CrateStackFactory", "size": [0.4, 0.6, 0.75], "rooms": []},     # market stockroom clutter (kit small_room_extras)
    "mop_bucket":      {"src": "proc:MopBucketFactory", "size": [0.5, 0.3, 1.25], "rooms": []},
    "bus_cart":        {"src": "proc:BusCartFactory", "size": [0.5, 0.8, 0.95], "rooms": []},
    "chest_freezer":  {"src": "proc:ChestFreezerFactory", "size": [1.6, 0.8, 0.85], "rooms": ["grocery", "convenience"]},
    "cafe_chair":     {"src": "abo:cafechair",   "size": [0.45, 0.5, 0.85], "rooms": ["cafe", "office", "break-room"]},
    "bar_stool":      {"src": "abo:barstool",    "size": [0.4, 0.4, 0.75], "rooms": ["cafe", "break-room"]},
    "beverage_fridge": {"src": "proc:DisplayCoolerFactory", "size": [0.75, 0.7, 2.0], "rooms": ["grocery", "convenience", "pharmacy"]},   # not cafe: the inf fridge rendered as a black box (floor H r4, 3 of 3)
}

#: room types that are workplaces: their planner prompt and vocabulary differ from a home's
WORK_ROOMS = {"warehouse", "garage", "utility", "office", "open-office", "meeting-room", "break-room", "factory-office", "cafe",
              "grocery", "clinic-reception", "exam-room", "dental-room", "physio-room", "convenience", "boutique", "pharmacy"}

#: small things that show someone lives here, placed on/at furniture
LIVED_IN = {
    "throw_blanket":   {"src": "inf:BlanketFactory", "on": ["sofa", "armchair", "bed"], "rooms": ["home"]},
    "cushion":         {"src": "abo:PILLOW", "on": ["sofa", "armchair", "bed", "floor"], "rooms": ["home"]},
    "book_stack":      {"src": "inf:BookStackFactory", "on": ["coffee_table", "side_table", "nightstand", "desk", "office_bookcase"], "rooms": ["home", "office", "open-office", "clinic-reception"]},
    "mug":             {"src": "inf:CupFactory", "on": ["coffee_table", "side_table", "nightstand", "desk", "dining_table", "reception_desk"], "rooms": ["home", "office", "open-office", "meeting-room", "break-room", "cafe", "clinic-reception", "exam-room", "pharmacy", "dental-room"]},
    "fruit_bowl":      {"src": "inf:FruitContainerFactory", "on": ["dining_table", "coffee_table", "counter"], "rooms": ["home", "break-room", "cafe"]},
    "table_lamp":      {"src": "abo:TABLE_LAMP", "on": ["side_table", "nightstand", "desk", "sideboard"], "rooms": ["home", "office"]},
    "vase":            {"src": "abo:VASE", "on": ["coffee_table", "sideboard", "dresser", "dining_table"], "rooms": ["home", "cafe"]},
    "small_plant":     {"src": "abo:PLANTER", "on": ["side_table", "sideboard", "desk", "dresser", "floor", "cafe_table"], "rooms": ["home", "office", "open-office", "meeting-room", "break-room", "cafe", "clinic-reception", "boutique", "restroom"]},
    "storage_box":     {"src": "abo:BOX", "on": ["floor", "bookshelf", "dresser"], "rooms": ["home"]},
    "draped_clothes":  {"src": "inf:ShirtFactory", "on": ["bed", "sofa"]},     # not armchair / chair / floor: the shirt hung in mid-air in front of the armchair (P2 r1 LAY-02)
    "pants":           {"src": "inf:PantsFactory", "on": ["bed", "armchair", "sofa", "floor"]},
    "towel":           {"src": "inf:TowelFactory", "on": ["bed", "floor", "armchair"]},
    "open_book":       {"src": "inf:BookFactory", "on": ["sofa", "armchair", "bed", "coffee_table", "side_table", "nightstand", "floor"], "rooms": ["home", "office", "open-office", "break-room"]},
    "laundry_basket":  {"src": "inf:BasketBaseFactory", "on": ["floor"]},
    # workplaces ("rooms": only offered there)
    "autoclave":       {"src": "proc:AutoclaveFactory", "on": ["medical_cabinet"], "rooms": ["utility"]},
    "bag":             {"src": "proc:BagFactory", "on": ["floor", "changing_bench"], "rooms": ["office", "open-office", "meeting-room", "break-room",
                        "clinic-reception", "exam-room", "dental-room", "physio-room", "closet", "warehouse", "kitchen", "cafe", "pharmacy"]},
    "cafe_stock":      {"src": "proc:CafeStockFactory", "on": ["stock_shelf", "storage_rack", "floor"], "rooms": ["utility", "warehouse"]},
    "dry_goods":       {"src": "proc:DryGoodsFactory", "on": ["stock_shelf", "storage_rack", "supply_shelf", "floor"], "rooms": ["warehouse", "utility"]},
    "cardboard_box":   {"src": "proc:CardboardBoxFactory", "on": ["storage_rack", "wide_shelf", "pallet", "workbench", "floor", "supply_shelf", "stock_shelf"],
                        "rooms": ["warehouse", "garage", "utility", "grocery"]},
    "storage_bin":     {"src": "abo:BOX", "on": ["storage_rack", "wide_shelf", "workbench", "floor", "supply_shelf"], "rooms": ["warehouse", "garage", "utility"]},
    "bottle":          {"src": "inf:BottleFactory", "on": ["workbench", "storage_rack"], "rooms": ["warehouse", "garage", "cafe", "grocery", "convenience", "pharmacy", "exam-room", "dental-room"]},
    "can":             {"src": "inf:CanFactory", "on": ["workbench", "storage_rack"], "rooms": ["warehouse", "garage"]},
    "monitor":         {"src": "inf:MonitorFactory", "on": ["desk", "office_desk", "reception_desk", "workbench"], "rooms": ["office", "open-office", "exam-room", "dental-room", "clinic-reception", "pharmacy", "warehouse"]},
    "speakerphone":    {"src": "proc:SpeakerphoneFactory", "on": ["meeting_table"], "rooms": ["meeting-room"]},
    "microwave":       {"src": "inf:MicrowaveFactory", "on": ["pantry_run"], "rooms": ["break-room"]},
    "plate":           {"src": "inf:PlateFactory", "on": ["cafe_table", "counter", "window_bar"], "rooms": ["cafe"]},
    "espresso_machine": {"src": "proc:EspressoMachineFactory", "on": ["counter"], "rooms": ["cafe", "convenience", "office", "break-room"]},
    "grinder":         {"src": "proc:GrinderFactory", "on": ["counter"], "rooms": ["cafe"]},
    "cup_stack":       {"src": "proc:CupStackFactory", "on": ["counter", "backbar_shelf"], "rooms": ["cafe"]},
    "pastry_case":     {"src": "proc:PastryCaseFactory", "on": ["counter"], "rooms": ["cafe", "grocery"]},
    "syrup_rack":      {"src": "proc:SyrupRackFactory", "on": ["counter"], "rooms": ["cafe"]},
    "cake_dome":       {"src": "proc:CakeDomeFactory", "on": ["counter", "cafe_table"], "rooms": ["cafe"]},
    "backbar_stock":   {"src": "inf:BottleFactory", "on": ["backbar_shelf"], "rooms": ["cafe"]},
    "wine_glass":      {"src": "inf:WineglassFactory", "on": ["cafe_table", "counter"], "rooms": ["cafe"]},
    "groceries":       {"src": "inf:FoodBoxFactory", "on": ["gondola", "wall_gondola", "counter"], "rooms": ["grocery", "convenience", "pharmacy"]},
    "basket":          {"src": "inf:BasketBaseFactory", "on": ["counter"], "rooms": ["grocery", "convenience", "pharmacy", "cafe"]},   # not floor: loose baskets in the queue path read as dropped (floor I r14, 3 of 3)
    "ramen_set":       {"src": "proc:RamenSeatSetFactory", "on": ["counter"], "rooms": ["cafe"]},      # S32: condiment jars, chopstick cup, tissue box, small bowl at a counter seat
    "register":        {"src": "proc:RegisterFactory", "on": ["counter"], "rooms": ["grocery", "cafe", "convenience", "boutique", "pharmacy"]},
    # desk clutter (user 2026-10-16: offices looked untouched -- leftover snacks, books, pencils, cups)
    "bud_vase":        {"src": "proc:BudVaseFactory", "on": ["cafe_table", "counter", "window_bar"], "rooms": ["cafe"]},
    "candle":          {"src": "proc:TableCandleFactory", "on": ["cafe_table", "counter", "window_bar"], "rooms": ["cafe"]},      # generated prop (decor "candles")
    "flower_arrangement": {"src": "proc:FlowerArrangementFactory", "on": ["counter"], "rooms": ["cafe"]},
    "drink_cans":      {"src": "proc:DrinkCansFactory", "on": ["pantry_run", "break_table", "counter"], "rooms": ["break-room", "convenience"]},
    "snack_basket":    {"src": "proc:SnackBasketFactory", "on": ["pantry_run", "break_table"], "rooms": ["break-room"]},
    "open_laptop":     {"src": "proc:OpenLaptopFactory", "on": ["desk", "office_desk", "meeting_table", "reception_desk"], "rooms": ["office", "open-office", "meeting-room"]},     # generated props (data/venue_refs/generated_props)
    "lanyard":         {"src": "proc:LanyardFactory", "on": ["desk", "office_desk", "meeting_table", "reception_desk"], "rooms": ["office", "open-office", "meeting-room"]},
    "desk_plant":      {"src": "proc:DeskPlantFactory", "on": ["desk", "office_desk", "meeting_table", "reception_desk"], "rooms": ["office", "open-office", "meeting-room"]},
    "pen_cup":         {"src": "proc:PenCupFactory", "on": ["desk", "office_desk", "meeting_table", "reception_desk"], "rooms": ["office", "open-office", "meeting-room", "clinic-reception", "exam-room", "pharmacy", "dental-room"]},
    "takeaway_cup":    {"src": "proc:TakeawayCupFactory", "on": ["desk", "office_desk", "meeting_table", "break_table", "counter", "reception_desk"], "rooms": ["office", "open-office", "meeting-room", "break-room", "cafe", "clinic-reception"]},
    "snack":           {"src": "proc:SnackFactory", "on": ["desk", "office_desk", "meeting_table", "break_table"], "rooms": ["office", "open-office", "meeting-room", "break-room"]},
    "phone":           {"src": "proc:PhoneFactory", "on": ["desk", "office_desk", "meeting_table", "break_table", "cafe_table", "reception_desk"], "rooms": ["office", "open-office", "meeting-room", "break-room", "cafe", "clinic-reception", "pharmacy", "boutique", "convenience"]},
    "notebook":        {"src": "proc:NotebookFactory", "on": ["desk", "office_desk", "meeting_table", "reception_desk"], "rooms": ["office", "open-office", "meeting-room", "clinic-reception", "exam-room", "dental-room"]},
    "open_box":        {"src": "proc:OpenBoxFactory", "on": ["workbench"], "rooms": ["warehouse", "garage"]},
    "shipping_scale":  {"src": "proc:ShippingScaleFactory", "on": ["workbench"], "rooms": ["warehouse", "garage"]},     # generated prop (packing bench: a scale, like the J ref)
    "tape_gun":        {"src": "proc:TapeGunFactory", "on": ["workbench"], "rooms": ["warehouse", "garage"]},
    "kraft_roll":      {"src": "proc:KraftRollFactory", "on": ["workbench"], "rooms": ["warehouse", "garage"]},
    "towel_stack":     {"src": "proc:FoldedLinenStackFactory", "on": ["exam_table", "changing_bench", "supply_shelf", "storage_rack"], "rooms": ["physio-room", "exam-room", "closet", "utility"]},
    # clinical counter / desk props (clinic r6 critic: 'no glove boxes, sanitizer or trays -- an unfurnished showroom')
    "glove_box":       {"src": "proc:GloveBoxFactory", "on": ["medical_cabinet", "clinic_desk", "reception_desk"], "rooms": ["clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy", "utility"]},
    "sanitizer":       {"src": "proc:SanitizerFactory", "on": ["medical_cabinet", "clinic_desk", "reception_desk", "counter", "wash_basin"], "rooms": ["clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy"]},
    "paper_towel":     {"src": "proc:PaperTowelFactory", "on": ["medical_cabinet"], "rooms": ["clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy"]},
    "clipboard":       {"src": "proc:ClipboardFactory", "on": ["medical_cabinet", "clinic_desk", "reception_desk", "exam_table"], "rooms": ["clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy"]},
    "kidney_tray":     {"src": "proc:KidneyTrayFactory", "on": ["medical_cabinet", "clinic_desk"], "rooms": ["exam-room", "dental-room"]},
    "paper_stack":     {"src": "proc:PaperStackFactory", "on": ["desk", "meeting_table", "filing_cabinet", "reception_desk"], "rooms": ["office", "open-office", "meeting-room", "clinic-reception", "exam-room", "dental-room", "pharmacy"]},
}

RELATIONS = {
    "against_wall": "back against wall `wall` (a wall id from the room, or 'longest_free'); `facing` defaults to the room",
    "in_front_of": "in front of `target` at `gap_m` (coffee table 0.4-0.5 m before a sofa)",
    "behind": "on the far side of `target`, facing it (the staff chair behind a reception desk or counter)",
    "beside": "next to `target` on `side` (left|right|both), touching distance",
    "around": "spread around `target` (dining chairs around a table), `count` of them",
    "facing": "turned to face `target` (armchair facing the sofa, sofa facing the TV)",
    "under": "under `target` (a rug under the coffee table / bed foot)",
    "corner": "in a free corner",
    "near_window": "within 1 m of a window",
    "row": "`count` of them side by side along wall `wall`, `gap_m` from it (0 = against it; 2-3 m = a free-standing aisle row "
           "parallel to that wall); `facing` 'away' (default) or 'toward' the wall",
}

#: how a piece of furniture stands: square to its wall/target, turned a little, or (chairs) pulled out from the table/desk
FURNITURE_POSES = {"aligned": "square, as placed", "angled": "turned 8-20 deg off square", "pulled_out": "moved 0.15-0.35 m back from its target and turned 10-25 deg"}

#: how a small item lies: upright where it belongs, or the way people leave things
ITEM_POSES = {"placed": "upright, where it belongs", "lying": "on its side / flat (a single book, a bottle on its side)",
              "tossed": "dropped carelessly and settled by physics (cushion against the backrest, clothes on the bed, a book on the sofa)",
              "leaning": "leaning against the host's back or a wall (cushion, book)"}
