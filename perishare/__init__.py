"""PeriShare — compartilhamento de periféricos entre computadores.

Duas funções principais:

1. Entrada (teclado e mouse): um computador "servidor" captura o teclado e o
   mouse físicos e os encaminha para um computador "cliente" pela rede local,
   estilo KVM por software.
2. Áudio (fones de ouvido): um computador transmite seu áudio pela rede para
   ser reproduzido nos fones conectados ao outro computador.

Compatível com Linux (testado com foco em Arch Linux, sessão X11) e
Windows 10/11.
"""

__version__ = "0.1.0"
