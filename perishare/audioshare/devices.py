"""Seleção e listagem de dispositivos de áudio."""

from __future__ import annotations


def resolve_device(spec: str, kind: str):
    """Converte a configuração em um índice de dispositivo do sounddevice.

    *spec* pode ser vazio (dispositivo padrão), um índice numérico ou parte
    do nome (sem diferenciar maiúsculas). *kind* é ``"input"`` ou ``"output"``.
    """
    import sounddevice as sd

    if not spec:
        return None
    try:
        return int(spec)
    except ValueError:
        pass
    needle = spec.lower()
    channel_key = f"max_{kind}_channels"
    for index, dev in enumerate(sd.query_devices()):
        if dev[channel_key] > 0 and needle in dev["name"].lower():
            return index
    raise ValueError(
        f"Dispositivo de áudio ({kind}) não encontrado: {spec!r}. "
        "Use 'perishare devices' para listar os disponíveis."
    )


def format_device_list() -> str:
    import sounddevice as sd

    default_in, default_out = sd.default.device
    apis = sd.query_hostapis()
    lines = ["Dispositivos de áudio (índice, entradas/saídas, nome):", ""]
    for index, dev in enumerate(sd.query_devices()):
        marks = ""
        if index == default_in:
            marks += " [entrada padrão]"
        if index == default_out:
            marks += " [saída padrão]"
        api = apis[dev["hostapi"]]["name"]
        lines.append(
            f"{index:>3}  {dev['max_input_channels']:>2}e/{dev['max_output_channels']:<2}s  "
            f"{dev['name']}  ({api}){marks}"
        )
    lines += [
        "",
        "Dica: para transmitir o SOM DO SISTEMA (e não o microfone), escolha em",
        "capture_device um dispositivo de monitor/loopback:",
        "  - Linux (PipeWire/PulseAudio): um dispositivo com \"monitor\" no nome;",
        "  - Windows 10/11: habilite o \"Stereo Mix\" (Mixagem Estéreo) no painel",
        "    de som ou instale um cabo virtual como o VB-Audio Cable.",
    ]
    return "\n".join(lines)
