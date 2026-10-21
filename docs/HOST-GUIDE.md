# Running your own SRNet host

*Host pack 0.5.0*

This guide sets up a host on your own server: a message board, a store, a wiki, chat rooms, a
file drop, a profile directory, a directory of communities or a mail host. People use it from
the SRNet app. Your server only stores and serves signed data; you don't write any app code.

## Two machines: your server and your own computer

You use two machines:

- **The server** runs the host. Any Linux server with Python 3.10 or newer works; the Session
  Router steps below are for Ubuntu 24.04.
- **Your own computer** (a laptop or desktop, not the server) holds your **root key**.

The root key is the master key for your host. It proves to people's apps that the host is
yours, and its public half (the **root pin**) is part of every invite link. It stays on your
computer so that someone who breaks into the server can't take over your host. The server gets
its own key, and your root key approves it for up to 90 days at a time.

You use your computer for three things: making the root key once, approving the server, and
approving it again every 90 days. It doesn't need to be disconnected from the internet; it just
shouldn't be the server. Steps below say **On your computer** or **On the server**.

## Set up a host

The example makes a chat room host called `lobby`. Replace the names with your own.

**1. On the server: download the pack.**

```sh
cd ~
sudo apt update
sudo apt install -y git curl python3 python3-cryptography
git clone https://github.com/SRNet-lab/SRNet-TypedSNApp-HostPack.git
cd SRNet-TypedSNApp-HostPack
```

**2. On your computer: download the pack and make your root key.**

```sh
cd ~
sudo apt install -y git python3 python3-cryptography
git clone https://github.com/SRNet-lab/SRNet-TypedSNApp-HostPack.git
cd SRNet-TypedSNApp-HostPack
./bin/srnet-host root init
```

It makes `srnet-root/root.key` and prints your root pin. Back up `srnet-root/root.key` (a USB
stick, or a paper copy). If you lose it, you can't renew your host; if someone else gets it, they
can pose as you.

**3. On the server: create the host.**

```sh
sudo ./bin/srnet-host init --type rooms --name lobby --sesh new
```

It prints the server's **host key** and writes `/opt/srnet-host/lobby/request.json`, the
request for your root key to approve. `--sesh new` also makes the host's `.sesh` address.

**4. On your computer: approve the server.** Copy the request over, then sign it:

```sh
scp you@your-server:/opt/srnet-host/lobby/request.json .
./bin/srnet-host root sign request.json --days 90
```

It shows the host key from the request. Check that it matches the one the server printed in
step 3, then answer `y`. This writes `delegation.json`, which is public and safe to copy.

**5. On your computer: send the approval back.**

```sh
scp delegation.json you@your-server:SRNet-TypedSNApp-HostPack/
```

**6. On the server: install it.**

```sh
sudo ./bin/srnet-host install-delegation delegation.json --prefix /opt/srnet-host/lobby
```

It starts the host as a system service and prints its invite link. The host is running now, but
only on the server itself. The next steps put it on Session Router so people can reach it.

**7. On the server: install Session Router.** This is the same SRNet build the SRNet app uses
(source: [Session-Router-SRNet](https://github.com/SRNet-lab/Session-Router-SRNet), branch
`srnet/mapexit-dev`). On Ubuntu 24.04, x86_64:

```sh
cd /tmp
curl -fLO https://github.com/SRNet-lab/Session-Router-SRNet/releases/download/v1.1.0-srnet6/session-router-srnet_1.1.0+srnet6_amd64.deb
echo "5c1c9b553b25649657f9f8e3ae0431aa3fe0534c82e65214588c728307bf3237  session-router-srnet_1.1.0+srnet6_amd64.deb" | sha256sum -c \
  && sudo apt install -y ./session-router-srnet_1.1.0+srnet6_amd64.deb \
  && sudo apt-mark hold session-router-srnet
cd ~/SRNet-TypedSNApp-HostPack
```

You should see `session-router-srnet_1.1.0+srnet6_amd64.deb: OK` before apt starts. If you
don't, nothing was installed: download it again and rerun the lines. apt may print
`Failed to try-restart session-router-client.service`; you can ignore that on a server.

**8. On the server: give the host its `.sesh` address.**

```sh
sudo ./bin/srnet-host front --sesh-import /opt/srnet-host/lobby/sesh/identity.key \
    --host /opt/srnet-host/lobby
```

It prints the address and the invite links, and starts now and at every boot.

**9. On the server: open the firewall** for Session Router's interface only. If ufw is on (it is
on most VPS images):

```sh
sudo ufw allow in on sr-front to any port 80 proto tcp
```

The address answers within a minute or two.

**10. Share your invite link.**

```sh
./bin/srnet-host link --prefix /opt/srnet-host/lobby
```

Each link looks like `srnet://<name>.sesh/room/lobby#root=<root pin>`. People paste it on Home
in the SRNet app. A bare `<name>.sesh` also works: the app lists everything the host offers.

`sudo ./bin/srnet-host status --prefix /opt/srnet-host/lobby` shows whether the host is healthy
and how many days are left before you need to renew.

## Host types

Pick one with `--type` in step 3:

