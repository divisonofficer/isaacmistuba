# IR Infinigen unrecoverable-output retirement — 2026-08-26

This inventory records the generated Infinigen `full/` outputs removed after
cross-checking all active and archived controller job snapshots. No running or
queued job referenced any of these source outputs at deletion time.

- Unique output directories: 25
- Total removed bytes: 26,556,409,244 (26.556 GB / 24.733 GiB)
- Job records that led to the set: 27 (duplicate references collapsed)
- Source root: `/jarvis/project/robomituba/data/infinigen_generated/outputs`
- Removal policy: quality/content-gate failures only; technical/retryable
  failures were retained.

## Removed outputs

```text
kr_03305432_single_room_open_office/full
kr_05518497_single_room_staircase_room/full
kr_05989289_single_room_meeting_room/full
kr_07399359_single_room_meeting_room/full
kr_11834066_single_room_restroom/full
kr_14722981_single_room_office/full
kr_18453015_single_room_restroom/full
kr_27924112_single_room_living_room/full
kr_29678771_single_room_break_room/full
kr_30865546_single_room_bathroom/full
kr_32038334_single_room_break_room/full
kr_37148354_single_room_dining_room/full
kr_38574116_single_room_open_office/full
kr_40645563_single_room_meeting_room/full
kr_53404293_single_room_meeting_room/full
kr_53503100_single_room_restroom/full
kr_56413750_single_room_warehouse/full
kr_68505893_single_room_warehouse/full
kr_72453212_single_room_break_room/full
kr_76164143_single_room_warehouse/full
kr_85445914_single_room_meeting_room/full
kr_92245573_single_room_meeting_room/full
kr_95364321_single_room_living_room/full
kr_96631359_single_room_open_office/full
kr_97909093_single_room_garage/full
```

Controller job snapshots and event logs were retained.
