#!/usr/bin/bash
set -euo pipefail

project_dir=$(cd "$(dirname "$0")" && pwd)
# Fedora's RPM post-processing tools do not all support spaces in BUILDROOT.
build_dir=$(mktemp -d -t gravadordetela-rpm-XXXXXX)
mkdir -p "$build_dir/BUILD" "$build_dir/BUILDROOT" "$build_dir/RPMS" \
    "$build_dir/SRPMS" "$build_dir/SOURCES" "$build_dir/SPECS" "$project_dir/dist"

rpmbuild -bb "$project_dir/packaging/gravadordetela.spec" \
    --define "_topdir $build_dir" \
    --define "_sourcedir $project_dir"

find "$build_dir/RPMS" -name '*.rpm' -exec cp -v '{}' "$project_dir/dist/" \;
