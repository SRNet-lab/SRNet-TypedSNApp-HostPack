# Changelog

## [Unreleased]

### Changed

- The README, the host guide and `srnet-host sesh-help` install the SRNet build of Session
  Router (Session-Router-SRNet 1.1.0+srnet6, the same one SRNet-Desktop uses) from its release
  `.deb`, with a checksum check. No Session Foundation apt repository is needed, and the server
  does not need the SRNet client.
- The next steps `init` prints are the exact commands to run from the pack folder, with `sudo`
  where it is needed.

## [0.5.0] - 2026-10-20

### Added

- Mail hosts can set limits for mail from people who aren't the recipient's contacts.
- The typed client core has a Mail page, a Check my setup button and tabs for add-ons, the same
  as SRNet-Desktop.
- The host guide gives a host a `.sesh` name in three steps: install Session Router, run
  `srnet-host front`, and open port 80 on the front's interface.

### Changed

- No developer fee anywhere in SRNet.
- Simpler store payments: buyers pay the seller's own address in USDC on Arbitrum One or Base,
  straight from their own wallet. No balance, no contract and no escrow.
- The host code matches SRNet-Desktop, with board, room and wiki templates at 1.6.0.
- File drop hosts are now called Storage Sellers. The README and host guide say that the SRNet
  client encrypts files and mail on the user's computer with ChaCha20-Poly1305.
- `.sesh` names go through `srnet-host front`, which finds Session Router wherever it is
  installed. `--sr-binary PATH` points it at another copy. `init` stores only the `.sesh` key.
- A board host gets its own `.sesh` name by running `front` with the board as the only `--host`.
- The host guide uses `sudo` where it's needed and says where `request.json` is.

### Removed

- SRNet balance payments in stores.
- The exit template and the Exits and Wallet views. Exits now have their own repository,
  [SRNet-VPSHost-ExitPack](https://github.com/SRNet-lab/SRNet-VPSHost-ExitPack).
- `--bootstrap` from the `front` examples.

### Fixed

- `init` no longer writes a Session Router config that couldn't start. `upgrade` removes the one
  older packs wrote and keeps the key.
- The front closes the connection after refusing a request, so the rest of it is never read as a
  new request, and idle callers time out after 60 seconds.

## [0.4.1] - 2026-10-17

First public release: run your own message board, store, wiki, chat rooms, file drop, profile
directory, community directory or mail host, with the root key kept offline.
