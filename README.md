# PeriShare

Compartilhamento de periféricos entre dois computadores pela rede local, com
duas funções:

1. **Teclado e mouse (KVM por software)** — use o teclado e o mouse de um
   computador para controlar o outro, alternando com um atalho
   (padrão: `Ctrl+Alt+F12`).
2. **Áudio / fones de ouvido** — o som de um computador é transmitido pela
   rede e reproduzido nos fones conectados ao outro.

Compatível com **Linux** (desenvolvido com foco em **Arch Linux**, sessão X11)
e **Windows 10/11**. As duas máquinas podem estar em qualquer combinação de
sistemas (Arch ⇄ Arch, Arch ⇄ Windows, Windows ⇄ Windows).

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
yay -S python-pynput          # dependência do AUR
git clone https://github.com/CauaVenturaDev/Desktop-laptop.git
cd Desktop-laptop/packaging/arch
makepkg -si
```

Opção B — pipx:

```bash
sudo pacman -S python-pipx tk
yay -S python-pynput
git clone https://github.com/CauaVenturaDev/Desktop-laptop.git
pipx install ./Desktop-laptop
```

> **Wayland:** a captura/injeção global de teclado e mouse usa X11. Em
> GNOME/KDE com Wayland, inicie uma sessão X11 (Xorg) para usar a função de
> entrada. A função de áudio funciona em qualquer sessão.

### Windows 10 / 11

1. Instale o [Python 3.11+](https://www.python.org/downloads/) marcando
   **"Add python.exe to PATH"**.
2. Baixe/clone este repositório e execute no PowerShell:

```powershell
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

Pressione **`Ctrl+Alt+F12`** (configurável em `toggle_hotkey`) para enviar o
teclado/mouse para a máquina remota; pressione de novo para voltar. Se a
conexão cair, o controle volta automaticamente para a máquina local e as
teclas pressionadas são soltas na remota.

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
| Entrada não funciona no Linux | Sessão Wayland: use uma sessão X11 (Xorg). |
| Áudio picotando | Aumente `blocksize` (ex.: 960) na configuração das duas máquinas. |
| `Servidor ... indisponível` | Confira `server_host`, se o serviço está rodando na outra máquina e o firewall (portas 42800/42801 TCP). |
| Atalho não alterna | Alguma tecla do atalho pode estar em uso pelo sistema; troque `toggle_hotkey` (formato do pynput, ex.: `<ctrl>+<alt>+<f9>`). |
| Tecla exótica não repete na outra máquina | Teclas sem caractere/nome usam código da plataforma, fiel apenas entre sistemas iguais; letras, números, acentos e teclas especiais funcionam entre Linux ⇄ Windows. |

## Desenvolvimento

```bash
python -m unittest discover -s tests -v   # testes (protocolo, segurança, config)
pip install -e .                          # instalação editável
```

Arquitetura em resumo: mensagens TCP com prefixo de tamanho
(`perishare/netmsg.py`); handshake HMAC + AES-256-GCM
(`perishare/security.py`); captura/injeção de entrada com pynput
(`perishare/inputshare/`); captura/reprodução de áudio com
sounddevice/PortAudio, PCM s16le e buffer de jitter
(`perishare/audioshare/`).

## Licença

[MIT](LICENSE)
