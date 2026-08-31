#!/usr/bin/env bash
# Cut a semver release of one component: bump the version, run checks, commit, tag.
#
# Usage: scripts/release.sh <mediagrab|bot> <MAJOR.MINOR.PATCH>
#
# Tags: mediagrab-vX.Y.Z (library — CI builds a wheel and attaches it to a
# GitHub Release) and bot-vX.Y.Z (bot — CI builds the Docker image and pushes
# it to GHCR as X.Y.Z, X.Y and latest). Push with:
#   git push origin master --follow-tags
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }

[[ $# -eq 2 ]] || die "usage: scripts/release.sh <mediagrab|bot> <MAJOR.MINOR.PATCH>"
component="$1"
version="$2"

[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || die "'$version' is not semver MAJOR.MINOR.PATCH (e.g. 1.2.3)"

case "$component" in
    mediagrab) pyproject="packages/mediagrab/pyproject.toml"; tag="mediagrab-v$version" ;;
    bot)       pyproject="bot/pyproject.toml";                tag="bot-v$version" ;;
    *)         die "unknown component '$component' (expected mediagrab or bot)" ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

git diff --quiet && git diff --cached --quiet || die "working tree not clean; commit or stash first"
git rev-parse -q --verify "refs/tags/$tag" >/dev/null && die "tag $tag already exists"

current="$(python3 -c "import tomllib;print(tomllib.load(open('$pyproject','rb'))['project']['version'])")"
[[ "$version" != "$current" ]] || die "$component is already at $version"

python3 - "$pyproject" "$version" <<'PY'
import pathlib, re, sys

path, ver = pathlib.Path(sys.argv[1]), sys.argv[2]
text = path.read_text(encoding="utf-8")
new = re.sub(r'(?m)^version = ".*"$', f'version = "{ver}"', text, count=1)
assert new != text, f"no version line found in {path}"
path.write_text(new, encoding="utf-8")
PY

echo "→ $component: $current → $version"
uv sync --quiet
uv run ruff check --quiet .
uv run pytest --quiet

git add "$pyproject" uv.lock
git commit --quiet -m "Release $component v$version"
git tag -a "$tag" -m "Release $component v$version"

echo "Tagged $tag. Push the release with:"
echo "  git push origin master --follow-tags"
