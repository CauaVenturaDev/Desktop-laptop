# PeriShare

Compartilhamento de periféricos entre dois computadores pela rede local, com
duas funções:

1. **Teclado e mouse (KVM por software)** — use o teclado e o mouse de um
   computador para controlar o outro, alternando com um atalho
   (padrão: `Ctrl+Alt+End`).
2. **Áudio / fones de ouvido** — o som de um computador é transmitido pela
   rede e reproduzido nos fones conectados ao outro.

Compatível com **Linux** (foco em **Arch Linux**, em X11 **e Wayland/Hyprland**
via backend evdev) e **Windows 10/11**. As duas máquinas podem estar em
qualquer combinação de sistemas e ambientes gráficos (Arch ⇄ Arch, Arch ⇄
Windows, Hyprland ⇄ Qtile, etc.).

```
   DESKTOP (servidor/emissor)                LAPTOP (cliente/receptor)
  ┌──────────────────────────┐             ┌──────────────────────────┐
  │ teclado + mouse físicos  │──entrada──▶ │ cursor/teclas injetados  │
  │ som do sistema           │──áudio────▶ │ fones de ouvido          │
  │ perishare input-server   │    LAN      │ perishare input-client   │
  │ perishare audio-send     │             │ perishare audio-recv     │
  └──────────────────────────┘             └──────────────────────────┘
```

Os papéis são independentes: qualquer máquina pode ser servidora de entrada
e/ou emissora de áudio. O tráfego é autenticado por segredo compartilhado
(HMAC-SHA256) e cifrado com AES-256-GCM — teclas digitadas incluem senhas,
então não desative a cifragem sem motivo.

## Instalação

Requisito comum: **Python 3.11 ou mais novo**.

### Arch Linux

Opção A — pacote nativo (recomendada):

```bash
# Dependências do AUR (o makepkg NÃO as resolve sozinho — instale antes).
# python-evdev, python-cryptography e tk vêm dos repositórios oficiais.
yay -S python-pynput python-sounddevice
git clone https://github.com/CauaVenturaDev/Desktop-laptop.git
cd Desktop-laptop/packaging/arch
makepkg -si
```

> Se aparecer `target not found: python-sounddevice` (ou `python-pynput`), é
> porque essas duas dependências estão no AUR e o `makepkg -si` só resolve as
> dos repositórios oficiais. Instale-as antes com `yay -S python-pynput
> python-sounddevice` (ou outro auxiliar do AUR) e rode o `makepkg -si` de novo.

Opção B — pipx (puxa as dependências Python do PyPI, sem AUR):

```bash
sudo pacman -S python-pipx tk portaudio
git clone https://github.com/CauaVenturaDev/Desktop-laptop.git
pipx install ./Desktop-laptop
```

