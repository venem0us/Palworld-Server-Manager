# Palworld Manager for Windows

A native Windows desktop app for managing Palworld on a remote Ubuntu machine over SSH. This is an initial, unsigned **0.2.11** release. It is not affiliated with Pocketpair.

## Changes in 0.2.11

Chat & broadcast now has an optional welcome announcement, disabled by default. Set the message using {player} and {world}, enable the checkbox and save. Requires REST player access; announcements are visible to everyone. Monitoring establishes an initial roster without greeting existing players, then welcomes newly detected joins. Brief joins between polls may not be detected. API failures retain the previous roster to avoid duplicate welcomes. Keep Windows open or publish the updated worker in Schedule for Ubuntu operation. Publish again after changing welcome settings. Imported profiles have welcomes disabled.

## Changes in 0.2.10

Schedule supports **Edit selected** and double-click editing of action, message, timing and enabled state. The Ubuntu sync column compares each task against the running worker: **Published** means it matches, **Changes pending** means it differs, **Not published** means it is absent, and **Not verified** means worker configuration is unavailable. Publish after editing, toggling or removing tasks. A notice identifies tasks removed locally that still exist on Ubuntu. Sync status refreshes with connection checks and indicates configuration, not successful execution.

## Changes in 0.2.9

Added **+ Add world → Install a new server on Ubuntu**. The wizard verifies SSH/sudo access, Ubuntu/architecture, resources, free ports and unused installation paths before installing SteamCMD, Palworld and its systemd service. It streams progress, supports recognized interrupted downloads, keeps existing worlds intact, and saves the connection profile. Supports native x86-64 Ubuntu 22.04+ with Python 3, systemd and an existing non-root sudo account. See UBUNTU-INSTALL.md for setup, firewall details and validation limits.

## Changes in 0.2.8

Added **Save repair** for Pals stuck on missing expeditions after migration. Scan the world, choose the player and select Pals to recover. Recovery creates a full backup, stops the world and revalidates ownership, preserves unrelated save bytes, and keeps an original recovery copy. See SAVE-REPAIR.md for the workflow, supported format and dependency licenses. The live server was not modified during development. With the bundled GPL save engine, the combined distribution is GPL-3.0; the manager’s original MIT notice and dependency notices are retained in the included source package.

## Changes in 0.2.7

Fixed the live map and location labels to convert REST Unreal-world coordinates to Palpagos in-game coordinates. Previously the API’s large raw values fell outside the map bounds. The Players X/Y columns remain raw for diagnostics; location tooltips show converted map coordinates. Custom named locations are entered in map coordinates. The live map and exported/Discord PNGs share this conversion. World Tree positions require a separate map and are not plotted on Palpagos.

**Live map → Map image & calibration** now offers a full-world PNG download link and **Use full PalMap PNG bounds**. Download the linked full PNG, select it with Browse, apply that preset and save. The 27 MB image is supported (image limit raised to 50 MB). Custom images need their own bounds. Images retain their aspect ratio. No game restart is needed; republish the Ubuntu worker if it generates Discord map PNGs. See MAP-SETUP.md for links, coordinate details and instructions.

## Changes in 0.2.6

Schedule now shows a server-verified Ubuntu worker status: **Not checked**, **Not installed**, **Installed / Running**, **Installed / Stopped**, **Failed**, or **Status unavailable**. It also shows startup enablement and whether the worker responds to its health check. Status refreshes with the normal connection poll; **Check worker status** requests a refresh. Detection works even when the local profile does not have Ubuntu automation enabled. It does not install, start or disable services, or change which scheduler runs your jobs. The configured automation target is displayed separately.

## Changes in 0.2.5

Players now includes a **Location** column with approximate “Near [landmark]” names from 61 landmarks across the original islands, Sakurajima and Feybreak. Hover over a name for distance and interpretation. Outside the catalogue radius the app shows **Unknown area**; missing coordinates show **Unavailable**. The X/Y columns retain the REST values.

Select a player and choose **Add named location** to name a base or other spot, using their coordinates or your own. Custom locations take priority within their match radius and are saved with the world profile. **Remove custom location** removes a custom label. This feature runs locally and needs no server restart or worker publication. See LOCATION-SOURCES.md for data attribution and limits; it is not an exact region or dungeon detector.

## Changes in 0.2.4

