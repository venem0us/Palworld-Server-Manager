# Live map setup

The live REST API supplies Unreal-world positions, not the small numbers shown in the in-game map. Version 0.2.7 converts Palpagos positions before plotting or resolving landmark names. Players X/Y remain raw; tooltips include map coordinates.

## Full map image

- [Download the full-world PNG](https://raw.githubusercontent.com/voidpossum/PalMap/main/app/data/T_WorldMap.png) (8192 px, approximately 27 MB).
- [Source repository](https://github.com/voidpossum/PalMap).
- [Source calibration documentation](https://github.com/voidpossum/PalMap/blob/main/docs/TECHNICAL.md).

This is a community-hosted copy of the game map texture, not an original map licensed by this app. It is not bundled in the executable. A clear license covering redistribution of the artwork was not found. The link is provided for selecting your own local map image.

1. Download the full PNG from the link above.
2. Open **Live map → Map image & calibration**.
3. Browse to the downloaded PNG.
4. Click **Use full PalMap PNG bounds**. This selects REST world-coordinate conversion, fills the documented full-texture bounds and clears axis swaps/flips.
5. Save. The next player refresh will update the dots.

For a screenshot or differently cropped image, calibrate its actual edges instead. The preset only matches the linked full texture. World Tree is a separate map and is not included in this display. No server restart is needed. If your Ubuntu worker generates Discord PNGs, publish its updated code and map settings again.

## Coordinate facts

Palpagos map X = (REST Y - 158000) / 459.
Palpagos map Y = (REST X + 123888) / 459.

The full image's world bounds are X [-1099401, 349385], Y [-724397, 724389]. The preset converts these into map-coordinate bounds. These constants are documented by the source project's calibration work; arbitrary image crops still need separate calibration.
