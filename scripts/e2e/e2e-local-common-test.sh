#!/usr/bin/env bash
# Focused regression test for semantic E2E certificate path comparison.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
. "$repo_root/scripts/e2e/e2e-local-common.sh"

test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
mkdir -p "$test_dir/state/nested"
printf 'test CA placeholder\n' >"$test_dir/state/smtp-ca.pem"

expected="$test_dir/state/smtp-ca.pem"
equivalent="$test_dir/state/nested/../smtp-ca.pem"
different="$test_dir/state/other-ca.pem"
printf 'other CA placeholder\n' >"$different"

e2e_same_regular_file "$expected" "$equivalent"
if e2e_same_regular_file "$expected" "$different"; then
    printf 'Different certificate files must not compare equal.\n' >&2
    exit 1
fi
if e2e_same_regular_file "$expected" "$test_dir/state/missing-ca.pem"; then
    printf 'A missing certificate file must not compare equal.\n' >&2
    exit 1
fi
printf 'e2e local certificate path comparison: PASS\n'