Schedule now includes **Send message**. Choose **Schedule → Add schedule → Send message**, enter up to 500 characters, and choose an interval or daily time in the profile timezone. For example, schedule a 03:50 message saying maintenance begins at 04:00, with a separate restart schedule at 04:00. Message schedules announce only; they do not restart the world. They use REST with RCON fallback and appear in Activity when executed. If the Ubuntu worker is enabled, use **Install / publish to Ubuntu** after adding or changing a schedule.

## Changes in 0.2.3

Accepts the ID-zero RCON replies observed from native Palworld 1.0.4, while still rejecting failed authentication, malformed packets and unrelated replies. Windows and Ubuntu worker use the same RCON implementation. REST connection failures now explain that settings require a restart. If using the Ubuntu worker, publish it again from Schedule to update its code.

## Start here

1. Run `PalworldManager.exe`. Python is not required for the packaged executable.
2. Select **Connection…** and enter the password for each account separately: Steam / server owner (`steam`) and administrator (your sudo account). They may be different. Passwords are visible in the app and saved encrypted on disk. Choose whether to remember it. Saved credentials use Windows DPAPI and are tied to your Windows account.
3. Select **Connect / refresh**. Activity shows connection stages, API availability, completion and failures. Enter your Ubuntu host, account names, installation path, service name and independently verified SSH host fingerprint before connecting.
4. To enable player administration and location data: open **Settings**, load the settings, click **Enable REST**, then **Apply changed settings**. Restart the world when ready. The app warns players through the existing RCON connection, saves, stops and starts the service.
5. REST travels inside SSH to `127.0.0.1:8212`. You do not need to expose that port or change the firewall. If your configuration uses a different REST port, change both the connection profile and INI setting.

The existing `AdminPassword` is read over SSH when needed. It is never included in exported settings or profiles. No passwords are embedded in the executable or source.

## Reference installation

| Item | Value |
|---|---|
| Host | Your Ubuntu SSH hostname or IP |
| Server file owner | `steam` |
| Sudo account | Your non-root sudo account |
| Installation | `/home/steam/.steam/steam/steamapps/common/PalServer` |
| Service | `palworld.service` |
| Game | `v1.0.4.102642`, Steam build `25080279` |
| Configuration | `Pal/Saved/Config/LinuxServer/PalWorldSettings.ini` |
| Settings | 122 defaults; 119 explicitly present in the reference INI at inspection |
| Platform | Native x86-64 Linux; Ubuntu glibc 2.35 |
| API | REST disabled; RCON enabled at inspection |

## Existing maintenance behavior

The reference installation used `Restart=always`, a six-hour runtime limit, a startup update/backup script and a stop backup script. The startup script also permanently purges old backups. The app reports this on Overview.

**Schedule → Take over maintenance** writes `/etc/systemd/system/palworld.service.d/90-palmanager.conf` to turn off the legacy hooks and runtime limit and use `Restart=on-failure` with a 15-second delay. It does not restart the running world. The original service file is preserved. After takeover, configure your preferred schedules in the app. Otherwise the original service continues to update on startup even if the app's auto-update checkbox is off.

An administrator can revert this optional override by moving that specific drop-in to Trash and running `sudo systemctl daemon-reload`. Do not run `systemctl revert` blindly: that can affect unrelated administrator overrides.

## Feature coverage and limits

