# Third-party notices for the EE-free Evalith workbench

The workbench is generated from Rhesis AI GmbH's MIT-licensed core at commit
`ce24bb1993fc545bb0ccb0d8b3951683ac14fff1` (`VERSION` 0.20.1). The upstream
`LICENSE` and `NOTICE` files are copied verbatim into the generated tree and must
ship with any distributed source or image.

Evalith modifications are limited to the automated patch list in
`workbench/build.py`:

- removed the non-MIT `/ee/` directory entirely (not copied into the tree);
- removed the optional `ee` Python extra, the `rhesis-backend-ee` path source,
  the `@rhesis/ee-frontend` dependency, and the EE transpile/bootstrap entries;
- removed upstream brand artwork under `public/logos/`, `public/elements/`,
  `public/auth/hero-wash.png`, `public/avatar.png`, `public/background.png`, and
  replaced visible brand marks with `public/evalith-mark.svg`;
- replaced the Rhesis legal imprint and terms links with an internal-validation
  notice;
- disabled product telemetry and Rhesis platform-key/SaaS defaults in the
  provided run configuration and seeded data.

Upstream NOTICE obligations (Apache-2.0 components, OpenTelemetry, Transformers,
garak, deepeval, deepteam) remain in the copied `NOTICE`. OWASP Top 10 for LLM
Apps material is CC BY-SA 4.0; it is kept with attribution and the
non-endorsement statement from the upstream NOTICE. The base images and Python
dependencies keep their own licenses; see the upstream NOTICE and each
dependency's metadata.

Known gaps intentionally left for follow-up, not claimed as complete:

- the upstream `Sora`, `Sometype Mono` and `Geist` font files ship without OFL
  text; Evalith must add the font licenses or replace the families before any
  public image distribution;
- some in-copy references to Rhesis (documentation links, attribution strings)
  remain where they identify upstream provenance rather than Evalith branding;
- no image is published by this repository, so MIT/Apache notice inclusion in a
  distributed image is still to be added when the image pipeline is finalized.
