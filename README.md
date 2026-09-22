# Gravador de Tela

Aplicativo pessoal para Fedora 44 KDE Plasma no Wayland. A janela permite escolher
microfone, áudio do sistema, webcam, resolução, FPS e pasta. O monitor é escolhido
no diálogo do KDE ao iniciar a captura. O cursor aparece no vídeo.

## Instalar

```bash
bash build-rpm.sh
sudo dnf install dist/gravadordetela-0.1.3-1.fc44.noarch.rpm
```

Abra **Gravador de Tela** pelo menu. No primeiro uso, o KDE apresenta o diálogo
para registrar os atalhos globais sugeridos: **Ctrl+Shift+F9** para iniciar,
pausar e retomar; **Ctrl+Shift+F10** para terminar e salvar. Eles podem ser
alterados nesse diálogo ou nas configurações de atalhos do KDE.

Se estiver atualizando uma versão já aberta, clique em **Sair** no aplicativo
antes de instalar o novo RPM e abra-o novamente depois da instalação.

O destino inicial é a pasta XDG **Vídeos/Gravador de Tela**. A opção “Iniciar com
a sessão” cria uma entrada de inicialização automática do usuário. Fechar a
janela mantém o aplicativo na bandeja; o botão **Sair** encerra o programa.

## Gravação e recuperação

O arquivo final é MP4 com H.264 e AAC. A gravação ocorre em pequenos trechos
Matroska, montados em MP4 sem recodificação depois de terminar. Se o processo
for interrompido, abra o aplicativo e use **Recuperar gravação interrompida**.
Os trechos ficam em `~/.local/state/gravadordetela/sessions/` até a montagem
do MP4 ter sucesso.

O aplicativo usa VA-API quando o elemento H.264 está disponível; caso contrário,
usa OpenH264 ou x264 na CPU. No Fedora 44, o elemento atual `vah264enc` vem em
`gstreamer1-plugins-bad-free`, já listado como dependência do RPM. Na Intel HD
520, instale também `libva-intel-driver` do RPM Fusion Free. O aplicativo ativa
o driver i965 automaticamente quando ele está instalado; não é preciso definir
variáveis de ambiente para abrir pelo menu ou com a sessão.

Comece com 1080p/30 FPS. A opção 1080p/60 FPS continua disponível para testar,
mas o desempenho real depende do monitor, da câmera, do áudio e da carga do
computador. O teste sintético confirmou a codificação por hardware em 1080p/30;
ele não substitui uma gravação de tela real para verificar fluidez e áudio.

## Outras distribuições Linux (KDE Wayland)

O mesmo código tem um pacote Flatpak local. Gere com `bash build-flatpak.sh` e
instale com `flatpak install --user dist/io.github.jeanlc77.GravadorDeTela-0.1.3-x86_64.flatpak`.
É necessário ter o Flathub configurado para obter o runtime GNOME 50 caso ele
ainda não esteja instalado. O pacote usa portais para escolher o monitor e
registrar atalhos; dá acesso à pasta pessoal para permitir a escolha de outra
pasta de saída e aos dispositivos para webcam/VA-API. Essas permissões são
amplas porque esta é uma ferramenta pessoal; revise-as antes de distribuir.
No runtime testado, o encoder `vah264enc` ficou disponível. O aplicativo também
usa `x264enc` quando não há encoder VA-API/OpenH264. A captura real, a bandeja e
os atalhos do Flatpak ainda precisam ser validados em cada ambiente KDE.

## Executar a partir do código

```bash
PYTHONPATH=src python3 -m gravadordetela
```

O código usa GTK 4, GStreamer, PipeWire, os portais do desktop e FFmpeg.

## Windows (em desenvolvimento)

A pasta `windows/` contém a base Windows Forms trazida do antigo GravaTela,
agora com seleção de monitor e 30/60 FPS antes de começar. Ela mantém pausa,
salvamento MP4, bandeja, atalhos Ctrl+Shift+F9/F10 e recuperação de trechos.
O código compila para `win-x64` e os testes do núcleo passaram no Linux com
vídeo sintético. **Ainda não é um instalador nem uma versão equivalente ao
Linux**: faltam microfone, áudio do sistema, webcam e validação da captura real
em Windows 10/11. O projeto espera `ffmpeg.exe` em
`windows/src/GravaTela/tools/` quando for executado no Windows. Não use o
instalador antigo como se ele contivesse estas alterações.

Para repetir somente os testes do núcleo no Linux, com SDK .NET 10, FFmpeg e
FFprobe locais:

```bash
dotnet run --project windows/tests/GravaTela.Tests.csproj -c Release -- \
  /usr/bin/ffmpeg /usr/bin/ffprobe /tmp libopenh264
```
