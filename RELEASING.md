# Releasing (maintainers)

    ./scripts/make_release.sh <signing-key> [outdir]      # default outdir: dist/

This builds `srnet-hostpack-<ver>.tar.gz` from committed files (`git archive`), then writes
`SHA256SUMS` and a detached SSH signature `SHA256SUMS.sig` (namespace `srnet-release`,
identity `release@srnet`) plus `allowed_signers`. Upload all four files to the GitHub release.

Releases are signed by the SRNet maintainers with the SRNet release key. Signatures made with
any other key must never be published. The release public key is published alongside the first
signed release, so hosts can check `allowed_signers` against it.
