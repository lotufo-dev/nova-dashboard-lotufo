"""As abas da pagina do contratante (issue #818): `GET /api/contratantes/{chave}/medicoes`, `.../a-receber` e
`.../siga`, cada uma o recorte de uma tela que ja' existe (`app/contratante.py`). So' leitura, com sessao.

Medicoes e A receber sao de quem ve os paineis (`ver_paineis`, os tres perfis), como a fila de Medicoes e a pagina A
receber. Processos no SIGA e' de quem abre a tela SIGA (`busca.PERMISSAO_SIGA`: engenharia e administracao): a
diretoria nao ve a aba nem recebe o dado dela (403). A rota `GET /api/siga` da tela continua como esta' (issue #829,
decisao pendente do dono). Chave que nenhuma obra tem: 404."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Path

from app import busca, contratante
from app.api_auth import conexao
from app.permissoes import exigir

router = APIRouter()

# a chave da pagina do contratante, como o endereco a aceita (`ehChave` em rota.tsx)
CHAVE = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def _recorte(ler, *args):
    """A aba do contratante; a chave que nenhuma obra tem e' 404 (`contratante.ContratanteDesconhecido`)."""
    try:
        return ler(*args)
    except contratante.ContratanteDesconhecido as e:
        raise HTTPException(404, str(e)) from None


@router.get("/api/contratantes/{chave}/medicoes")
def medicoes_do_contratante(chave: str = CHAVE, _=Depends(exigir("ver_paineis", com_csrf=False)),
                            conn: sqlite3.Connection = Depends(conexao)):
    """A fila de trabalho da competencia em trabalho, so' das obras do contratante."""
    return _recorte(contratante.medicoes, conn, chave)


@router.get("/api/contratantes/{chave}/a-receber")
def a_receber_do_contratante(chave: str = CHAVE, _=Depends(exigir("ver_paineis", com_csrf=False)),
                             conn: sqlite3.Connection = Depends(conexao)):
    """O grupo do contratante na pagina A receber; sem o total a receber liberado, so' a trava."""
    return _recorte(contratante.em_aberto, conn, chave)


@router.get("/api/contratantes/{chave}/siga")
def siga_do_contratante(chave: str = CHAVE, _=Depends(exigir(busca.PERMISSAO_SIGA, com_csrf=False)),
                        conn: sqlite3.Connection = Depends(conexao)):
    """Os processos vivos das obras do contratante, do mais parado para o menos. A diretoria recebe 403."""
    return _recorte(contratante.processos_no_siga, conn, chave)
