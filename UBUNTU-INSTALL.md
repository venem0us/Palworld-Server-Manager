# Install a new server on Ubuntu

In the manager, select **+ Add world → Install a new server on Ubuntu**.

1. Enter the Ubuntu host, SSH port, and an existing non-root account with sudo access. Enter its SSH password or private-key path; the separate sudo password defaults to the SSH password when blank. The game will run under this account. A dedicated account can be created on Ubuntu beforehand if preferred.
2. Choose **Read SSH fingerprint** and verify it against a trusted console on the Ubuntu machine. Check the verification box.
3. Choose a world name, directory name, and distinct game/query/REST ports. The new installation lives in `<account home>/PalServers/<directory name>` and uses `palworld-<directory name>.service`. A strong random server-admin password is generated; you can change it.
4. Choose whether to start the server after installation. The optional UFW checkbox only adds the game UDP allowance when UFW is already active. It never enables UFW or changes default firewall policies.
5. Choose **Check Ubuntu**, review the proposed directory, service and resource checks, read/accept the Steam terms, then choose **Install Palworld**.

Progress appears in the wizard and Activity, including elapsed-time updates during package installation and downloads. Keep the app open. On success, the connection profile is added automatically and credentials can be saved with Windows DPAPI encryption. The REST password is read from the server INI when needed.

## Prerequisites and behavior

The installer supports native x86-64 Ubuntu 22.04 or newer with Python 3, systemd, apt repositories and outbound access to Ubuntu/Steam. ARM, root-only logins, symlinked home/install paths, and non-systemd containers are rejected. SSH must already be configured. Use a supported Ubuntu release with working package repositories; the wizard does not upgrade the operating system.

Allow at least 15 GiB free space and 8 GB RAM; 16 GB RAM and four CPU cores or more are recommended. The installer checks resources and occupied ports again before installing. It enables multiverse/i386 package support, installs SteamCMD/runtime dependencies, downloads app 2394010 as the non-root owner, sets up the Steam SDK, writes initial settings and registers a systemd service with restart-on-failure. It enables startup even if immediate startup is unchecked.

The REST API is enabled on the chosen TCP port with the generated admin password. Keep that port private with host/cloud firewall rules; manager requests use SSH forwarding. RCON is disabled. Players require the game UDP port (default 8211), plus any router/cloud forwarding appropriate to your network. The installer does not configure router or cloud-provider rules.

Existing units, nonempty directories and saved worlds are protected. Interrupted downloads can be retried with the same account, directory, ports and world name when the installer has recorded a matching partial installation. Unrecognized files are never erased to force a retry. Successful existing servers should be added using **Connect to an existing server**. No recurring updates, backup deletion hooks or broad process-killing scripts are installed.

If the files and service install successfully but startup/REST readiness fails, the profile is still saved and the wizard reports the problem. Inspect **Connect / refresh** and **Console** before retrying Start. Full clean-machine Steam downloads were not performed during this release's validation; installation stages were tested with controlled fixtures and the read-only preflight was exercised on Ubuntu 22.04.

## References

- [User-provided Ubuntu setup guide](https://gist.github.com/troyfontaine/1f55fb13db2dc8de7f52c02c86874a2b)
- [Official Palworld deployment](https://docs.palworldgame.com/getting-started/deploy-dedicated-server/)
- [Official server requirements](https://docs.palworldgame.com/getting-started/requirements/)
