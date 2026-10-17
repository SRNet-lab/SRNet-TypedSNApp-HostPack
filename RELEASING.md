# Releasing (maintainers)

    ./scripts/make_release.sh <signing-key> [outdir]      # default outdir: dist/

This builds `srnet-hostpack-<ver>.tar.gz` from committed files (`git archive`), then writes
`SHA256SUMS` and a detached SSH signature `SHA256SUMS.sig` (namespace `srnet-release`,
identity `release@srnet`) plus `allowed_signers`. Upload all four files to the GitHub release.

**Real releases are signed by the SRNet maintainers with the SRNet release key.** Any other key
(for example one made for testing) is a throwaway: its signatures must never be published.
Publish the real release public key in the README and on the GitHub profile, so hosts can check
`allowed_signers` against it.
