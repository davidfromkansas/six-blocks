# Simulation References

CitySim is a game, not a forecasting model — but its causal structure is grounded
in public research and city data so the trade-offs feel real.

## Reference sources

- NYC Housing and Vacancy Survey — https://www.nyc.gov/site/hpd/about/research.page
  (rent burden distributions; the ~30% "rent-burdened" and ~50% "severely burdened"
  thresholds used qualitatively)
- ACS / NYC Planning population profiles — https://www.nyc.gov/site/planning/data-maps/nyc-population.page
  (household sizes, age mix, commute mode shares for outer-borough neighborhoods)
- NYC heat mortality reports (NYC DOHMH) — https://www.nyc.gov/site/doh/data/data-publications/heat-reports.page
  (heat vulnerability: age, health, access to cooling; cooling centers as mitigation)
- MTA ridership & service data — https://new.mta.info/agency/new-york-city-transit
  (subway dependency, bus frequency effects on commute experience)
- NYC DSNY cleanliness scorecards — https://www.nyc.gov/site/dsny/index.page
  (trash service levels, backlog dynamics)
- Urban displacement literature (Urban Displacement Project) — https://www.urbandisplacement.org/
  (rent shocks → displacement risk; equity framing)
- Small business survival studies (SBS/JPMC Institute) — qualitative basis for
  storefront sensitivity to foot traffic and local disposable income.

## How CitySim represents them

- **Rent burden** = rent ÷ income per household, with mood/displacement pressure
  rising steeply past qualitative burden thresholds.
- **Mode-specific mobility**: each resident has a commute mode; service changes
  affect only the residents who actually use that mode.
- **Heat vulnerability** compounds age, health, and lack of nearby cooling; cooling
  centers cut exposure for that block.
- **Cleanliness** decays without service, compounds during backlogs, and feeds
  perceived safety and business foot traffic.
- **Displacement** is permanent within an episode and scored under equity.
- **Business health** follows local spending power and foot traffic, with grants as
  a short-term bridge.

## What CitySim deliberately omits

- Real dollar calibration (costs/rents are game-scaled, not budget-accurate).
- Crime modeling (only "perceived safety" as a service-level abstraction).
- Schools, taxation, zoning law, political process.
- Migration into the neighborhood at census fidelity (arrivals are abstracted).
- Any claim of predictive validity — the numbers are tuned for meaningful play.