| Type | Serves |
|---|---|
| `board` | a message board |
| `store` | a store; buyers pay the seller's own address in USDC (Arbitrum One or Base) from their own wallet |
| `wiki` | a wiki |
| `rooms` | one or more chat rooms (`--room NAME` adds another, repeatable) |
| `files` | a file drop, which makes you a Storage Seller (encrypted by default; files up to 25 MiB by default) |
| `people` | a profile directory |
| `directory` | a directory of communities |
| `mail` | a mail host: keeps sealed mail until the recipient picks it up |

Names start with a letter and use lowercase letters, digits and dashes. Other options: `--port`,
`--prefix` (default `/opt/srnet-host/<name>`), `--admin <pubkey>` (wiki, rooms, people,
directory) and `--seller <pubkey>` (store).

For the `.sesh` address, `--sesh new` makes one, `--sesh-import FILE` uses a key file you already
have (for example from a vanity-name search), and `--sesh skip` leaves it for later
(`sudo ./bin/srnet-host sesh --prefix … --sesh new`). Without the flag, `init` asks.

## Keeping it running

- **Renew every 90 days or sooner.** `status` warns you two weeks ahead. On the server, run
  `sudo ./bin/srnet-host renew --prefix /opt/srnet-host/lobby`, then repeat steps 4 to 6.
- **Upgrade:** on the server, run `git pull` in the pack folder, then
  `sudo ./bin/srnet-host upgrade --prefix …`. It keeps your keys, data and `.sesh` address, and
  restarts the service.
- **Back up:** `sudo ./bin/srnet-host backup --prefix …` writes a `.tar.gz` with your data and
  host key. Keep it private. It never contains the root key.
- **Remove:** `sudo ./bin/srnet-host uninstall --prefix …` stops the service and keeps the data.
  Add `--purge --yes` to delete everything.

## Listing in a directory

A directory lists communities that asked to be listed. Each entry is signed with the root key
of the collection it lists, so only you can list your host.

On your computer, in the pack folder, sign an entry for one of your own links:

    ./bin/srnet-host root directory-entry --link 'srnet://<name>.sesh/room/hikers#root=<pin>' \
        --title "Hikers" --desc "Weekend walks, routes and meetups" --directory-name directory

Then post it (from your computer or the server):

    ./bin/srnet-host directory-submit directory-entry.json --to http://<directory>.sesh/c/directory

To run a directory yourself, use `--type directory`.

## Running a mail host

    sudo ./bin/srnet-host init --type mail --name post1

A mail host keeps sealed messages for people until they pick them up. It can't read them
and can't see who sent them. Approve and install it the same way as any host (steps 4 to 9
above). `srnet-host link` then prints the mail host URL people add as one of their mail hosts.

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
disk at once. For a file, it deletes the file's bytes too. Mirrors and users' clients delete
their copies the next time they sync, and the post shows as "Removed by host: <reason>". A
remove can't be undone, and the record, including your reason, is public, so don't put
personal data in the reason. Removing content doesn't take back copies someone
already downloaded or screenshotted. Report illegal material to the authorities where the
law requires it.

## File limits (Storage Sellers)

`srnet-host init --type files … --max-file-mb 25 --quota-mb 500` sets the largest file and
the MiB each uploader key may store (0 means no quota). Change them later with
`srnet-host files --prefix … --max-file-mb 50`. Make sure your disk can hold the total.

## What your host does and doesn't do

- You can hide, remove and pin posts (see "Moderating"). Every action is signed and public.
- Store buyers pay the seller's own address from their own wallet, then post a signed order
  naming the transaction, which the seller can check on chain.
- As a Storage Seller you store files the SRNet client encrypted on the uploader's computer
  with ChaCha20-Poly1305, unless the uploader chose to publish a file unencrypted.
- Coming soon: Storage Sellers will be able to turn off public hosting, so they hold only
  encrypted files they can't read.
- You are responsible for what you host under your local laws.

## Details

### .sesh key files

`--sesh-import` accepts a 32-byte seed or a 64-byte seed+public key (as hex or raw bytes), or a
`d1:s64:…e` identity file.

### One .sesh address for several hosts

To run rooms, a directory, files and mail on one server under one `.sesh` address:

    srnet-host init --type rooms --name lobby --sesh skip        # ... and directory, files, mail
    # approve each request.json on your computer, then install-delegation on each
    srnet-host front --sesh-import name.key \
        --host /opt/srnet-host/lobby --host /opt/srnet-host/directory \
        --host /opt/srnet-host/files --host /opt/srnet-host/mail

`front` starts two services: `srnet-front-router` (the name) and `srnet-front`, which sends
each request to the host serving it. Each host's `link` then prints links on that name. Open
tcp/80 on `sr-front` only: `sudo ufw allow in on sr-front to any port 80 proto tcp`.
A board host serves at `/`, so it needs a name of its own: run `front` with the board as the
only `--host`.

With systemd, `front` enables both units so they start at boot. Pass `--no-systemd` to only
write the unit files to the front directory and start them yourself, or turn off autostart
later with `sudo systemctl disable srnet-front-router srnet-front`.

#### Other local services on the same address (`--route`)

`--route /NAME=PORT` (repeatable) also forwards `/NAME/...` to `127.0.0.1:PORT`, so another
local service is reachable over Session Router:

    srnet-host front --sesh-import name.key \
        --host /opt/srnet-host/lobby --host /opt/srnet-host/mail --route /donate=48922

Re-run `front` with the same `--route` options whenever you change the hosts (routes not given
are dropped).
