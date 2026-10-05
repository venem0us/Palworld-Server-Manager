# Expedition recovery

Open **Save repair → Scan world save**. Scanning reads a copy through SSH while the game continues running. Choose the player, select the desired Pals (or use **Select recoverable Pals**), then choose **Recover selected Pals**.

This release supports native PlM1 Level.sav files with the tested Palworld 1.0 character layout. It is a targeted repair, not a general inventory or character editor. Existing expedition buildings, unknown owners, duplicate complete record keys, unsupported formats, and failed no-change round trips block recovery.

Recovery warns players using the configured maintenance delay, saves and stops the game, creates a full backup, and reads the stopped save again. It checks each selected record's owner and expedition against the preview before removing only `MapObjectConcreteInstanceIdAssignedToExpedition`. It checks the edited save, restores the removed properties in a verification copy, and requires that verification copy to reproduce the original uncompressed bytes exactly. The compressed result is also decompressed and compared before installation.

The installer verifies the stopped save's SHA-256, stores an additional original `Level.sav` under `.palmanager/save-recovery/`, and replaces the file atomically. Full backups are available in **Backups**. A previously running world is started again. If a step fails after stopping, the world stays stopped for inspection. Recovery uses the same remote maintenance lock as the Ubuntu worker; no worker publication is required for this Windows action.

Keep the app open through completion. Check the player's Palbox afterward. Offline validation verifies file structure and preservation; it does not substitute for checking the result in the game. No live save was edited during development of this release.

## Dependencies and sources

The save parser is vendored from [Palworld Save Editor](https://github.com/xyuqikzz/Palworld-Save-Editor), which includes the original MIT-licensed palworld-save-tools and later GPL-3.0 contributions. Its notices and GPL text are included under THIRD-PARTY-LICENSES/save-engine. The bundled Windows `ooz.pyd` is supplied by that upstream editor; it exposes both compression and decompression. Do not replace it with PyPI pyooz 0.0.8, which only decompresses.

The combined distribution with the GPL save engine is provided under GPL-3.0; the original manager source retains its MIT notice. The source package includes the parser, upstream codec source archive with submodules, dependency notices, build instructions, and provenance hashes. See THIRD-PARTY-LICENSES/save-engine/PROVENANCE.json. Build the app using the included PyInstaller spec to preserve the native codec.

Repair behavior is corroborated by [upstream expedition recovery](https://github.com/xyuqikzz/Palworld-Save-Editor/blob/develop/src/palworld_pal_editor/core/pal_entity.py) and the [Palworld 1.0 migration report](https://gist.github.com/rudy649/b535dee3f9293778e774cefe662abe2e). Player IDs are composite map keys; the repair preserves separate old-host records.
