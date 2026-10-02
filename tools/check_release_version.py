from __future__ import annotations

import argparse
import ast
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_package_version(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "__version__" for target in statement.targets):
            if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                return statement.value.value
    raise ValueError(f"Version introuvable dans {path}")


def validate_release_version(tag: str, root: Path = ROOT) -> str:
    normalized_tag = tag.strip()
    if not normalized_tag.startswith("v") or len(normalized_tag) == 1:
        raise ValueError(f"Tag de release invalide: {tag!r}. Format attendu: vX.Y.Z")

    tag_version = normalized_tag[1:]
    with (root / "pyproject.toml").open("rb") as handle:
        project_version = str(tomllib.load(handle)["project"]["version"])
    package_version = read_package_version(root / "perspectiv" / "version.py")

    versions = {
        "tag": tag_version,
        "pyproject.toml": project_version,
        "perspectiv/version.py": package_version,
    }
    if len(set(versions.values())) != 1:
        details = ", ".join(f"{source}={version}" for source, version in versions.items())
        raise ValueError(f"Publication incoherente: {details}")
    return tag_version


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifie la coherence des versions avant une release.")
    parser.add_argument("--tag", required=True, help="Tag cible, par exemple v0.3.6")
    args = parser.parse_args()
    try:
        version = validate_release_version(args.tag)
    except (KeyError, OSError, SyntaxError, ValueError) as exc:
        print(f"ERREUR: {exc}", file=sys.stderr)
        return 1
    print(f"Version de release coherente: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
