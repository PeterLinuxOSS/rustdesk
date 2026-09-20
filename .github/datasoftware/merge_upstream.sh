#!/usr/bin/env bash
#
# Merge an upstream RustDesk release into the DataSoftware branch.
#
#   .github/datasoftware/merge_upstream.sh <upstream-tag>
#
# Used by .github/workflows/datasoftware-upstream-sync.yml and safe to run by
# hand. It does the mechanical part of DATASOFTWARE_BUILD.md section 8 and
# refuses to produce anything that silently breaks the customisation.
#
# Behaviour:
#   * A clean merge is committed and the customisation checks are run.
#   * Cargo.toml / Cargo.lock conflict on every upstream release, because
#     upstream bumps the version and we carry our own "-N" build suffix. That
#     one conflict is resolved automatically: take upstream's files, then set
#     the version to "<upstream version>-1". Those are the only lines we
#     change in them, so nothing of ours is lost.
#   * Any other conflict is left for a human. The merge is aborted and the
#     conflicting paths are reported, because guessing at a conflict in
#     src/common.rs is exactly how the auto-updater ends up pointing back at
#     rustdesk/rustdesk.
#
# Outputs (when run under GitHub Actions, also written to $GITHUB_OUTPUT):
#   status=merged|conflict|up-to-date
#   version=<the new DataSoftware version>
#   conflicts=<space separated paths>

set -euo pipefail

TAG="${1:?usage: merge_upstream.sh <upstream-tag>}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

# CI runners ship `python3`, Git Bash on Windows ships `python`. Probe by
# actually running it: Windows puts a `python3` App Execution Alias on PATH
# that only prints "Python was not found" and exits non-zero, so merely
# finding the name on PATH proves nothing.
PYTHON=""
for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c "import sys; sys.exit(0)" >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "Need a working python3 or python on PATH." >&2
    exit 2
fi
echo "Using ${PYTHON}"

# Never leave a half-finished merge behind: an interrupted run would otherwise
# strand the working tree in a conflicted state.
cleanup_on_error() {
    status=$?
    if [ "$status" -ne 0 ] && [ -e "$(git rev-parse --git-dir)/MERGE_HEAD" ]; then
        echo "Aborting the in-progress merge after an error." >&2
        git merge --abort || true
    fi
    exit "$status"
}
trap cleanup_on_error EXIT

emit() {
    echo "$1=$2"
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        echo "$1=$2" >>"$GITHUB_OUTPUT"
    fi
}

if ! git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
    echo "Unknown tag ${TAG}. Fetch upstream tags first." >&2
    exit 2
fi

if git merge-base --is-ancestor "$TAG" HEAD; then
    echo "${TAG} is already merged."
    emit status up-to-date
    exit 0
fi

echo "Merging upstream ${TAG} ..."
if git merge --no-commit --no-ff "$TAG"; then
    CONFLICTS=""
else
    CONFLICTS="$(git diff --name-only --diff-filter=U | tr '\n' ' ' | sed 's/ $//')"
fi

# --- the expected, auto-resolvable conflict -------------------------------
VERSION_FILES="Cargo.toml Cargo.lock"
REMAINING=""
for f in $CONFLICTS; do
    case " $VERSION_FILES " in
        *" $f "*) ;;
        *) REMAINING="$REMAINING $f" ;;
    esac
done
REMAINING="$(echo "$REMAINING" | sed 's/^ *//')"

if [ -n "$REMAINING" ]; then
    echo "Conflicts need a human: $REMAINING" >&2
    git merge --abort
    emit status conflict
    emit conflicts "$REMAINING"
    exit 0
fi

# Take upstream's Cargo files wholesale; the version is the only thing we
# change in them, and it is re-applied right after.
for f in $CONFLICTS; do
    echo "Resolving $f in favour of upstream, then re-applying our version"
    git checkout --theirs -- "$f"
    git add -- "$f"
done

UPSTREAM_VERSION="$(git show "${TAG}:Cargo.toml" | grep -m1 '^version' | cut -d'"' -f2)"
if [ -z "$UPSTREAM_VERSION" ]; then
    echo "Could not read the upstream version from ${TAG}:Cargo.toml" >&2
    git merge --abort
    exit 1
fi
NEW_VERSION="${UPSTREAM_VERSION%%-*}-1"

"$PYTHON" .github/datasoftware/set_version.py "$NEW_VERSION"
git add Cargo.toml Cargo.lock

# An upstream release usually moves the hbb_common submodule pointer. Check
# out the new commit before verifying, otherwise the checks below inspect the
# previous hbb_common and pass for the wrong reason.
git submodule update --init --recursive

# --- the customisation must still be intact -------------------------------
# Run before committing, so a broken merge never lands as a commit.
if ! "$PYTHON" .github/datasoftware/check_customisation.py; then
    echo "" >&2
    echo "The merge compiles away part of the DataSoftware customisation." >&2
    echo "Aborting. See DATASOFTWARE_BUILD.md section 8." >&2
    git merge --abort
    emit status conflict
    emit conflicts "customisation-check-failed"
    exit 0
fi

git commit -q --no-edit -m "Merge upstream RustDesk ${TAG} into the DataSoftware client

Version set to ${NEW_VERSION}: upstream moved to ${UPSTREAM_VERSION} and the
DataSoftware build suffix restarts at -1.

.github/datasoftware/check_customisation.py passes, so the branding, the
built-in server configuration and the update redirect survived the merge.
The Windows build still has to be run and the client tested on Windows."

echo "Merged ${TAG} as ${NEW_VERSION}"
emit status merged
emit version "$NEW_VERSION"
emit conflicts ""
