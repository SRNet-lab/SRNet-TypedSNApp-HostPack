# Running your own SRNet host

*Host pack 0.5.0*

This pack lets you run a piece of the SRNet community on your own server: a message board,
a store, a wiki, chat rooms, a file drop, a profile directory, a directory of communities or
a mail host. You do **not** write or ship any app code. The apps are built into the SRNet
client. Your server only stores and serves signed data, and every user's client checks that
data before showing it.

## What you need

- A Linux server with Python 3.10 or newer and the `cryptography` package
  (`apt install python3-cryptography` on Debian/Ubuntu). With systemd, the pack installs a
  locked-down service; without it, `srnet-host run` runs the host in the foreground.
- A **second machine for the root key**, ideally one that stays offline (an old laptop,
  or a live USB). The root key is the identity of your host. If someone steals it, they can
  impersonate you, so it never goes on the server.
- About 10 minutes.

## The two keys, in plain words

| Key | Lives on | Does |
|---|---|---|
| **Root key** | your offline machine | Vouches for your server for up to 90 days at a time. Its public half (the **root pin**) travels in every invite link, and clients pin it on first join. |
| **Host key** | the server | Signs the day-to-day data. Made automatically. If the server is compromised you just stop renewing it. |

## Step by step

**1. On the offline machine: create the root key (once).**

    ./bin/srnet-host root init --dir ./srnet-root

Write down the root pin it prints. Back up `srnet-root/root.key` (USB stick, paper copy).

**2. On the server: prepare the host.**

    sudo ./bin/srnet-host init --type rooms --name lobby --room hikers --room maps

Types:

| Type | Serves |
|---|---|
| `board` | a message board |
| `store` | a store; buyers pay the seller's own address in USDC (Arbitrum One or Base) from their own wallet |
| `wiki` | a wiki |
| `rooms` | one or more chat rooms (`--room NAME` adds another, repeatable) |
| `files` | a file drop, which makes you a Storage Seller (encrypted by default; files up to 25 MiB by default) |
| `people` | a profile directory |
| `directory` | a directory of communities; each entry is signed by the listed collection's root key |
| `mail` | a mail host: sealed store-and-forward mail |

Names start with a letter and use lowercase letters, digits and dashes. Options: `--port`,
`--prefix` (default `/opt/srnet-host/<name>`), `--admin <pubkey>` (wiki, rooms, people,
directory) and `--seller <pubkey>` (store).

`init` also asks about the host's own **`.sesh` name**: **make** a new key, **import** a key file
you already have (for example one from a vanity-name search), or **skip** and add one later.
Flags do the same without a prompt: `--sesh new`, `--sesh-import FILE`, `--sesh skip`. Without a
terminal the default is skip. `srnet-host sesh --prefix … --sesh new` adds a name later.

This creates a host key and a file called `request.json`. It is in the host's folder,
`/opt/srnet-host/<name>/request.json`. Copy it to the offline machine, for example on a USB
stick or with `scp`.

**3. Carry `request.json` to the offline machine and sign it.**

Run this in the folder that holds `srnet-root`:

    ./bin/srnet-host root sign request.json --days 90

Before you answer `y`, check that the host key it shows matches the one the server printed.
This writes `delegation.json`, which is public and safe to copy around.

**4. Back on the server: install it.**

    sudo ./bin/srnet-host install-delegation delegation.json --prefix /opt/srnet-host/lobby

With systemd, this installs a locked-down system service and starts it. Without systemd, or
with `--no-systemd`, start the host with `srnet-host run --prefix …`. Either way it prints
your connect info: the type, the collections, the root pin and an invite link for each
collection.

**5. Check on it any time.**

    sudo ./bin/srnet-host status --prefix /opt/srnet-host/lobby
    ./bin/srnet-host link --prefix /opt/srnet-host/lobby

`status` shows health, days left on the delegation, the `.sesh` name and the invite links.
`link` prints just the links, ready to share.

## Letting people in

Out of the box your host listens only on 127.0.0.1. To give it a `.sesh` name people can reach,
install the SRNet build of Session Router on the server and start a front for the host.

