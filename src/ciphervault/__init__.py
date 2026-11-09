"""Inicialização do pacote CipherVault.

Contém a string de versão da biblioteca e exporta módulos públicos.
Incrementar números de versão em alterações significativas:
 MAJOR (X.0.0): incompatível / grande redesenho
 MINOR (1.X.0): adições de funcionalidades (novos comandos, alterações de formato)
 PATCH (1.0.X): pequenas melhorias / correções / instrumentação
"""

__version__ = "1.9.0"

__all__ = ["crypto", "__version__"]
