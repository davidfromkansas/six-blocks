# Visual References

Six Blocks' look is inspired by real NYC streetscapes and by late-1990s/2000s 2D
management games, but every asset is generated procedurally with p5.js — no
photographs, no copyrighted game art, no traced sprites.

## Reference sources (publicly viewable)

- NYC Street Design Manual — https://www.nycstreetdesign.info/
  (street/sidewalk/crosswalk geometry, bike lane and pedestrian plaza treatments)
- NYC DOT public plaza & open streets program pages — https://www.nyc.gov/html/dot/html/pedestrians/nyc-plaza-program.shtml
- NYC Planning MapPLUTO documentation — https://www.nyc.gov/site/planning/data-maps/open-data/dwn-pluto-mappluto.page
  (block/lot structure, building footprints and floor counts)
- MTA subway entrance imagery & signage guidelines — https://new.mta.info/
  (the green-globe subway entrance, "M" signage abstraction)
- Wikipedia Commons categories for NYC streetscapes (freely licensed):
  water towers, fire hydrants, brownstone stoops, bodega awnings.
- Genre references (studied for feel only, nothing copied): classic top-down
  city/management games of the late 90s — dense small maps, warm palettes,
  readable at a glance, one-screen neighborhoods.

## Common characteristics observed

- NYC blocks are dense rectangles ringed by sidewalks; storefronts face the street
  with colored awnings; roofs carry water tanks and parapets.
- Street furniture is everywhere: hydrants (red/silver), lamp posts, street trees in
  pits, bus shelters, green subway entrances.
- Crosswalks are wide white ladder stripes; bike lanes are green painted strips.
- Life reads through motion: pedestrians, yellow cabs, buses.

## How Six Blocks represents them

- Top-down 2D view, six dense rectangular blocks with sidewalk aprons and ladder
  crosswalks at corners.
- Buildings as roof-view rectangles: facade hue per building, parapet strip,
  skylight/window grids scaled to floor count, water tanks on taller buildings,
  striped awnings on storefront frontages, flags on civic buildings.
- Green painted bike lanes, blue bus shelters, green "M" subway entrances.
- Pedestrians as seeded walking figures (mode-aware: cyclists get wheels), yellow
  cabs and blue buses circulating on the street grid.
- Event dressing: heat shimmer tint, flood water sheets, construction barriers,
  festival bunting, trash bag piles, blackout dimming.

## What Six Blocks deliberately omits

- Real place names, landmarks, or recognizable buildings (block names are invented).
- Photorealism, textures, or licensed imagery of any kind.
- Traffic simulation fidelity (vehicles are ambience, not agents).
- Interiors, weather beyond event dressing, day/night cycle.

## p5.js abstraction rules

1. Everything is drawn from primitives (rects, circles, triangles, lines).
2. All variation is seeded (mulberry32 on `seed + entity id`): the same seed renders
   the same city, live and in replay.
3. Palette lives in one place (`generate-assets` emits `generated/palette.json`).
4. The renderer never mutates simulation state; it only reads world + frame payloads.
