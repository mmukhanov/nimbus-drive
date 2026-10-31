# AUR package

`PKGBUILD` and `.SRCINFO` for <https://aur.archlinux.org/packages/nimbus-drive>.

The build and package steps were dry-run on Ubuntu; the package has not been built with
`makepkg` on Arch yet. Before the first upload, on an Arch machine:

```bash
makepkg -si            # builds and installs; check that `nimbus-drive tray` starts
namcap PKGBUILD *.pkg.tar.zst
makepkg --printsrcinfo > .SRCINFO
```

Uploading needs an AUR account with an SSH key:

```bash
git clone ssh://aur@aur.archlinux.org/nimbus-drive.git aur-nimbus-drive
cp PKGBUILD .SRCINFO aur-nimbus-drive/
cd aur-nimbus-drive && git add PKGBUILD .SRCINFO && git commit -m "nimbus-drive 0.1.0" && git push
```

For a new release: bump `pkgver`, reset `pkgrel=1`, update `sha256sums`
(`curl -sL <tarball url> | sha256sum`) and regenerate `.SRCINFO`.
