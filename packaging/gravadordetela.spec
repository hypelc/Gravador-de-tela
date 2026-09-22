Name:           gravadordetela
Version:        0.1.3
Release:        1%{?dist}
Summary:        Gravador de tela local para Fedora KDE Wayland
License:        MIT
BuildArch:      noarch

Requires:       python3
Requires:       python3-gobject
Requires:       gtk4
Requires:       gstreamer1
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
Requires:       gstreamer1-plugins-bad-free
Requires:       gstreamer1-plugin-openh264
Requires:       gstreamer1-plugin-libav
Requires:       pipewire-gstreamer
Requires:       pulseaudio-utils
Requires:       ffmpeg-free
Requires:       xdg-desktop-portal
Requires:       xdg-desktop-portal-kde

%description
Grava um monitor escolhido no KDE Wayland com microfone, áudio do sistema
e webcam opcionais. Pausa, salva em MP4 e recupera trechos após interrupção.

%prep

%build

%install
install -d "%{buildroot}%{_bindir}"
install -m 0755 "%{_sourcedir}/bin/gravadordetela" "%{buildroot}%{_bindir}/gravadordetela"
install -d "%{buildroot}%{_datadir}/gravadordetela/gravadordetela"
install -m 0644 "%{_sourcedir}"/src/gravadordetela/*.py "%{buildroot}%{_datadir}/gravadordetela/gravadordetela/"
install -d "%{buildroot}%{_datadir}/applications"
install -m 0644 "%{_sourcedir}/packaging/io.github.jeanlc77.GravadorDeTela.desktop" "%{buildroot}%{_datadir}/applications/"
install -d "%{buildroot}%{_datadir}/icons/hicolor/scalable/apps"
install -m 0644 "%{_sourcedir}/packaging/io.github.jeanlc77.GravadorDeTela.svg" "%{buildroot}%{_datadir}/icons/hicolor/scalable/apps/"
install -m 0644 "%{_sourcedir}/packaging/io.github.jeanlc77.GravadorDeTela-recording.svg" "%{buildroot}%{_datadir}/icons/hicolor/scalable/apps/"
install -m 0644 "%{_sourcedir}/packaging/io.github.jeanlc77.GravadorDeTela-paused.svg" "%{buildroot}%{_datadir}/icons/hicolor/scalable/apps/"
install -d "%{buildroot}%{_datadir}/licenses/gravadordetela"
install -m 0644 "%{_sourcedir}/LICENSE" "%{buildroot}%{_datadir}/licenses/gravadordetela/"

%files
%{_bindir}/gravadordetela
%{_datadir}/gravadordetela/
%{_datadir}/applications/io.github.jeanlc77.GravadorDeTela.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.jeanlc77.GravadorDeTela.svg
%{_datadir}/icons/hicolor/scalable/apps/io.github.jeanlc77.GravadorDeTela-recording.svg
%{_datadir}/icons/hicolor/scalable/apps/io.github.jeanlc77.GravadorDeTela-paused.svg
%license %{_datadir}/licenses/gravadordetela/LICENSE

%changelog
* Tue Sep 22 2026 Codex <noreply@localhost> - 0.1.3-1
- Add portable H.264 software fallback and relocatable launcher
- Prepare cross-distribution Flatpak packaging

* Tue Sep 22 2026 Codex <noreply@localhost> - 0.1.2-1
- Use the current GStreamer VA-API H.264 encoder on Intel i965
- Enable the i965 driver automatically when it is installed

* Mon Sep 21 2026 Codex <noreply@localhost> - 0.1.1-1
- Keep microphone input from taking over the recording clock

* Mon Sep 21 2026 Codex <noreply@localhost> - 0.1.0-1
- Initial local Fedora KDE Wayland recorder
