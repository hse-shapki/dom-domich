"""TLS trust for MAX API and its signed upload URLs."""

import hashlib
import ssl
from importlib.resources import files

import certifi

RUSSIAN_TRUSTED_ROOT_SHA256 = "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31"


def max_ssl_context() -> ssl.SSLContext:
    """Combine Mozilla roots with the CA required by the documented MAX endpoints."""

    context = ssl.create_default_context(cafile=certifi.where())
    resource = files("dom_domych.infrastructure.max").joinpath("certs/russian_trusted_root_ca.pem")
    certificate = resource.read_text(encoding="ascii")
    der = ssl.PEM_cert_to_DER_cert(certificate)
    if hashlib.sha256(der).hexdigest() != RUSSIAN_TRUSTED_ROOT_SHA256:
        raise RuntimeError("bundled MAX trust root fingerprint mismatch")
    context.load_verify_locations(cadata=certificate)
    return context
