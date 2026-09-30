"""A03/A11: explicit combined trust for MAX API and upload CDN."""

from dom_domych.infrastructure.max.tls import max_ssl_context


def test_max_ssl_context_contains_mozilla_and_russian_trust_roots() -> None:
    subjects = {
        tuple(name for group in certificate["subject"] for name in group)
        for certificate in max_ssl_context().get_ca_certs()
    }

    assert any(("commonName", "ISRG Root X1") in subject for subject in subjects)
    assert (
        ("countryName", "RU"),
        ("organizationName", "The Ministry of Digital Development and Communications"),
        ("commonName", "Russian Trusted Root CA"),
    ) in subjects
