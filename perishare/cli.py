"""Interface de linha de comando do PeriShare."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import __version__, config as config_mod


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="perishare",
        description=(
            "Compartilhamento de periféricos entre computadores pela rede local: "
            "teclado/mouse (estilo KVM) e áudio (fones de ouvido). "
            "Linux (Arch) e Windows 10/11."
        ),
    )
    parser.add_argument(
        "--config", "-c", metavar="ARQUIVO", help="caminho do config.toml"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="logs detalhados (debug)"
    )
    parser.add_argument(
        "--version", action="version", version=f"perishare {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMANDO")

    p_init = sub.add_parser(
        "init", help="cria o arquivo de configuração com um segredo aleatório"
    )
    p_init.add_argument(
        "--force", action="store_true", help="sobrescreve a configuração existente"
    )

    sub.add_parser("devices", help="lista os dispositivos de áudio disponíveis")
    sub.add_parser(
        "input-devices",
        help="Linux: diagnostica teclados/mouses e o acesso a /dev/uinput (evdev)",
    )
    sub.add_parser(
        "input-server",
        help="máquina com teclado/mouse físicos: captura e envia a entrada",
    )
    sub.add_parser(
        "input-client",
        help="máquina controlada: recebe e aplica teclado/mouse remotos",
    )
    sub.add_parser(
        "audio-send", help="máquina cujo som será transmitido: envia o áudio"
    )
    sub.add_parser(
        "audio-recv", help="máquina com os fones: recebe e reproduz o áudio"
    )
    sub.add_parser("gui", help="abre o painel gráfico com os quatro serviços")
    return parser


def _cmd_init(args) -> int:
    from pathlib import Path

    path = Path(args.config) if args.config else config_mod.default_path()
    try:
        config_mod.write_template(path, force=args.force)
    except FileExistsError:
        print(f"Já existe configuração em {path} (use --force para sobrescrever).")
        return 1
    print(f"Configuração criada em: {path}")
    print()
    print("Próximos passos:")
    print("  1. Copie este mesmo arquivo para a outra máquina (o campo 'secret'")
    print("     precisa ser idêntico nas duas).")
    print("  2. Na máquina cliente/receptora, edite 'server_host' com o IP da")
    print("     máquina servidora/emissora.")
    print("  3. Rode 'perishare devices' para escolher os dispositivos de áudio.")
    return 0


def _cmd_devices() -> int:
    try:
        from .audioshare.devices import format_device_list

        print(format_device_list())
    except Exception as exc:
        print(f"Não foi possível listar os dispositivos de áudio: {exc}", file=sys.stderr)
        return 1
    return 0


def _user_in_group(name: str) -> bool:
    """Verifica se o usuário atual pertence ao grupo *name*.

    Cobre os dois casos: o grupo já ativo na sessão (os.getgroups) e o grupo
    atribuído mas ainda não aplicado por falta de novo login (gr_mem).
    """
    try:
        import grp

        entry = grp.getgrnam(name)
    except (KeyError, ImportError):
        return False
    if entry.gr_gid in os.getgroups():
        return True
    try:
        import getpass

        return getpass.getuser() in entry.gr_mem
    except Exception:
        return os.environ.get("USER", "") in entry.gr_mem


def _cmd_input_devices() -> int:
    """Diagnóstico (somente leitura) do backend evdev: dispositivos e permissões.

    Não modifica nada no sistema — apenas verifica e imprime instruções.
    """
    if not sys.platform.startswith("linux"):
        print(
            "O backend evdev existe apenas no Linux. Em Windows/X11 o app usa o "
            "backend pynput, que não precisa deste diagnóstico."
        )
        return 0
    try:
        import evdev
        from evdev import ecodes
    except Exception as exc:
        print(f"Pacote 'evdev' indisponível ({exc}).")
        print("Instale com: sudo pacman -S python-evdev   (ou: pip install evdev)")
        return 1

    print("Dispositivos de entrada em /dev/input:\n")
    keyboards = pointers = readable = 0
    denied = 0
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except PermissionError:
            denied += 1
            print(f"  {path}: SEM PERMISSÃO de leitura")
            continue
        except OSError:
            continue
        readable += 1
        caps = dev.capabilities()
        keys = set(caps.get(ecodes.EV_KEY, []))
        rels = set(caps.get(ecodes.EV_REL, []))
        is_kbd = ecodes.KEY_A in keys or ecodes.KEY_ENTER in keys
        is_ptr = (ecodes.REL_X in rels and ecodes.REL_Y in rels) or ecodes.BTN_LEFT in keys
        role = []
        if is_kbd:
            role.append("teclado")
            keyboards += 1
        if is_ptr:
            role.append("mouse/ponteiro")
            pointers += 1
        print(f"  {path}: {dev.name}  [{', '.join(role) or 'outro'}]")
        dev.close()

    print()
    print(f"Legíveis: {readable} | teclados: {keyboards} | ponteiros: {pointers}")
    if denied:
        print(
            f"\n{denied} dispositivo(s) sem permissão. Entre no grupo 'input':\n"
            "  sudo usermod -aG input $USER    (e refaça o login)"
        )

    if readable == 0:
        # O evdev.list_devices() oculta os dispositivos que não consegue abrir,
        # então "0 legíveis" costuma ser falta de permissão, não ausência de
        # hardware. Diagnostica melhor olhando os nós brutos e o grupo 'input'.
        import glob

        nodes = glob.glob("/dev/input/event*")
        print()
        if not nodes:
            print(
                "Nenhum /dev/input/event* existe. Isso é raro: verifique se há "
                "teclado/mouse conectados e se o kernel os expõe."
            )
        elif _user_in_group("input"):
            print(
                f"Existem {len(nodes)} dispositivos em /dev/input, mas nenhum é "
                "legível nesta sessão.\n"
                "Você JÁ está no grupo 'input', mas a sessão atual ainda não o "
                "aplicou.\n"
                "  -> Faça logout/login (ou reinicie) e tente de novo.\n"
                "  -> Teste rápido nesta shell: newgrp input && perishare input-devices"
            )
        else:
            print(
                f"Existem {len(nodes)} dispositivos em /dev/input, mas você não "
                "tem permissão de leitura.\n"
                "Você NÃO está no grupo 'input'. Rode:\n"
                "  sudo usermod -aG input $USER\n"
                "e faça logout/login (o grupo só passa a valer em sessões novas).\n"
                "Obs.: no Qtile (backend evdev) isso é necessário. Se preferir o "
                'backend pynput (X11), defina backend = "pynput" e este acesso '
                "não é preciso no servidor."
            )

    # Acesso ao /dev/uinput (injeção). Testa sem manter o dispositivo aberto.
    print()
    try:
        ui = evdev.UInput(name="PeriShare Test")
        ui.close()
        print("Injeção via /dev/uinput: OK")
    except PermissionError:
        print(
            "Injeção via /dev/uinput: SEM PERMISSÃO.\n"
            "  Instale a regra udev packaging/linux/99-perishare-uinput.rules em\n"
            "  /etc/udev/rules.d/, rode 'sudo modprobe uinput' e entre no grupo 'input'."
        )
    except Exception as exc:
        print(
            f"Injeção via /dev/uinput: indisponível ({exc}).\n"
            "  Carregue o módulo do kernel: sudo modprobe uinput"
        )
    return 0


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.command == "init":
        return _cmd_init(args)
    if args.command == "devices":
        return _cmd_devices()
    if args.command == "input-devices":
        return _cmd_input_devices()

    if args.command == "gui":
        from .gui import run_gui

        return run_gui(args.config)

    cfg = config_mod.load(args.config)
    if args.command == "input-server":
        from .inputshare.backends import make_input_server

        service = make_input_server(cfg)
    elif args.command == "input-client":
        from .inputshare.backends import make_input_client

        service = make_input_client(cfg)
    else:
        audio = {
            "audio-send": "perishare.audioshare.sender:AudioSender",
            "audio-recv": "perishare.audioshare.receiver:AudioReceiver",
        }
        module_name, _, class_name = audio[args.command].partition(":")
        import importlib

        service_cls = getattr(importlib.import_module(module_name), class_name)
        service = service_cls(cfg)
    try:
        service.run_forever()
    except RuntimeError as exc:
        logging.getLogger("perishare").error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
