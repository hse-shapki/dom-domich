"""Воспроизводимый audit/manifest без создания или перемещения Git tag."""

import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SecretFinding:
    source: str
    pattern: str


_ASSIGNMENT = re.compile(
    r"(?m)^[ \t]*(MAX_BOT_TOKEN|MAX_WEBHOOK_SECRET|POSTGRES_PASSWORD)[ \t]*="
    r"[ \t]*([^\s#]+)"
)
_STRUCTURED_ASSIGNMENT = re.compile(
    r"(?m)^[ \t]*[\"']?(MAX_BOT_TOKEN|MAX_WEBHOOK_SECRET|POSTGRES_PASSWORD)[\"']?"
    r"[ \t]*:[ \t]*[\"']?([^\s#\"']+)"
)
_DATABASE_CREDENTIAL = re.compile(r"postgres(?:ql)?(?:\+asyncpg)?://[^\s:/]+:([^@\s]+)@")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_PLACEHOLDERS = {
    "change-me",
    "example",
    "password",
    "pass",
    "secret",
    "secret-token",
    "test",
    "<redacted>",
}


def _looks_real(value: str) -> bool:
    if value.startswith("${"):
        return False
    normalized = value.strip("'\"${}").lower()
    return (
        bool(normalized) and normalized not in _PLACEHOLDERS and not normalized.endswith(".invalid")
    )


def scan_text_for_secrets(text: str, source: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    if _PRIVATE_KEY.search(text):
        findings.append(SecretFinding(source, "private_key"))
    for match in (*_ASSIGNMENT.finditer(text), *_STRUCTURED_ASSIGNMENT.finditer(text)):
        if _looks_real(match.group(2)):
            findings.append(SecretFinding(source, f"non_placeholder_{match.group(1).lower()}"))
    for match in _DATABASE_CREDENTIAL.finditer(text):
        if _looks_real(match.group(1)):
            findings.append(SecretFinding(source, "database_password_in_url"))
    return findings


def _git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], check=True, text=True, capture_output=True).stdout


def audit_repository() -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for name in _git("ls-files", "--cached", "--others", "--exclude-standard").splitlines():
        path = Path(name)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(scan_text_for_secrets(text, name))
    history = _git("log", "-p", "--all", "--no-ext-diff", "--format=commit:%H")
    commit = "unknown"
    for line in history.splitlines():
        if line.startswith("commit:"):
            commit = line.removeprefix("commit:")[:12]
        elif line.startswith(("+++", "---")):
            continue
        elif line.startswith(("+", "-")):
            findings.extend(scan_text_for_secrets(line[1:], f"history:{commit}"))
    return sorted(set(findings), key=lambda item: (item.source, item.pattern))


def dependency_inventory() -> list[dict[str, str]]:
    inventory: list[dict[str, str]] = []
    for distribution in importlib.metadata.distributions():
        metadata = distribution.metadata
        license_name = metadata.get("License-Expression") or metadata.get("License")
        if not license_name:
            classifiers = metadata.get_all("Classifier") or []
            license_classifiers = [
                classifier.removeprefix("License :: ")
                for classifier in classifiers
                if classifier.startswith("License :: ")
            ]
            license_name = "; ".join(license_classifiers) or "UNKNOWN"
        inventory.append(
            {
                "name": metadata.get("Name", "UNKNOWN"),
                "version": distribution.version,
                "license": " ".join(license_name.split()),
            }
        )
    return sorted(inventory, key=lambda item: item["name"].lower())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_release_evidence(output: Path, images: list[str]) -> None:
    parsed_images: dict[str, str] = {}
    for image in images:
        name, separator, digest = image.partition("=")
        if not separator or not digest.startswith("sha256:") or len(digest) != 71:
            raise ValueError("image must be NAME=sha256:<64 hex>")
        int(digest.removeprefix("sha256:"), 16)
        parsed_images[name] = digest
    if _git("status", "--porcelain").strip():
        raise RuntimeError("release evidence requires a clean worktree")
    output.mkdir(parents=True, exist_ok=False)
    commit = _git("rev-parse", "HEAD").strip()
    archive = output / f"dom-domych-{commit[:12]}.tar.gz"
    subprocess.run(
        ["git", "archive", "--format=tar.gz", "--output", str(archive), commit], check=True
    )
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "commit": commit,
        "archive": archive.name,
        "archive_sha256": sha256_file(archive),
        "uv_lock_sha256": sha256_file(Path("uv.lock")),
        "migration_heads": subprocess.run(
            ["uv", "run", "alembic", "heads"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.splitlines(),
        "images": parsed_images,
    }
    (output / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("secrets")
    licenses = subparsers.add_parser("licenses")
    licenses.add_argument("--output", type=Path, required=True)
    evidence = subparsers.add_parser("evidence")
    evidence.add_argument("--output", type=Path, required=True)
    evidence.add_argument("--image", action="append", default=[])
    arguments = parser.parse_args()
    if arguments.command == "secrets":
        findings = audit_repository()
        print(json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2))
        if findings:
            raise SystemExit(1)
    elif arguments.command == "licenses":
        arguments.output.write_text(
            json.dumps(dependency_inventory(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        create_release_evidence(arguments.output, arguments.image)


if __name__ == "__main__":
    main()
