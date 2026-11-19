// As permissoes que o servidor informa em /api/auth/eu (`permissoes.do_perfil`, backend/app/permissoes.py). A tela
// decide por elas, e nao pelo nome do perfil, onde a regra e' uma permissao do servidor (issue #829: o SIGA).

/** As permissoes que a tela le. `ver_siga`: abrir o SIGA (menu, rota, aba do contratante); `editar_cadastros`: os
 *  botoes que gravam no SIGA (colar link, corrigir a categoria, pedir leitura ao robo). */
export type Permissao = "ver_siga" | "editar_cadastros";

/** Quem tem a permissao? Sem a lista (usuario nenhum, resposta antiga), ninguem tem. */
export function pode(usuario: { permissoes?: readonly string[] } | null | undefined, p: Permissao): boolean {
  return usuario?.permissoes?.includes(p) ?? false;
}
