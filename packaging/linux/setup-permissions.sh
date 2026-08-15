#!/usr/bin/env bash
# Configura as permissões do backend evdev/uinput do PeriShare no Linux.
#
# Este script é INTERATIVO e conservador de propósito: pede confirmação antes
# de CADA alteração no sistema e NUNCA sobrescreve um arquivo existente sem
# perguntar. Nada aqui é executado automaticamente pelo aplicativo — você
# roda este script manualmente, quando quiser.
#
# Uso:
#   ./packaging/linux/setup-permissions.sh
#
# O que ele pode fazer (sempre perguntando antes):
#   1. adicionar seu usuário ao grupo "input" (ler /dev/input);
#   2. instalar a regra udev em /etc/udev/rules.d/ (acesso a /dev/uinput);
#   3. instalar o carregamento do módulo em /etc/modules-load.d/;
#   4. carregar o módulo "uinput" agora (modprobe);
#   5. recarregar as regras do udev.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULE_SRC="$SCRIPT_DIR/99-perishare-uinput.rules"
RULE_DST="/etc/udev/rules.d/99-perishare-uinput.rules"
MOD_SRC="$SCRIPT_DIR/perishare-uinput.conf"
MOD_DST="/etc/modules-load.d/perishare-uinput.conf"

ask() {
    # ask "pergunta" -> retorna 0 se o usuário confirmar (y/s), 1 caso contrário.
    local prompt="$1" reply
    read -r -p "$prompt [s/N] " reply || true
    case "$reply" in
        [sSyY]) return 0 ;;
        *) return 1 ;;
    esac
}

install_file() {
    # install_file origem destino descrição
    local src="$1" dst="$2" desc="$3"
    if [[ -f "$dst" ]]; then
        if cmp -s "$src" "$dst"; then
            echo "  ✓ $desc já instalado e idêntico ($dst)."
            return 0
        fi
        echo "  ! Já existe um arquivo DIFERENTE em $dst."
        if ! ask "    Sobrescrever $dst?"; then
            echo "    Mantido como está (nada alterado)."
            return 0
        fi
    fi
    sudo install -Dm644 "$src" "$dst"
    echo "  ✓ Instalado: $dst"
}

echo "== Configuração de permissões do PeriShare (backend evdev/uinput) =="
echo
echo "Usuário atual: $USER"
echo "Este script pede confirmação antes de cada alteração no sistema."
echo

# 1) Grupo input
if id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
    echo "1) Grupo 'input': você já pertence. ✓"
else
    echo "1) Ler /dev/input exige pertencer ao grupo 'input'."
    if ask "   Adicionar $USER ao grupo 'input' (sudo usermod -aG input $USER)?"; then
        sudo usermod -aG input "$USER"
        echo "   ✓ Adicionado. Você precisa REFAZER O LOGIN para valer."
    else
        echo "   Pulado."
    fi
fi
echo

# 2) Regra udev
echo "2) Regra udev para acesso a /dev/uinput (injeção de entrada)."
if [[ -f "$RULE_SRC" ]]; then
    if ask "   Instalar $RULE_DST?"; then
        install_file "$RULE_SRC" "$RULE_DST" "regra udev"
    else
        echo "   Pulado."
    fi
else
    echo "   ! Origem não encontrada: $RULE_SRC"
fi
echo

# 3) Carregamento do módulo no boot
echo "3) Carregar o módulo 'uinput' no boot."
if [[ -f "$MOD_SRC" ]]; then
    if ask "   Instalar $MOD_DST?"; then
        install_file "$MOD_SRC" "$MOD_DST" "modules-load.d"
    else
        echo "   Pulado."
    fi
else
    echo "   ! Origem não encontrada: $MOD_SRC"
fi
echo

# 4) Carregar o módulo agora
echo "4) Carregar o módulo 'uinput' agora (sem reiniciar)."
if lsmod | grep -qw uinput; then
    echo "   Módulo 'uinput' já carregado. ✓"
elif ask "   Rodar 'sudo modprobe uinput' agora?"; then
    sudo modprobe uinput
    echo "   ✓ Carregado."
else
    echo "   Pulado."
fi
echo

# 5) Recarregar udev
echo "5) Recarregar as regras do udev."
if ask "   Rodar 'sudo udevadm control --reload-rules && sudo udevadm trigger'?"; then
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    echo "   ✓ Recarregado."
else
    echo "   Pulado."
fi
echo

echo "Concluído. Verifique com:  perishare input-devices"
echo "Se acabou de entrar no grupo 'input', refaça o login antes."
