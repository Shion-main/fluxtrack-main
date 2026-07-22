# Vendored browser runtime

These are exact, unmodified files from the named npm releases. Licenses are
stored beside each package. `config.tests.VendoredFrontendTests` pins SHA-256
hashes so an upgrade is an explicit reviewed change rather than an invisible CDN
change.

| Package | Version | Runtime files |
|---|---:|---|
| `htmx.org` | 2.0.6 | `htmx.min.js` |
| `html5-qrcode` | 2.3.8 | `html5-qrcode.min.js` |
| `franken-ui` | 2.1.2 | core/utilities CSS, core/icon IIFE JavaScript |

To upgrade, fetch the exact npm tarball, inspect its package manifest and license,
copy only the required distribution files, update template paths and expected
hashes, then run `collectstatic` plus the scanner/browser smoke tests.
