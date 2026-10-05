# Landmark data sources

The app uses factual landmark names and approximate map coordinates from the following sources, checked 8 September 2026. It does not reproduce their maps or prose.

- [Destructoid: fast-travel locations](https://www.destructoid.com/where-to-find-all-the-fast-travel-points-in-palworld/) — 30 selected landmarks on the original islands. Original guide published February 2024; these are not a complete current map.
- [Palworld Database: Sakurajima](https://www.palworld-db.com/guides/how-to-find-sakurajima-island) — seven fast-travel landmarks.
- [Palworld Database: Feybreak](https://palworld-db.com/guides/how-to-get-to-feybreak) — 24 fast-travel landmarks.
- [Official REST player schema](https://docs.palworldgame.com/api/rest-api/players/) — location_x and location_y fields.

Labels are local nearest-landmark estimates within 120 map units. They do not establish region boundaries, dungeon identity, altitude, realm or travel distance. REST world coordinates are converted to the Palpagos map grid before lookup; custom locations use map coordinates. World Tree is a separate coordinate space and is not matched to these landmarks. The newest areas and unlisted locations may return Unknown area. Custom names can extend the catalogue and take precedence within their configured radius. Raw REST coordinates remain visible.
