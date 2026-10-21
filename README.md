# SRNet host pack

**What's new**

- No developer fee anywhere in SRNet.
- Simpler store payments: buyers pay the seller's own address straight from their own wallet. No
  balance, no contract and no escrow.
- Exits now have their own repository,
  [SRNet-VPSHost-ExitPack](https://github.com/SRNet-lab/SRNet-VPSHost-ExitPack).

Full history: [CHANGELOG.md](CHANGELOG.md)

Run your own SRNet community host: a **message board, store, wiki, chat rooms, file drop, profile
directory, community directory or mail host**. The apps are built into the SRNet client. Your server just stores and
serves signed data. Your root key stays offline, and the host listens only on `127.0.0.1`
until you choose to open it up through your own `.sesh` name.

This is beta software. Stores never handle money: buyers pay the seller's own address from
their own wallet, and your server only stores the signed listings and orders.

Hosting a file drop makes you a Storage Seller. The SRNet client encrypts files on the
uploader's computer with ChaCha20-Poly1305 before upload, unless the uploader chooses to publish
a file unencrypted, so with encryption on you store only ciphertext. Mail is sealed the same way
on the sender's computer, so a mail host can't read the mail it holds.

**Coming soon:** Storage Sellers will be able to turn off public hosting, so they hold only
encrypted files they can't read.

SRNet is an independent project. It is not affiliated with or endorsed by the Session Foundation
or the Session Technology Foundation.

Running a mail host? It's open to new inboxes by default (cap 1000); close sign-up any time with
`srnet-host mail --prefix <dir> --closed`. See *Running a mail host* in `docs/HOST-GUIDE.md`.

Guide: [Typed SNApps: an illustrated walkthrough](docs/Typed-SNApps-Walkthrough.pdf) (PDF), a
screen-by-screen tour of the client, ending with how to run a host.

## Install

On the server (Debian or Ubuntu; Python 3.10 or newer):

```sh
cd ~
sudo apt update
sudo apt install -y git curl python3 python3-cryptography
git clone https://github.com/SRNet-lab/SRNet-TypedSNApp-HostPack.git
cd SRNet-TypedSNApp-HostPack
```

Your root key lives on a separate, offline machine. Clone the same repository there too (only
`python3` and `python3-cryptography` are needed).

Then follow [docs/HOST-GUIDE.md](docs/HOST-GUIDE.md). The short version, run from the
`SRNet-TypedSNApp-HostPack` folder:

    ./bin/srnet-host root init                    # on your OFFLINE machine
    sudo ./bin/srnet-host init --type rooms --name lobby --sesh new  # on the server
    ./bin/srnet-host root sign request.json --days 90               # offline machine
    sudo ./bin/srnet-host install-delegation delegation.json --prefix /opt/srnet-host/lobby
    # install Session Router (below), then:
    sudo ./bin/srnet-host front --sesh-import /opt/srnet-host/lobby/sesh/identity.key \
        --host /opt/srnet-host/lobby                                 # the .sesh name
    sudo ufw allow in on sr-front to any port 80 proto tcp
    sudo ./bin/srnet-host status --prefix /opt/srnet-host/lobby
    ./bin/srnet-host link --prefix /opt/srnet-host/lobby             # invite links to share

Types: `board`, `store`, `wiki`, `rooms` (`--room` adds more rooms), `files`, `people`,
`directory`, `mail`. Later: `renew`, `upgrade`, `backup`, `mail --closed/--open`,
`root directory-entry` + `directory-submit` to list your community in a directory, and `front`
to serve several hosts under one `.sesh` name.

To give your host a `.sesh` name, install the SRNet build of Session Router
([Session-Router-SRNet](https://github.com/SRNet-lab/Session-Router-SRNet), the same one the
SRNet client uses) on the server and run `srnet-host front`. On Ubuntu 24.04:

```sh
cd /tmp
curl -fLO https://github.com/SRNet-lab/Session-Router-SRNet/releases/download/v1.1.0-srnet6/session-router-srnet_1.1.0+srnet6_amd64.deb
echo "5c1c9b553b25649657f9f8e3ae0431aa3fe0534c82e65214588c728307bf3237  session-router-srnet_1.1.0+srnet6_amd64.deb" | sha256sum -c \
  && sudo apt install -y ./session-router-srnet_1.1.0+srnet6_amd64.deb \
  && sudo apt-mark hold session-router-srnet
cd ~/SRNet-TypedSNApp-HostPack
```

The server does not need the SRNet client. *Letting people in* in the guide has the rest.

Signed release tarballs (see [RELEASING.md](RELEASING.md)) are not published yet; install from git.

## Contents

| Path | What |
|---|---|
| `bin/srnet-host` | installer / operator tool |
| `mbfmt/ mbhost/ typed/ mbclient/` | host code (and a minimal client used by `scripts/demo.py`) |
| `docs/HOST-GUIDE.md` | step-by-step guide |
| `docs/LICENSES.md` | licence notes |
| `tests/` | automated tests |
| `RELEASING.md` | how maintainers build and sign releases |

## Related repositories

- [SRNet-Desktop](https://github.com/SRNet-lab/SRNet-Desktop): the SRNet client people use to
  join your host, read and post, and send mail.
- [Session-Router-SRNet](https://github.com/SRNet-lab/Session-Router-SRNet): the Session Router
  build the client runs, with exit mapping added.
- [SRNet-VPSHost-ExitPack](https://github.com/SRNet-lab/SRNet-VPSHost-ExitPack): run a paid
  exit on an Ubuntu server.

## License

MIT. See [LICENSE](LICENSE) and [docs/LICENSES.md](docs/LICENSES.md).

## Donations

If SRNet is useful to you, donations are welcome at
`0xec4fEECa354C7eabbe8957a23c361Aa365E3b377` (USDC or ETH on Arbitrum One or Base).