**1. Install Session Router** (Ubuntu 24.04, x86_64). This is the same SRNet build the
SRNet client uses (source:
[Session-Router-SRNet](https://github.com/SRNet-lab/Session-Router-SRNet), branch
`srnet/mapexit-dev`):

```sh
cd /tmp
curl -fLO https://github.com/SRNet-lab/Session-Router-SRNet/releases/download/v1.1.0-srnet6/session-router-srnet_1.1.0+srnet6_amd64.deb
echo "5c1c9b553b25649657f9f8e3ae0431aa3fe0534c82e65214588c728307bf3237  session-router-srnet_1.1.0+srnet6_amd64.deb" | sha256sum -c \
  && sudo apt install -y ./session-router-srnet_1.1.0+srnet6_amd64.deb \
  && sudo apt-mark hold session-router-srnet
cd ~/SRNet-TypedSNApp-HostPack
```

You should see `checksum OK` before apt starts. If the check fails, nothing gets installed:
download it again and rerun the chained lines. The package installs `/usr/bin/session-router`,
which `srnet-host front` finds by itself. The server does not need the SRNet client.

**2. Start the front** with the `.sesh` key that `init` made:

```sh
sudo ./bin/srnet-host front --sesh-import /opt/srnet-host/lobby/sesh/identity.key \
    --host /opt/srnet-host/lobby
```

It prints the name and the invite links. Both of its services start now and at every boot. If
you skipped the `.sesh` question in `init`, first run
`sudo ./bin/srnet-host sesh --prefix /opt/srnet-host/lobby --sesh new`. If Session Router is
installed somewhere other than `/usr/bin` or `/usr/local/bin`, add `--sr-binary PATH`.

**3. Open the firewall on the front's interface only.** If ufw is on (it is on most VPS images):

```sh
sudo ufw allow in on sr-front to any port 80 proto tcp
```

Nothing else needs opening, because Session Router only makes outgoing connections. The name
answers within a minute or two.

Then share the invite links from `srnet-host link`. Each one looks like

    srnet://<name>.sesh/room/hikers#root=<root pin>

and carries everything a client needs: the address, the collection and your root pin. A
bare `<name>.sesh` also works: the client lists every collection the host offers.

## Listing in a directory

A directory lists communities whose operators opted in. Each entry must be signed by the
root key of the collection it lists, so nobody can list your community but you, and nobody
can point your title at someone else's host.

On the offline machine, sign an entry for one of your own links:

    ./bin/srnet-host root directory-entry --link 'srnet://<name>.sesh/room/hikers#root=<pin>' \
        --title "Hikers" --desc "Weekend walks, routes and meetups" --directory-name directory

Carry `directory-entry.json` to any online machine and post it:

    ./bin/srnet-host directory-submit directory-entry.json --to http://<directory>.sesh/c/directory

To run a directory yourself, use `--type directory`. Clients show only entries signed by the
listed collection's own root key.

## Running a mail host

    sudo ./bin/srnet-host init --type mail --name post1

A mail host keeps sealed messages for people until they pick them up. It can't read them
and can't see who sent them. It listens on `127.0.0.1:48915` by default. Signing and
installing work the same as for the other types, and `srnet-host link` prints the mail host
URL people add as one of their mail hosts.

**Open or closed.** A mail host is **open** by default: anyone can create an inbox, up to
1000. To stop new inboxes (existing ones keep working):

    sudo ./bin/srnet-host mail --prefix /opt/srnet-host/post1 --closed

`--open` turns sign-up back on and `--max-inboxes N` changes the cap. You can also start
closed with `srnet-host init --type mail --name post1 --closed`.

- Each inbox holds up to 256 messages or 8 MiB, plus a "requests" pile for mail from
  strangers: 32 messages of up to 16 KiB, 20 per hour. Change the pile limits with
  `srnet-host mail --prefix … --requests-max-msgs N --requests-per-hour N`.
- Messages are deleted after their owner's client confirms it saved them, or after 7 days
  (up to 30 if the sender asks) if never confirmed.
- Total storage is capped at 1 GiB.

## Keeping it running

- **Renew every 90 days or sooner.** `status` warns you two weeks ahead. Run
  `srnet-host renew`, sign the new `request.json` on the offline machine, then run
  `install-delegation` again. The server refuses a delegation from a different root unless
  you pass `--allow-root-change`.
- **Upgrade:** unpack the new release, verify it, and run its
  `./bin/srnet-host upgrade --prefix …`. It swaps in the new code, keeps your keys, data,
  delegations and `.sesh` name, keeps the previous code in `<prefix>/app.prev`, and restarts
  the service. It refuses to move to an older version unless you pass `--force`.
- **Back up:** `srnet-host backup --prefix …` writes a `.tar.gz` with your data and host key.
  Keep it private. It never contains the root key.
- **Remove:** `srnet-host uninstall --prefix …` stops the service and keeps the data.
  Add `--purge --yes` to delete everything.

## Moderating

Find a post's id in the client (⋯ menu) or in `/v1/log`. Every action is a signed, public
record, so users can see what you did.

- **Hide** (spam, off-topic): the post stays on your disk and keeps syncing. Users' clients hide
  it by default, and users can choose to show it.
  `srnet-host moderate --prefix … hide post <id> --reason spam` (`unhide` reverses it;
  `hide author <key>` hides everything from one key).
- **Pin** up to 3 posts at the top of a room or board:
  `srnet-host moderate --prefix … pin post <id>` (`unpin` to drop one).
- **Header:** the description and rules shown at the top of the room:
  `srnet-host header --prefix … --description "…" --rules "…"`.

Add `--coll <room>` for a room other than the host's main one.

### Removing content

Use **remove** for content you must not keep: child abuse material, doxxing, credible threats,
or anything a valid legal order covers.

    srnet-host moderate --prefix … remove post <id> --reason "illegal content"

It asks you to type `REMOVE` (or pass `--yes`). Your host then deletes the post text from its
disk at once. For a file, it deletes the file's bytes too. The post leaves a small signed
placeholder, so the room's history still verifies. Mirrors and users' clients delete their
copies the next time they sync, and the post shows as "Removed by host: <reason>". Nobody can
show it again. A remove can't be undone, and the record, including your reason, is public, so
don't put personal data in the reason. Removing content doesn't take back copies someone
already downloaded or screenshotted. Report illegal material to the authorities where the
law requires it.

## File limits (Storage Sellers)

`srnet-host init --type files … --max-file-mb 25 --quota-mb 500` sets the largest file and
the MiB each uploader key may store (0 means no quota). Change them later with
`srnet-host files --prefix … --max-file-mb 50`. The limits are in your signed policy, so
clients refuse a file that's too large before uploading it. Large files upload in 1 MiB chunks
and resume after an interruption. Make sure your disk can hold the total you allow.

## What your host does and doesn't do

- It checks every record's signature and its small proof-of-work puzzle, and it applies rate
  limits. New keys get a slightly harder puzzle.
- You can hide, remove and pin posts (see "Moderating"). Every action is signed and public.
- **Stores never touch money.** Buyers pay the seller's own address straight from their own
  wallet, then post a signed order naming the transaction, which the seller can check on chain.
  There is no developer fee, no contract and no escrow.
- As a Storage Seller you serve files only by their SHA-256 hash. The SRNet client encrypts
  each file on the uploader's computer with ChaCha20-Poly1305 before upload, so you store only
  ciphertext, unless the uploader chooses to publish a file unencrypted. You set the largest
  file size (25 MiB by default) and can set a storage quota per uploader (see "File limits").
- Coming soon: Storage Sellers will be able to turn off public hosting, so they hold only
  encrypted files they can't read.
- You are responsible for what you host under your local laws.

## Security defaults the installer sets

Runs as an unprivileged `srnethost` user. The data directory is mode 700 and the host key
is mode 600. Under systemd the service has no capabilities, a read-only system, no home
access, private /tmp and devices, and its network is limited to localhost by systemd's IP
filter. The host refuses to bind a public address.

## .sesh key files

- Import checks the key, copies it unchanged with mode 600, and shows the resulting name.
  It never prints the secret.
- Accepted key files: a 32-byte seed or a 64-byte seed+public key (as hex or raw bytes), or a
  `d1:s64:…e` identity file.
- `init` and `sesh` refuse to overwrite an existing `.sesh` key.

## Verifying a download

Releases ship `srnet-hostpack-<ver>.tar.gz`, `SHA256SUMS`, `SHA256SUMS.sig` and
`allowed_signers`. Check them before unpacking:

    sha256sum -c SHA256SUMS
    ssh-keygen -Y verify -f allowed_signers -I release@srnet -n srnet-release \
        -s SHA256SUMS.sig < SHA256SUMS

Compare the key in `allowed_signers` with the release key published by the SRNet maintainers.

## One .sesh name for several roles (`srnet-host front`)

Run rooms, directory, files and mail on one server under ONE .sesh name:

    srnet-host init --type rooms --name lobby --sesh skip        # ... and directory, files, mail
    # sign each request.json on the root machine, then install-delegation on each
    srnet-host front --sesh-import name.key \
        --host /opt/srnet-host/lobby --host /opt/srnet-host/directory \
        --host /opt/srnet-host/files --host /opt/srnet-host/mail

`front` copies the key (never moves it; refuses to overwrite a different stored key), writes a
Session Router client config (own tun range, `[bind] listen=:1250`), and starts two units:
`srnet-front-router` (the name) and `srnet-front` (a path router on the tun address, port 80):
`/c/<collection>` goes to the hub serving it, `/v1/mail` to the mail host, `/v1/collections`
lists everything. Each host's `link` then prints links on that name. Open tcp/80 on
`sr-front` only: `sudo ufw allow in on sr-front to any port 80 proto tcp`.
A board host serves at `/`, so it needs a name of its own: run `front` with the board as the
only `--host`.

With systemd, `front` enables both units so they start at boot. Pass `--no-systemd` to only
write the unit files to the front directory and start them yourself, or turn off autostart
later with `sudo systemctl disable srnet-front-router srnet-front`.

### Other loopback services on the same name (`--route`)

`--route /NAME=PORT` (repeatable) also forwards `/NAME/...` to `127.0.0.1:PORT`, for example an
SRNet relayer, so it is reachable only over Session Router and never on a public IP:

    srnet-host front --sesh-import name.key \
        --host /opt/srnet-host/lobby --host /opt/srnet-host/mail --route /relayer=8645

Re-run `front` with the same `--route` options whenever you change the hosts (routes not given
are dropped). The front sets `X-Forwarded-For` to each caller's Session Router address and drops
any value the caller sent, so a loopback service can rate-limit per caller (`srnet-relayer
--trust-proxy` does). The relayer itself comes with the SRNet client
([SRNet-Desktop](https://github.com/SRNet-lab/SRNet-Desktop), `client-cli/README.md`,
*Running a relayer*); keep it on `--host 127.0.0.1`.