| Feature | This release |
|---|---|
| Start, stop, restart, update | Implemented using SSH and systemd. Stop/restart/maintenance warn and save first. |
| Crash guardian | Reads existing systemd policy and can configure persistent server-side recovery. |
| Optional auto-update | Checks the Steam public build hourly, announces maintenance, backs up, updates and starts again. Runs on Ubuntu when the optional worker is installed; otherwise Windows must stay open and awake. |
| Settings | Discovers all options from the installed default and actual INIs, including future/unknown fields. Section filter, search, per-field reset and changed-only atomic writes. |
| Presets | Two suggested starting points. They are **not independently community-tested** and are labeled accordingly. |
| Players | REST player list, kick, ban and unban by platform user ID. Requires enabling REST. |
| Live map | Live player dots and names, coordinate grid, PNG export and optional user-supplied terrain map with axis calibration. **No terrain image is bundled.** |
| Console | Polls the systemd journal every five seconds, follows journal cursors and bounds the visible log history. |
| Backups | Consistent stopped-world `Pal/Saved` archives, verification, listing, download and restore. Maintenance includes a brief outage. |
| Schedules | Interval or daily backups/restarts. Uses the profile’s IANA timezone, persists next execution and coalesces missed intervals into one run. The optional Ubuntu worker runs independently of Windows. DST spring gaps move forward; a repeated fall time runs once. |
| Mods | Import/toggle/remove PAK files; import Lua or JSON archives when a compatible native framework already exists. Mutations require the world to be stopped. |
| Workshop / framework installers | **Not implemented for this native Linux configuration.** The official Workshop loader requires Windows. The inspected BlackBook and Xarmina UE4SS binaries require glibc 2.38; NullPrism requires 2.39. This server has 2.35. PalSchema 0.6.7 ships a Windows DLL. The UI reports these limits. |
| Chat and broadcast | Announcements via REST with RCON fallback. Chat-reading requires a server/mod log source; configurable file and regex parsing are provided. **No chat-producing bridge is installed.** |
| Discord notifications | Multiple encrypted webhook destinations per world with separate event routing and disabled mentions. Requires your webhook URLs. Failed deliveries are reported locally; no durable retry queue. |
| Discord bot | All eight requested slash commands, per-command user/role allowlists, deny by default, no message-reading intent. `/player-location` attaches a PNG. Requires your own bot token, guild ID and invitation. Use a separate bot application per world. Can run on the Ubuntu worker after installing its optional bot runtime. |
| Appearance | Profile icon, banner and accent; map dots use the world accent. |
| ZIP transfer | Redacted settings and profiles with image assets. Credentials, live schedules, webhook channels and bot permissions are excluded for sharing. Profile archives do not contain save data or server binaries; use backups to transfer saves. |
| Recoverable removal | Windows Recycle Bin for profile removal; freedesktop Linux Trash for saves, mods, manager backups and installation removal. Rejects symlinks and cross-filesystem Trash operations. |

This release therefore does **not** fulfill the entire requested feature list. Its principal gaps are automatic compatible framework/Workshop installation on your Linux server, a built-in game-chat source, a bundled terrain map, and independently tested community presets. Unattended schedules and Discord support are now included through the optional Ubuntu worker. Moving your live server to Wine or a different OS was deliberately not performed.

## Unattended Ubuntu operation

1. Set the schedules, auto-update preference and **Connection → Schedule timezone**. The default is `America/New_York`.
2. Select **Schedule → Install / publish to Ubuntu**. This creates a separate manager service, not a new game server. It does not restart the running game. No worker was installed on your live world during validation.
3. Publish again after editing schedules, warning time, Discord routing/permissions, chat configuration or map settings. The worker uses the last published snapshot. Its ready/error state appears on Schedule while connected.
4. For your bot, save the token and guild ID in Discord, then click **Start bot**. With the worker enabled, this installs a private Python runtime on Ubuntu and publishes the enabled bot. **Stop bot** publishes it disabled. Bot login and real Discord delivery require your credentials and have not been live-tested.
5. **Disable Ubuntu worker** stops only the manager and returns scheduling to Windows. It keeps worker files for recovery. Any maintenance already in progress finishes before the worker stops.

The worker is `palmanager-<installation-id>.service`, with code under `/opt/palworld-manager/<installation-id>` and root-only configuration/state under `/var/lib/palworld-manager/<installation-id>`. Its `/run/palmanager-<installation-id>.sock` is accessible only to the game owner and root. The worker accepts a fixed set of maintenance actions and no arbitrary shell commands. It uses root for systemd control and runs game-file/SteamCMD operations as `steam`. SSH and sudo passwords are **never** copied to Ubuntu; configured Discord secrets are stored there with root-only permissions.

The optional bot runtime may install Ubuntu’s `python3-venv` package and downloads pinned `discord.py`/Pillow dependencies into the worker’s private environment. Existing game scripts, configuration and system libraries are not replaced. The original six-hour restart/update hooks remain unless you separately choose **Take over maintenance**.

## Safety and behavior

