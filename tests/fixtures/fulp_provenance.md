# FULP fixture provenance

`fulp_listing_observed.html` and the six `fulp_detail_*.html` files are
reduced deterministic fixtures based on the public `https://www.fulp.es/ofertas`
listing and the six public detail URLs inspected on 2026-09-16. They retain
the observed `.panel_ofertas .row.oferta` listing fields, duplicate type
badges, `.Content-Oferta` root, `.container-details` summary, section classes,
canonical/`og:url` identity, and the four observed opportunity-type families.

The fixture descriptions and some dates are reduced or synthetic mutations;
they are not claims about the current availability of those offers. Tests that
exercise redirects, identity conflicts, malformed rows, deadlines, nested
foreign records, totals, budgets, and unsupported continuation use synthetic
HTML or injected responses and are labelled as such in the test modules.