> **Wayland / Hyprland:** a função de teclado/mouse tem dois backends. O
> padrão (`pynput`) funciona em X11 e Windows. Para **Wayland (Hyprland,
> Sway, GNOME/KDE Wayland)** o app usa automaticamente o backend **`evdev`**,
> que opera em nível de kernel e funciona em qualquer compositor. Ele exige
> uma configuração de permissões única — veja
> [Backend de entrada e Wayland](#backend-de-entrada-e-wayland) abaixo. A
> função de áudio funciona em qualquer sessão, sem configuração extra.

### Windows 10 / 11

1. Instale o [Python 3.11+](https://www.python.org/downloads/) marcando
   **"Add python.exe to PATH"**. Reabra o PowerShell depois.
2. **Baixe o código** desta máquina. Sem Git configurado, o mais fácil é o ZIP:
   na página do repositório, botão verde **Code → Download ZIP**, e extraia
   (ex.: para `C:\Users\<você>\Desktop-laptop`). Com Git: `git clone <url>`.
3. **Entre na pasta do projeto** no PowerShell e rode o instalador. O caminho
   `packaging\windows\install.ps1` é relativo à pasta atual — se você não
   estiver dentro do projeto, dá o erro "arquivo não existe":

```powershell
cd C:\Users\<você>\Desktop-laptop      # a pasta onde você extraiu/clonou
dir packaging\windows\install.ps1      # confirme que o arquivo aparece
powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1
```

O script cria um ambiente isolado em `%LOCALAPPDATA%\perishare` e um atalho
`perishare.cmd`. Quando o Windows perguntar, **permita o Python no firewall
em redes privadas** (necessário só na máquina que atua como servidor/emissor).

## Configuração

Na primeira máquina:

```bash
perishare init
```

Isso cria o `config.toml` (Linux: `~/.config/perishare/`, Windows:
`%APPDATA%\perishare\`) com um segredo aleatório. **Copie esse mesmo arquivo
para a outra máquina** — o campo `secret` precisa ser idêntico nas duas — e,
na máquina cliente/receptora, ajuste `server_host` para o IP da outra
(descubra com `ip addr` no Linux ou `ipconfig` no Windows).

Veja todas as opções comentadas em [`config.example.toml`](config.example.toml).

## Uso

### Função 1 — teclado e mouse

Na máquina com os periféricos físicos (ex.: desktop):

```bash
perishare input-server
```

Na máquina a ser controlada (ex.: laptop):

```bash
perishare input-client
```

No **teclado da máquina servidora** (onde a captura acontece), pressione
**`Ctrl+Alt+End`** (configurável em `toggle_hotkey`) para enviar o
teclado/mouse para a máquina remota; pressione de novo para voltar. O atalho
é detectado só no servidor — não adianta pressioná-lo no cliente. Se a conexão
cair, o controle volta automaticamente para a máquina local e as teclas
pressionadas são soltas na remota.

> Evite `Ctrl+Alt+F1`…`F12` como atalho: no Linux são reservados para trocar
> de terminal virtual (TTY) e o kernel/X11 podem interceptá-los antes do app.
> Com o backend `evdev` no servidor, o atalho é lido direto do kernel, o que é
> mais confiável do que com `pynput` em X11.

### Backend de entrada e Wayland

A função de teclado/mouse tem dois backends, escolhidos por `backend` em
`[input]` (padrão `"auto"`):

| Backend | Onde funciona | Permissões |
|---|---|---|
| `pynput` | X11 e Windows 10/11 | nenhuma |
| `evdev` | **Linux em nível de kernel**: Wayland (Hyprland/Sway/GNOME/KDE), X11 e console | grupo `input` + regra udev |

Com `"auto"`: Windows e Linux/X11 usam `pynput`; Linux/Wayland usa `evdev`.
Assim, no seu caso (**Arch Hyprland ⇄ Arch Qtile**) tudo funciona: o lado
Hyprland usa `evdev` e o lado Qtile pode usar qualquer um dos dois.

**Habilitar o backend evdev (uma vez por máquina):**

```bash
perishare input-devices              # diagnóstico: dispositivos e permissões
./packaging/linux/setup-permissions.sh   # script interativo, pede confirmação
```

O script pergunta antes de cada passo e nunca sobrescreve nada sem confirmar.
Se preferir fazer manualmente:

```bash
sudo usermod -aG input $USER         # e refaça o login
sudo cp packaging/linux/99-perishare-uinput.rules /etc/udev/rules.d/
sudo cp packaging/linux/perishare-uinput.conf     /etc/modules-load.d/
sudo modprobe uinput
sudo udevadm control --reload-rules && sudo udevadm trigger
```

(Instalando pelo pacote do Arch, a regra udev e o módulo já vão junto; só
falta entrar no grupo `input`.)

**Segurança do backend evdev.** Para suprimir a entrada local no modo remoto,
o `evdev` captura o teclado/mouse com exclusividade (*grab*). Isso é feito com
várias travas de segurança para você nunca ficar "trancado":

- o *grab* só acontece no **modo remoto**; no modo local a máquina é sua;
- o **atalho de alternância** é lido direto do kernel e sempre libera o
  controle, mesmo com o *grab* ativo;
- **qualquer** saída (atalho, `Ctrl+C`, `stop`, `SIGTERM`, queda da conexão)
  libera o *grab*; e se o processo morrer, o kernel o libera sozinho — não há
  como ficar preso com o programa encerrado;
- quem prefere zero risco pode usar `grab = false`: a entrada vai para as duas
  máquinas ao mesmo tempo (sem suprimir a local).

O dispositivo virtual de injeção (lado cliente) não interfere no seu teclado
físico. Fidelidade máxima é entre Linux ⇄ Linux (envia o código de tecla do
kernel); para Windows/X11 há um mapa de layout US para letras e símbolos.

### Função 2 — áudio / fones

Primeiro escolha os dispositivos com:

```bash
perishare devices
```

Na máquina cujo som deve ser transmitido, configure `capture_device` com um
dispositivo que capture o **som do sistema**:

- **Linux (PipeWire/PulseAudio):** um dispositivo com `monitor` no nome —
  ex.: `capture_device = "monitor"`;
- **Windows:** habilite o **Stereo Mix** (Painel de som → Gravação) ou use um
  cabo virtual como o [VB-Audio Cable](https://vb-audio.com/Cable/), e aponte
  `capture_device` para ele.

Depois:

```bash
# na máquina que envia o som
perishare audio-send

# na máquina com os fones
perishare audio-recv
```

Dica: selecionando um **microfone** em `capture_device`, o mesmo par de
comandos transmite o microfone em vez do som do sistema.

### Painel gráfico

```bash
perishare gui
```

Abre uma janela com botões iniciar/parar para os quatro serviços e o log ao
vivo. (No Arch requer o pacote `tk`.)

### Iniciar automaticamente (Arch / systemd)

O pacote instala unidades de usuário para os papéis de "máquina secundária":

```bash
systemctl --user enable --now perishare-input-client
systemctl --user enable --now perishare-audio-recv
```

## Solução de problemas

| Sintoma | Causa provável / solução |
|---|---|
| `Falha de autenticação` | O `secret` difere entre as máquinas — copie o mesmo `config.toml`. |
| Entrada não funciona em Wayland | Habilite o backend evdev: `perishare input-devices` e `./packaging/linux/setup-permissions.sh` (grupo `input` + regra udev). |
| `Sem permissão para ... /dev/uinput` | Instale a regra udev e entre no grupo `input`; rode `perishare input-devices` para diagnosticar. |
| `Nenhum teclado/mouse encontrado` | Entre no grupo `input` (`sudo usermod -aG input $USER`) e refaça o login. |
| Áudio picotando | Aumente `blocksize` (ex.: 960) na configuração das duas máquinas. |
| `Servidor ... indisponível` | Confira `server_host`, se o serviço está rodando na outra máquina e o firewall (portas 42800/42801 TCP). |
| Atalho não alterna | Alguma tecla do atalho pode estar em uso pelo sistema; troque `toggle_hotkey` (ex.: `<ctrl>+<alt>+<f9>`). |
| Medo de "trancar" o teclado (evdev) | O atalho e o fim do processo sempre liberam o *grab*; ou use `grab = false` para nunca capturar com exclusividade. |
| Acento/símbolo errado entre Linux e Windows | O mapa cross-plataforma é US; entre Linux ⇄ Linux (evdev) a fidelidade é total via código de tecla do kernel. |
| Periférico Bluetooth reconectou e parou | O `input-server` abre os dispositivos ao iniciar; se um teclado/mouse (BT ou USB) cai e volta, reinicie o `input-server` para capturar o novo nó. |
| Fone Bluetooth com atraso no áudio | Latência do A2DP soma à da rede; aumente `blocksize` se picotar. O microfone de fone BT (HSP/HFP) tem baixa qualidade — mas normalmente capturamos o som do sistema, não o mic. |

## Bluetooth

Funciona: o app opera no nível de dispositivo do sistema, então **teclado,
mouse e fones Bluetooth são tratados como quaisquer outros** — desde que já
estejam pareados e conectados pelo próprio SO (o app não faz o pareamento).

- **Teclado/mouse (Função 1):** um dispositivo BT aparece como um
  `/dev/input/event*` normal (Linux) ou HID (Windows); o backend evdev ou
  pynput captura igual a um USB, inclusive o *grab*.
- **Fones (Função 2):** aponte `playback_device` para o fone BT (ou deixe
  vazio, se ele já for a saída padrão). A latência do Bluetooth (A2DP) soma à
  da rede — ótimo para ouvir o som do sistema, menos ideal para sincronia fina.
- **Limitação de hot-plug:** os dispositivos de entrada são abertos no início
  do `input-server`. Se um periférico BT desconectar e reconectar no meio da
  sessão, reinicie o serviço (o mesmo vale para reconexão USB).

## Desenvolvimento

```bash
python -m unittest discover -s tests -v   # testes (protocolo, segurança, config)
pip install -e .                          # instalação editável
```

Arquitetura em resumo: mensagens TCP com prefixo de tamanho
(`perishare/netmsg.py`); handshake HMAC + AES-256-GCM
(`perishare/security.py`); entrada com dois backends selecionados em
`perishare/inputshare/backends.py` — `pynput` (X11/Windows, em `server.py`/
`client.py`) e `evdev`/uinput em nível de kernel (`evdev_server.py`/
`evdev_client.py`), com o transporte compartilhado em `transport.py` e a
tradução de teclas em `keymap.py`; captura/reprodução de áudio com
sounddevice/PortAudio, PCM s16le e buffer de jitter (`perishare/audioshare/`).

## Licença

[MIT](LICENSE)
