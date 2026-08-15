"""Interface de linha de comando do PeriShare."""

from __future__ import annotations

import argparse
import logging
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

    if args.command == "gui":
        from .gui import run_gui

        return run_gui(args.config)

    cfg = config_mod.load(args.config)
    services = {
        "input-server": "perishare.inputshare.server:InputServer",
        "input-client": "perishare.inputshare.client:InputClient",
        "audio-send": "perishare.audioshare.sender:AudioSender",
        "audio-recv": "perishare.audioshare.receiver:AudioReceiver",
    }
    module_name, _, class_name = services[args.command].partition(":")
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
