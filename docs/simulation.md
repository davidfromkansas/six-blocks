# Six Blocks — Simulation

Deterministic by seed: all randomness comes from a seeded PRNG; the same seed produces
the same neighborhood, the same event schedule, and — with the same actions — the same
trajectory, score, and replay. (This document explains the causal systems, not the
exact constants; discovering good management is the benchmark.)

## The neighborhood

Six blocks in a 3×2 grid, each with its own character: housing stock, storefronts,
civic buildings, open space, a subway entrance on some blocks, and distinct starting
conditions (some blocks start cleaner, better-connected, or more affordable than
others). About 100 residents live in households with real rents and incomes; roughly
two dozen buildings hold homes, businesses, clinics, and parks.

## Residents

Residents are the fundamental unit. Each day every resident:

- **Commutes** by subway, bus, bike, or foot. Their mobility depends on the modes
  available to *them* — bus riders care about bus frequency, subway riders about
  subway reliability, cyclists about bike capacity, walkers about walkability.
- **Uses services**: sanitation, healthcare, parks and playgrounds, food access,
  street lighting. Access shortfalls drag on mood and health.
- **Pays rent**. Rent burden (rent ÷ income) drives displacement risk; sustained high
  burden can push a household out of the neighborhood, permanently.
- **Feels events**: a heat wave hurts the heat-vulnerable most (age, health, no
  nearby cooling); a subway disruption hurts subway commuters most.

Mood, health, and welfare are aggregates over these individual residents.

## Businesses

Each business responds to local disposable income, foot traffic, accessibility,
and events. Struggling businesses can close (permanently, unless something reopens
the space); thriving blocks attract more spending. Business grants and community
events push traffic and revenue in the short term; structural improvements
(cleanliness, safety, pedestrianization) push them durably.

## Interventions

Twelve block-targeted interventions with upfront costs and (mostly) daily upkeep.
Effects are causal, not cosmetic: bus service helps bus commuters' actual commute;
trash pickup raises cleanliness, which feeds perceived safety and foot traffic;
rent relief lowers displacement risk for that block's households. Second-order
consequences matter — pedestrianizing a street helps walkers and storefronts but
slows drivers; over-spending early can leave you unable to respond to a late crisis
(upkeep is charged every day).

## Events

Ten seeded event kinds: `heat_wave`, `subway_disruption`, `trash_backlog`,
`flash_flood`, `street_construction`, `rent_spike`, `business_closure`,
`street_festival`, `power_outage`, `new_development`. Events are scheduled by the
seed, target specific blocks or the whole neighborhood, last multiple days, and
interact with resident vulnerability and your interventions (cooling centers blunt
heat waves; extra trash pickup digs out of a backlog faster).

## The day loop

Dashboard → inspections → up to three interventions → `end_day` → resident routines →
mobility → businesses → housing/economy → events → aggregate metrics → replay frame →
next day. After day 30: results artifact, replay artifact, episode end.
