JOEY MEIJER SUPPORT — WINDOWS X64

Variants
  support: incoming-only UI and RustDesk's existing incoming-only connection gate.
  admin: normal incoming/outgoing functionality; no extra server privileges.
Both embed support.joeymeijer.nl, relay port 21117 and the public server key in
src/joey_branding.rs. No password, private key or unattended-access credential is
embedded. The admin download is intentionally public.

Compatibility
  Executable inside the portable package: rustdesk.exe
  Service/config/IPC identity: RustDesk
  This keeps the existing --silent-install, --config and --get-id deployment
  commands and existing IDs/passwords compatible. The two variants share that
  installation namespace: installing one replaces the other on the same PC.
  The customer build cannot start normal outgoing connections. The existing
  RustDesk switch-sides-back exception still follows upstream behavior.
  Pro account/address-book UI is disabled; recent connections remain available
  in the admin build. No Pro licence verification code is modified.

Branding
  Original JM mark, drawn as SVG, with matching Pillow PNG/ICO exports.
  Colors: #111827, #0F766E, #5EEAD4, #F59E0B.
  Regenerate on Windows with Pillow installed:
    python brand/joey-meijer/generate_assets.py
  A different licensed local font can be passed with --font. Font files are not
  redistributed. Artwork exports are committed, so CI does not need Pillow.

Build
  GitHub Actions: "Joey Meijer - Windows clients".
  Runs on pushes affecting the branding/workflow on master or manual dispatch.
  Reuses upstream bridge generation and the x64 window helper build. Bridge
  codegen is not run locally. Windows jobs build support/admin separately and
  run the joey_branding::tests regression test before packaging.
  The workflow publishes unsigned EXEs, ZIPs, checksums and the website package.
  Authenticode signing requires a separate certificate/service and is not
  configured. Do not instruct customers to bypass security warnings.

  For an already provisioned Windows build machine, in a disposable checkout:
    python brand/joey-meijer/prepare.py support
    python build.py --portable --flutter --skip-portable-pack --hwcodec --vram --joey-variant support
  Replace support with admin for the other variant. The upstream pinned MSVC,
  Flutter engine, Rust, bridge and vcpkg prerequisites are still required.
  prepare.py deliberately stages logo/icon/resource/theme changes in that build
  checkout; do not run it in a checkout containing unrelated edits.

Distribution and maintenance
  The original RustDesk AGPL-3.0 licence and copyright notices are retained.
  Release payloads include LICENCE.txt and SOURCE.txt with the exact source
  commit. Source is available at https://github.com/joeymeijer/rustdesk and must
  remain available to recipients. Clone with --recurse-submodules for the pinned
  submodule sources; the release git-archive snapshot omits submodule contents.
  Each release tag pins the root commit; dependencies/submodules follow upstream
  locks and workflow pins. RustDesk's external engine release URL is the upstream
  main engine asset, so this is not claimed to be a byte-reproducible build.

  Stock RustDesk update checks/automatic updates are disabled in these variants
  to prevent replacement by the unbranded release. Update by building a new
  release and distributing it through your deployment tool/download site.
  Update the embedded public key if the server key changes; website .env must
  describe the same server/key. Never embed a shared permanent password.

Existing runtime paths changed (regression surface)
  Cargo.toml: two opt-in features, neither enabled in stock builds.
  src/lib.rs: only registers the feature-gated branding module.
  src/core_main.rs: initializes branded settings immediately after custom-client
    loading, before service/UI startup. No effect without the branding feature.
  build.py: --joey-variant selects a feature, refuses non-Windows/non-Flutter use.
  flutter/lib/common.dart: window title reads the optional branding display name,
    otherwise falls back to the original RustDesk title.
  New prepare.py stages assets, FileDescription/ProductName and the accent color
    only in custom build checkouts. Copyright and technical identity stay intact.
  No hbb_common submodule changes, regenerated bridges or unrelated cleanup.

Website
  See deploy/download-site/LEESMIJ.txt. Root page serves the incoming client;
  /download/admin/ serves the normal admin client with no ACL.
