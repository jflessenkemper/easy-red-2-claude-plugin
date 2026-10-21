# Easy Red 2 map and mission file formats

What is programmatically writable, what is not, and what is still unknown. Established by reading
the real files on 2026-09-17; every claim here is from a file on disk, not from documentation.

Custom maps live in
`~/.config/unity3d/Corvostudio/Easy Red 2/map_editor/<Map Name>/`
and missions in
`~/.config/unity3d/Corvostudio/Easy Red 2/mission_editor/ME_<name>_<id>/`.

## The editor is TWO editors

Main menu → **Mission Editor** opens a hub with **MAP EDITOR** (left) and **MISSION EDITOR**
(right). The plugin's `er2_play_mission` has only ever driven the right-hand one, which is why the
map tools went unexamined for so long. Map Editor then offers **Edit Map** / **Create Map**.

## Writable: map props — `tx_data_objects.er2f`

**Plain ASCII.** Records separated by a blank line:

```
id: Trench 1
pos: -32.78476;1.00531;50.52933
rot: 0;9.213078;0
```

Semicolon-separated `x;y;z`, rotation in the same order. This is directly authorable from a script,
which makes a purpose-built cover/obstacle layout possible without touching the editor UI.

### The id vocabulary comes from the editor's prop palette

**Scene → Add Prop** opens a searchable palette, read on screen 2026-09-18. It has a `Search...` box
(~1072,144), six category tabs down the left — **props, buildings, environment, streets, terrain,
deprecated** — and a red **CANCEL** at ~(696,1001) which closes it without placing anything.

**The ids are the displayed labels verbatim**, which is consistent with `Trench 1` in the file on
disk. Entries read directly off the first page of `props`:

`Ammo Crate`, `Ammunition Refill Box`, `Ardennes Sign Bastogne` (also `Doncherry`, `Flamierge`,
`Foy`, `Margeret`, `Marvie`, `Noville`, `Sedan`, `Stonne`), `Armchair Fancy`, `Barbed Wire Double`,
`Barbed Wire Double Long`, `Barbed Wire Single`, `Barbed Wire Single Long`, `Barrel Oil Drum`,
`Barrel Wood`.

So the palette — not the asset bundle — is the practical way to enumerate ids: search a term, read
the labels, then CANCEL. The list is alphabetical, so the categories plus the search box beat
scrolling. **The rest of the vocabulary is still unharvested**; the cover props an AI test level
needs (sandbags, low walls, hedges) have not been read yet, and the `terrain` category is unexamined.

Two ids are additionally confirmed from files:

| id | namespace | seen in |
|---|---|---|
| `Trench 1` | map editor | the test map's own `tx_data_objects.er2f` |
| `WoodenBunker` | **mission** `placed_objects` | Stonne's `.mer2` |

Those are **different namespaces** — do not assume an id from one works in the other.

Prop prefabs live in `StreamingAssets/CorvoBundles/er2maps_placedprops` (185 MB, `UnityFS`
2022.3.62f3). It contains per-map scenes including **`CustomTerrain_placedProps`**, which is the one
custom maps use — but the prop names sit inside LZ4-compressed blocks, so `strings` does not see
them (`Trench 1` returns zero hits). Enumerating them needs either a Unity bundle extractor
(UnityPy is **not** installed) or reading the editor's own prop palette in game.

**Never guess an id.** An invalid prop is likely to fail silently, which is the worst outcome.

**Generator:** `er2-realistic/tools/gen_prop_layout.py` builds this file from a role-based layout
and `er2-realistic/data/props/palette.json`, where every id carries a status (`confirmed`,
`palette-read`, `unconfirmed`). Default output is confirmed ids only (today: `Trench 1`). Add a
harvested label to the palette as `palette-read`, and promote it to `confirmed` only after a
generated file loads it in the editor.

## Not safely writable: the mission — `.mer2`

.NET **BinaryFormatter** stream (`MissionEditorBattleData.MissionEditorBattle`). Readable with
`strings`/`xxd`; decoded structure for the test map:

| list | size |
|---|---|
| `vphases` | 1 |
| `unit_spawns` | 2 (both `spawnType` enum **4**, both live) |
| `vehicle_spawns` | 0 |
| `conquer_areas` | 1 |
| `placed_objects` | 0 |
| `neededDLCs` | 1 |
| `customSquads` | 1 (`Elite SS Squad`) |

Battle settings that matter: `maxAllies` / `maxAxis` (**10** on the test map, **70** on Stonne and
VirtualScene), `ignoreOverrideMaxUnits`, `invadersTickets`, `location_name`.

**Prefer never patching this.** `setFactionBudget(faction, budget)` is a *scripted* way to raise
capacity — probed working 2026-09-17, `getFactionBudget` returned the value set. Note also that
`getSettingMaxAllies()` / `getSettingMaxAxis()` read the **player's own client preference**, which
was also 10 — so a low cast size may not be the mission's fault at all.

If a patch is unavoidable: back up first, locate the `int32` by its neighbouring field-name string,
patch in place with **unchanged byte length**, never re-serialise, and verify by re-decoding AND by
opening the mission. If the decode is ambiguous, stop.

## Unknown: terrain — `tx_data_heightmap.er2b` and friends

`custom_map.er2m` (`CustomMapData`) is BinaryFormatter and holds `size_x`, `size_y`, `yPosition`,
`terrainScaleMultiplier`, `terrain_palette` and the layer list. The test map reads
`size_x = size_y = 500`, `yPosition = -10.0`, `terrainScaleMultiplier = 0.5`.

**Caution: 500 has not been confirmed to mean 500 metres.** A centred 600 m grid built and streamed
87 soldiers on this map, which a strict ±250 m bound would not obviously allow — so either the
scale multiplier changes the world extent or the terrain extends past the authored area. Measure
before relying on it.

Sibling binaries, all unexamined: `tx_data_heightmap.er2b` (7316 B), `tx_data_smap.er2b`,
`tx_data_grassmap.er2b`, `tx_data_roads.er2b`, `tx_data_road_profiles.er2b`,
`tx_data_holesmap.er2b`. **Writing elevation is not yet possible** — the encoding is uncracked. That
matters because the repo's own notes record the range as flat desert and that "a test map with no
slope cannot test terrain-sensitive movement".

## DLC gating bites custom maps

The test map's **mission** requires one DLC (`neededDLCs = [DLC 5]`, surfaced in the UI as
`Needs DLCs: Hungary`) while its **map** requires none (`custom_map.er2m` `neededDLCs` size 0). The
requirement comes from mission *content* — the `Elite SS Squad` / `ger_ss_pzgr_1945_win_AT` spawner.
Consequence: a direct-launched game has no entitlement, so the mission row goes inert and will not
open. Use `er2_launch {"via_steam": true}` for it, or replace that squad to un-gate the mission.

## See also

- `/er2-review` — record-and-scrub AI review, which needs no custom map at all
- `docs/ui-map.md` — verified editor UI coordinates
