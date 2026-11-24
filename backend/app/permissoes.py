from fastapi import Depends, HTTPException

from app.api_auth import exigir_csrf, usuario_atual

# frozenset: a matriz de permissoes e' constante de modulo e nao pode ser mutada
# por engano em tempo de execucao (um .add() num set aqui daria permissao a todo
# mundo, silenciosamente e sem deixar rastro na auditoria).
#
# `ver_siga` (issue #829, decisao do dono de 19/11/2026): ler o SIGA, a regra unica de quem o ve. Decide no servidor a
# tela (`GET /api/siga`), a busca (`busca.ve_siga`), a aba do contratante e a posicao do processo no quadro das
# Medicoes (`/api/medicoes/resumo` e `/api/medicoes/fila`, #853); a tela le a mesma regra em `/api/auth/eu`
# (`permissoes`), para o menu e a rota. A diretoria le e nao escreve: as rotas do SIGA que gravam, inclusive pedir
# leitura ao robo, exigem `editar_cadastros`.
VER_SIGA = "ver_siga"
PERFIS: dict[str, frozenset[str]] = {
    "diretoria": frozenset({"ver_paineis", VER_SIGA}),
    "engenharia": frozenset({"ver_paineis", VER_SIGA, "editar_cadastros"}),
    "admin": frozenset({"ver_paineis", VER_SIGA, "editar_cadastros", "editar_config_fiscal", "administrar"}),
}

_VAZIO: frozenset[str] = frozenset()

def tem(perfil: str, permissao: str) -> bool:
    return permissao in PERFIS.get(perfil, _VAZIO)

def do_perfil(perfil: str) -> list[str]:
    """As permissoes do perfil, em ordem, para a tela decidir pela mesma regra do servidor (`/api/auth/eu`)."""
    return sorted(PERFIS.get(perfil, _VAZIO))

def exigir(permissao: str, com_csrf: bool = True):
    """Devolve uma dependency que exige sessao valida + a permissao informada.

    com_csrf=True (padrao) tambem valida o header X-CSRF-Token -- use em rotas
    que escrevem. Em leituras (GET), passar com_csrf=False.
    """
    base = exigir_csrf if com_csrf else usuario_atual

    def dep(usuario: dict = Depends(base)) -> dict:
        if not tem(usuario["perfil"], permissao):
            raise HTTPException(403, f"Permissão necessária: {permissao}")
        return usuario

    return dep
