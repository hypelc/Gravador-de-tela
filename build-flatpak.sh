#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "$0")" && pwd)
version=${1:-0.1.3}
arch=$(flatpak --default-arch)
output="$project_dir/dist/io.github.jeanlc77.GravadorDeTela-${version}-${arch}.flatpak"
if [[ -e "$output" ]]; then
    printf 'O arquivo ja existe: %s\n' "$output" >&2
    exit 1
fi

build_root=$(mktemp -d -t gravadordetela-flatpak-XXXXXX)
cleanup() {
    if [[ "$build_root" == /tmp/gravadordetela-flatpak-* && -d "$build_root" ]]; then
        rm -r -- "$build_root"
    fi
}
trap cleanup EXIT

flatpak build-init "$build_root/app" io.github.jeanlc77.GravadorDeTela \
    org.gnome.Platform org.gnome.Platform 50
flatpak build --filesystem="$project_dir:ro" --env=GDT_SRC="$project_dir" \
    "$build_root/app" sh -e -c '
install -Dm755 "$GDT_SRC/bin/gravadordetela" /app/bin/gravadordetela
install -d /app/share/gravadordetela/gravadordetela
install -m644 "$GDT_SRC"/src/gravadordetela/*.py /app/share/gravadordetela/gravadordetela/
install -Dm644 "$GDT_SRC/packaging/io.github.jeanlc77.GravadorDeTela.desktop" /app/share/applications/io.github.jeanlc77.GravadorDeTela.desktop
install -Dm644 "$GDT_SRC/packaging/io.github.jeanlc77.GravadorDeTela.svg" /app/share/icons/hicolor/scalable/apps/io.github.jeanlc77.GravadorDeTela.svg
install -Dm644 "$GDT_SRC/packaging/io.github.jeanlc77.GravadorDeTela-recording.svg" /app/share/icons/hicolor/scalable/apps/io.github.jeanlc77.GravadorDeTela-recording.svg
install -Dm644 "$GDT_SRC/packaging/io.github.jeanlc77.GravadorDeTela-paused.svg" /app/share/icons/hicolor/scalable/apps/io.github.jeanlc77.GravadorDeTela-paused.svg
install -Dm644 "$GDT_SRC/LICENSE" /app/share/licenses/gravadordetela/LICENSE
'
flatpak build-finish "$build_root/app" --command=gravadordetela \
    --sdk=org.gnome.Sdk --socket=wayland --socket=fallback-x11 \
    --socket=pulseaudio --share=ipc --device=all --filesystem=home \
    --talk-name=org.kde.StatusNotifierWatcher
flatpak build-export "$build_root/repo" "$build_root/app" stable
mkdir -p "$project_dir/dist"
flatpak build-bundle \
    --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
    "$build_root/repo" "$output" io.github.jeanlc77.GravadorDeTela stable
printf 'Flatpak pronto: %s\n' "$output"
