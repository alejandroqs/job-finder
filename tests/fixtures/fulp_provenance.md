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

The `fulp_detail_108550.html` description and `Tareas` content preserve the
wording observed in one read-only fetch of the public detail URL on
2026-09-16, including the extracurricular internship type, degree-enrolment
condition, English requirement, Helpdesk work, and Microsoft 365 duties. The
long repeated-task case in `test_record_text_keeps_description_eligibility_before_long_optional_tasks`
is synthetic stress data; it is not presented as FULP wording and exists only
to prove that optional long sections cannot displace the captured eligibility
sentence from the first 1,500-character AI payload window.