- The default SSH host key is pinned to the key observed on your server. New hosts require verifying and entering their SHA256 fingerprint. Changed keys are rejected.
- `steam` owns file operations. The administrator connection elevates service control, the selected systemd override and optional worker deployment.
- A server-side workflow lock serializes manager maintenance across clients. File operations also lock the installation while changing data.
- Settings edits compare a SHA256 version before writing, keep a configuration history, preserve untouched text and the UTF-8 BOM, and replace the file atomically. Reload after outside edits.
- A backup stops the game after an announcement/save, archives `Pal/Saved`, verifies the compressed data and restarts only if it was running beforehand. A failed maintenance operation leaves the world stopped for inspection.
- Restores validate archive paths and entry types, refuse symlinks/special files, check available disk space, stage data separately and move the previous `Saved` to Trash. An additional pre-restore backup is taken automatically.
- Manager data on Ubuntu lives under `<installation>/.palmanager`. Backup files are below `backups`; settings history is below `config-history`. The optional worker adds a private Unix socket only; it opens no network listening port.
- Restoring `Pal/Saved` also restores its configuration and world identity. If a restored INI changes the REST port, update the connection profile to match.
- Local application data is in `%LOCALAPPDATA%\PalworldManager`. `PALMANAGER_DATA` can override that directory. Never share `credentials.dpapi` as a way to transfer credentials; enter them again on another Windows account.
- Keep one authoritative scheduling setup. With the Ubuntu worker enabled, Windows suppresses its own scheduler and sends maintenance commands to the worker. Without it, closing Windows pauses those jobs. Ubuntu systemd crash recovery always remains independent.
- Commands that produce irreversible game effects, such as a ban or restore, are exposed as explicit UI actions. Removing files uses Trash; the app does not provide a permanent-delete option.

## Validation performed

- 59 automated tests passed: INI parsing/preservation, mutation validation, archive export secrecy, profile path rejection, Windows DPAPI, backup ordering and failures, operation locking, connection activity success/failure, visible field labels, distinct SSH account credentials and encrypted save/reload, timezone and DST calculation, background delegation and duplicate-job prevention, Discord command allowlists and PNG generation.
- All 11 desktop pages rendered in UI smoke tests; actual server INIs populated 122 fields; editing one setting produced one change.
- The final packaged executable passed its own isolated self-test (exit code 0): all 11 pages, bundled SSH helper sources, Windows DPAPI and map PNG generation.
- Connected to the actual Ubuntu installation: status, Steam build, settings, journal, capabilities and read-only sudo access verified.
- A temporary HTTP fixture on Ubuntu verified GET/POST REST traffic and Basic authentication through the SSH tunnel. The game's REST API remains disabled, so player moderation was not exercised against the live game.
- An isolated temporary PalServer fixture verified atomic edits, stale-write rejection, backup/restore, traversal rejection and Linux Trash. The fixture and its recovery save were moved to Trash afterward.
- A second isolated systemd fixture verified worker deployment, private-socket commands, maintenance backup, schedule execution, due-time persistence across worker restarts, timezone publication and worker removal. The fixture never used live save data.
- The live server's PID and settings hash were unchanged by validation. **The live world was not stopped, updated, restored or modified.**
- Discord delivery/bot login need your credentials and were not tested against Discord. Mod loading requires compatible binaries and was not tested in game.

## Build from source

Windows x64 and Python 3.12 are the tested build environment. Run `build.ps1`, or:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller==6.22.2
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean PalworldManager.spec
```

Use the supplied spec: it prevents unrelated ICU libraries on the build machine's PATH from shadowing Windows' native ICU ABI used by Qt. The resulting executable is unsigned; no signing certificate was supplied. Third-party libraries retain their own licenses. The source is provided so the app can be audited, extended and rebuilt.

## Sources

- [Your Ubuntu installation guide](https://gist.github.com/troyfontaine/1f55fb13db2dc8de7f52c02c86874a2b)
- [Official Palworld configuration parameters](https://docs.palworldgame.com/settings-and-operation/configuration/)
- [Official REST API](https://docs.palworldgame.com/category/rest-api/)
- [Player list and coordinates](https://docs.palworldgame.com/api/rest-api/players/)
- [Official Workshop server support](https://docs.palworldgame.com/settings-and-operation/mod/)
- [NullPrism Linux requirements and scope](https://github.com/NullPrism/RE-UE4SS-Linux/blob/main/docs/linux.md)
- [PalSchema source and release requirements](https://github.com/Okaetsu/PalSchema/releases)

- [BlackBook Linux UE4SS release inspected](https://github.com/BlackBookOfficial/ue4ss-linux-palworld/releases/tag/v1.0.2-palworld-linux)
- [Xarmina Linux UE4SS release inspected](https://github.com/XarminaEu/ue4ss-linux/releases/tag/v3.0.2)

## License

The combined application is distributed under GNU GPL version 3; see LICENSE. The original manager code retains its MIT notice in LICENSE-MIT. Third-party components retain their own copyright and license notices under THIRD-PARTY-LICENSES. Executable distributions must include access to the corresponding source and build instructions. Palworld and its assets belong to their respective owners; this repository does not distribute the game or world saves.
