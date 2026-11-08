"""Importa o ledger historico de faturamento da dashboard ANTIGA para ligar NF do RM a
medicoes ja carregadas na dashboard nova.

Evento UNICO (nao e' sincronizacao recorrente). Le dois JSON exportados da antiga:
`Itens de Faturamento.json` (uma linha por nota, com `IdMovRM` = IDMOV do TOTVS RM) e
`Cadastro de Obras.json` (para mapear a obra ao contrato pelo numero do instrumento).

Para cada item que (a) mapeia a um contrato, (b) casa uma medicao por (numero, tipo),
(c) tem uma NF do RM JA presente em `notas_fiscais` (coligada+idmov, ativa) e (d) essa
NF tem o MESMO valor bruto do ledger, cria a alocacao reusando `sincronizacao_rm.alocar`
-- o mesmo caminho auditado do casador. Ao final recomputa recebimentos (a baixa do RM
ja sincronizada faz a medicao virar `recebida` sozinha). Itens SEM IdMovRM (cota de
consorcio, backfill) NAO criam registro de NF -- ficam como estao (medicao ja e'
`nf_emitida` = faturada), decisao do Leonardo (2026-09-09: sem acao humana).

Travas contra vinculo errado (gate Sol 2026-09-09):
- a coligada vem da ChaveIdempotencia `RM:<coligada>:<idmov>` (fullmatch, e o idmov da
  chave TEM que ser igual ao IdMovRM); so' se infere a coligada pela entidade da obra
  quando a chave e' um `MIG:` valido; chave desconhecida e' pulada.
- CONFERENCIA DE VALOR: so' aloca se `notas_fiscais.valor_centavos` == `ValorBruto` do
  ledger. E' a mesma nota, entao tem que bater; NF homonima (mesmo idmov, coligada
  errada) tem valor diferente e e' rejeitada.
- rotulo de medicao validado por inteiro (numero + ª/º opcional), nao por prefixo.

Idempotente (NF ja alocada e' pulada), atomico, auditado. `aplicar=False` = dry-run.
"""
import datetime
import json
import re
from collections import Counter

from app import db, rm, sincronizacao_rm

_NUM = re.compile(r"(\d{2,4})/(\d{4})")
_CRO = re.compile(r"CRO\.ENG\.(\d+)\.(\d+)", re.I)
_RMCH = re.compile(r"RM:(\d+):(\d+)")
_MIG = re.compile(r"MIG:\d+:\w+:\d+:\d+")        # backfill: "MIG:172:FATURAMENTO:23:2081"
_ROT = re.compile(r"\s*(\d+)\s*[ªº°]?\s*$")      # rotulo INTEIRO: "13ª", "5", "5º" -- nao "1xyz"
_COMP = re.compile(r"(\d{2})/(\d{4})")           # competencia do ledger: "12/2024"
_TIPO = {"medição": "execucao", "medicao": "execucao", "reajuste": "reajuste", "projeto": "projeto"}


def _num_contrato(s):
    """'074/2021/00/00' | '155/2022/00/00-SINFRA' -> '74/2021'; 'CRO.ENG.508.2025' -> 'CRO508/2025'."""
    m = _NUM.search(s or "")
    if m:
        return f"{int(m.group(1))}/{m.group(2)}"
    m = _CRO.search(s or "")
    return f"CRO{m.group(1)}/{m.group(2)}" if m else None


def _carregar(caminho_ou_lista):
    if isinstance(caminho_ou_lista, list):
        return caminho_ou_lista
    d = json.load(open(caminho_ou_lista, encoding="utf-8"))
    return d if isinstance(d, list) else d.get("value", d)


def _mapa_obra_contrato(conn, cadastro):
    """ObraId (antiga) -> contrato_id (novo), so' quando a correspondencia e' 1:1 nos dois
    sentidos: o numero do instrumento acha exatamente um contrato novo, e um mesmo ObraId
    nao aponta para contratos diferentes (defesa contra cadastro duplicado)."""
    novo = {}
    for r in conn.execute("SELECT id, numero_instrumento FROM contratos"):
        k = _num_contrato(r["numero_instrumento"])
        if k:
            novo.setdefault(k, set()).add(r["id"])
    por_obra = {}
    for o in cadastro:
        cand = novo.get(_num_contrato(o.get("Contrato")), set())
        if len(cand) == 1:
            por_obra.setdefault(o["Id"], set()).add(next(iter(cand)))
    return {oid: next(iter(cts)) for oid, cts in por_obra.items() if len(cts) == 1}


def importar(conn, usuario_id, itens, cadastro, aplicar: bool = False) -> dict:
    """Liga as NFs do RM do ledger antigo as medicoes. `itens`/`cadastro` = caminho JSON
    ou lista ja carregada. `aplicar=False` = dry-run (nao grava)."""
    from app import diretoria   # import local: diretoria importa sincronizacao_rm
    itens = _carregar(itens)
    cadastro = _carregar(cadastro)
    obra2ct = _mapa_obra_contrato(conn, cadastro)
    obra2colig = {}
    for oid, ct in obra2ct.items():
        r = conn.execute("SELECT e.coligada_rm FROM contratos c LEFT JOIN entidades e ON e.id=c.entidade_id "
                         "WHERE c.id=?", (ct,)).fetchone()
        obra2colig[oid] = r["coligada_rm"] if r else None
    med = {}
    for r in conn.execute("SELECT id, contrato_id, numero, tipo FROM medicoes"):
        med.setdefault((r["contrato_id"], r["numero"], r["tipo"]), []).append(r["id"])

    resumo = {"itens": len(itens), "alocadas": 0, "ja_alocada": 0, "sem_idmov": 0,
              "sem_contrato": 0, "sem_medicao": 0, "sem_nf_rm": 0, "valor_divergente": 0,
              "chave_ruim": 0, "rotulo_ruim": 0, "medicao_incompat": 0, "recebimentos": 0,
              "fora_da_cobranca": 0, "puladas_fora_da_cobranca": []}
    plano = []

    def passar():
        for it in itens:
            ct = obra2ct.get(it.get("ObraId"))
            if not ct:
                resumo["sem_contrato"] += 1
                continue
            idmov = it.get("IdMovRM")
            if not idmov:
                resumo["sem_idmov"] += 1          # cota consorcio / backfill: fica faturado
                continue
            # coligada: da chave RM (idmov TEM que bater) ou, so' para MIG valido, da entidade
            ch = str(it.get("ChaveIdempotencia") or "")
            rmm = _RMCH.fullmatch(ch)
            if rmm:
                if rmm.group(2) != str(idmov):
                    resumo["chave_ruim"] += 1
                    continue
                colig = int(rmm.group(1))
            elif ch.startswith("MIG:"):
                colig = obra2colig.get(it.get("ObraId"))
            else:
                resumo["chave_ruim"] += 1
                continue
            m = _ROT.match(str(it.get("MedicaoRotulo") or ""))
            if not m:
                resumo["rotulo_ruim"] += 1
                continue
            numero = int(m.group(1))
            tipo = _TIPO.get(str(it.get("TipoDocumento", "")).strip().lower())
            mids = med.get((ct, numero, tipo), [])
            if len(mids) != 1:
                resumo["sem_medicao"] += 1
                continue
            nf = conn.execute("SELECT id, valor_centavos, codtmv FROM notas_fiscais "
                              "WHERE coligada=? AND idmov=? AND situacao='ativa'",
                              (colig, int(idmov))).fetchone() if colig is not None else None
            if not nf:
                resumo["sem_nf_rm"] += 1
                continue
            # CONFERENCIA DE VALOR: e' a mesma nota, o bruto tem que bater (defesa contra
            # coligada inferida errada que ache uma NF homonima).
            if rm.centavos(it.get("ValorBruto")) != nf["valor_centavos"]:
                resumo["valor_divergente"] += 1
                continue
            if conn.execute("SELECT 1 FROM nf_alocacoes WHERE nota_id=? AND desfeita_em IS NULL",
                            (nf["id"],)).fetchone():
                resumo["ja_alocada"] += 1
                continue
            # Issue #598: so' nota de cobranca ao orgao (`diretoria.CODTMV_COBRANCA`, a lista do a receber, #563)
            # vira vinculo automatico; nota de outro tipo ou sem tipo fica de fora e vai no relato.
            if nf["codtmv"] not in diretoria.CODTMV_COBRANCA:
                resumo["fora_da_cobranca"] += 1
                resumo["puladas_fora_da_cobranca"].append({"medicao_id": mids[0], "nota_id": nf["id"],
                                                           "numero_nf": it.get("NumNF"), "codtmv": nf["codtmv"]})
                continue
            estado = conn.execute("SELECT estado FROM medicoes WHERE id=?", (mids[0],)).fetchone()["estado"]
            if estado not in ("protocolada", "nota_emitida", "nf_emitida"):
                resumo["medicao_incompat"] += 1
                continue
            plano.append({"medicao_id": mids[0], "nota_id": nf["id"], "numero_nf": it.get("NumNF"),
                          "valor_centavos": nf["valor_centavos"]})
            if aplicar:
                sincronizacao_rm.alocar(conn, usuario_id, nf["id"], mids[0], "detectado", 1.0, "ledger_rm")
            resumo["alocadas"] += 1
        if aplicar:
            resumo["recebimentos"] = sincronizacao_rm._recebimentos(conn)

    if aplicar:
        with db.mutacao(conn):
            passar()
    else:
        passar()
    resumo["plano"] = plano
    return resumo


def _competencia(br):
    """'12/2024' -> '2024-12'. Fora do formato ou mes invalido (00, 13) -> None."""
    m = _COMP.fullmatch(str(br or "").strip())
    if not m or not 1 <= int(m.group(1)) <= 12:
        return None
    return f"{m.group(2)}-{m.group(1)}"


def _ultimo_dia(comp):
    """'2024-12' -> '2024-12-31' (ultimo dia da competencia, data estimada do protocolo)."""
    ano, mes = int(comp[:4]), int(comp[5:])
    return (datetime.date(ano + (mes == 12), (mes % 12) + 1, 1)
            - datetime.timedelta(days=1)).isoformat()


def criar_medicoes_faltantes(conn, usuario_id, itens, cadastro, aplicar: bool = False) -> dict:
    """Cria as medicoes que o ledger antigo FATURA mas que nunca entraram na lista de
    medicoes -- pre-passo do `importar`, que so' liga NF a medicao ja' existente.

    So' materializa um (contrato, numero, tipo) quando o item (a) mapeia a um contrato,
    (b) NAO tem medicao ainda, (c) tem IdMovRM cuja NF esta' em `notas_fiscais`
    (coligada+idmov, ativa) e (d) o bruto do ledger bate com a NF. GUARD (decisao do
    Leonardo 2026-09-09): a coligada da NF tem que ser a COLIGADA DA ENTIDADE do contrato
    -- item cuja NF vive em outra coligada (BR-163: entidade coligada 20, NF na 6 = Arica,
    tomador MCI, valores em milhares x os milhoes do contrato) NAO cria medicao, seria
    pousar faturamento de outra empresa. Varias NFs do mesmo (contrato, numero, tipo)
    viram UMA medicao no valor da SOMA (medicao faturada em varias notas -- Atalaia 43,
    Coxipo 15).

    A medicao nasce `protocolada` no valor da(s) nota(s) (a lista antiga nao trouxe a
    planilha; a NF do RM e' a fonte do valor, spec: NF desempata), com data de protocolo
    ESTIMADA pelo fim da competencia e justificativa de carga -- o mesmo padrao de
    `carga_legado`. Quem liga a NF e move para `nf_emitida` e' o `importar`, pelo IdMovRM.
    `aplicar=False` = dry-run (nao grava). Idempotente: medicao ja' existente e' pulada.

    Travas de dinheiro (gate Sol 2026-09-09):
    - GRUPO INTEIRO OU NADA: valida-se cada membro do (contrato, numero, tipo); se UM
      falhar (NF cancelada/ausente, valor divergente, competencia invalida, chave ruim),
      o grupo TODO e' recusado -- nunca nasce medicao com valor parcial.
    - Coligada da chave `RM:<coligada>:<idmov>` (idmov conferido) ou, no backfill `MIG:`,
      da entidade da obra -- o mesmo que o `importar` ja' faz em producao. Nos DOIS casos a
      NF tem que existir em (coligada, idmov) ativa E bater o ValorBruto; esse casamento de
      valor e' a trava contra coligada inferida errada (a chave RM ainda exige colig ==
      entidade, o que exclui o BR-163: RM:6 numa entidade coligada 20).
    - Cada NF entra UMA vez: duplicata identica no grupo e' ignorada; a mesma NF em dois
      grupos recusa AMBOS (nao se sabe de quem e' o valor).
    - Montagem do plano e criacao na MESMA transacao (`db.mutacao` = BEGIN IMMEDIATE), pra
      a NF nao ser cancelada entre a conferencia e a gravacao.
    """
    from app import diretoria, medicoes   # import local: diretoria importa sincronizacao_rm
    itens = _carregar(itens)
    cadastro = _carregar(cadastro)

    resumo = {"itens": len(itens), "grupos": 0, "criadas": 0, "nfs_cobertas": 0,
              "sem_idmov": 0, "sem_contrato": 0, "ja_tem_medicao": 0, "chave_ruim": 0,
              "rotulo_ruim": 0, "sem_nf_rm": 0, "coligada_divergente": 0,
              "valor_divergente": 0, "sem_competencia": 0, "competencia_incoerente": 0,
              "nf_duplicada": 0, "nf_ja_alocada": 0, "grupo_incompleto": 0, "fora_da_cobranca": 0}
    plano = []

    def montar_e_criar():
        obra2ct = _mapa_obra_contrato(conn, cadastro)
        obra2colig = {}
        for oid, ct in obra2ct.items():
            # COALESCE(entidade_id, 1): contrato sem entidade e' a Lotufo (entidade 1), a
            # mesma convencao do casador (_candidatas) -- senao obra propria com entidade
            # NULL cairia como coligada_divergente e nada seria criado.
            r = conn.execute("SELECT e.coligada_rm FROM contratos c "
                             "JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1) WHERE c.id=?", (ct,)).fetchone()
            obra2colig[oid] = r["coligada_rm"] if r else None
        existe = {(r["contrato_id"], r["numero"], r["tipo"])
                  for r in conn.execute("SELECT contrato_id, numero, tipo FROM medicoes")}

        # 1) agrupa os itens candidatos (com IdMovRM) por (contrato, numero, tipo) SEM ainda
        #    julgar a NF -- a validacao e' do grupo inteiro, no passo 2.
        grupos: dict = {}
        for it in itens:
            if not it.get("IdMovRM"):
                resumo["sem_idmov"] += 1
                continue
            ct = obra2ct.get(it.get("ObraId"))
            if not ct:
                resumo["sem_contrato"] += 1
                continue
            m = _ROT.match(str(it.get("MedicaoRotulo") or ""))
            tipo = _TIPO.get(str(it.get("TipoDocumento", "")).strip().lower())
            if not m or tipo is None:
                resumo["rotulo_ruim"] += 1
                continue
            numero = int(m.group(1))
            if (ct, numero, tipo) in existe:
                resumo["ja_tem_medicao"] += 1
                continue
            grupos.setdefault((ct, numero, tipo), []).append(it)

        # 2a) resolve a NF de CADA membro e REGISTRA a reivindicacao (nf_id -> chaves) assim
        #     que a NF esta' identificada com valor conferido -- ANTES de julgar o grupo. Se a
        #     mesma NF e' reivindicada por dois grupos, ambos caem, mesmo que um deles ja'
        #     tivesse falhado por outro membro (invariante do gate Sol 2026-09-09).
        def _resolver(it):
            """('ok', nf_id, comp) | ('fail', motivo). Registra a reivindicacao da NF."""
            idmov = it.get("IdMovRM")
            if not str(idmov).isdigit():
                return ("fail", "chave_ruim")
            ch = str(it.get("ChaveIdempotencia") or "")
            rmm = _RMCH.fullmatch(ch)
            if rmm:
                if rmm.group(2) != str(idmov):
                    return ("fail", "chave_ruim")
                colig = int(rmm.group(1))
            elif _MIG.fullmatch(ch):
                colig = obra2colig.get(it.get("ObraId"))         # backfill: coligada da entidade
            else:
                return ("fail", "chave_ruim")
            # RM: exige colig == entidade (exclui BR-163/Arica); MIG ja' e' a da entidade. A
            # conferencia de valor abaixo e' a trava final contra coligada inferida errada.
            if colig is None or colig != obra2colig.get(it.get("ObraId")):
                return ("fail", "coligada_divergente")
            nf = conn.execute("SELECT id, valor_centavos, codtmv FROM notas_fiscais "
                              "WHERE coligada=? AND idmov=? AND situacao='ativa'",
                              (colig, int(idmov))).fetchone()
            if not nf:
                return ("fail", "sem_nf_rm")
            # Issue #598: nota fora da cobranca ao orgao nao vira medicao (o `importar` tambem nao a ligaria)
            if nf["codtmv"] not in diretoria.CODTMV_COBRANCA:
                return ("fail", "fora_da_cobranca")
            if rm.centavos(it.get("ValorBruto")) != nf["valor_centavos"]:
                return ("fail", "valor_divergente")
            if conn.execute("SELECT 1 FROM nf_alocacoes WHERE nota_id=? AND desfeita_em IS NULL",
                            (nf["id"],)).fetchone():
                return ("fail", "nf_ja_alocada")     # NF ja' e' de outra medicao
            comp = _competencia(it.get("Competencia"))
            if not comp:
                return ("fail", "sem_competencia")
            return ("ok", nf["id"], nf["valor_centavos"], comp)

        reivindica: dict = {}           # nf_id -> set de chaves (ct,numero,tipo)
        por_grupo: dict = {}            # chave -> lista de saidas de _resolver
        for chave, membros in sorted(grupos.items()):
            saidas = [_resolver(it) for it in membros]
            for s in saidas:
                if s[0] == "ok":
                    reivindica.setdefault(s[1], set()).add(chave)
            por_grupo[chave] = saidas
        conflit = {nid for nid, ks in reivindica.items() if len(ks) > 1}   # NF em >1 grupo

        # 2b) grupo inteiro ou nada: qualquer membro que falhou derruba o grupo; NF em conflito
        #     (dois grupos) ou a mesma NF com competencias diferentes tambem.
        for chave, saidas in sorted(por_grupo.items()):
            fails = [s[1] for s in saidas if s[0] == "fail"]
            if fails:
                resumo[fails[0]] += 1
                resumo["grupo_incompleto"] += 1
                continue
            nfs, valor, ruim = {}, 0, False        # nfs: nf_id -> comp
            for _, nid, val, comp in saidas:
                if nid in nfs:
                    if nfs[nid] != comp:           # mesma NF, competencia diferente
                        ruim = True; break
                    continue                       # duplicata identica: ignora
                nfs[nid] = comp; valor += val
            if ruim:
                resumo["grupo_incompleto"] += 1
                continue
            if conflit.intersection(nfs):
                resumo["nf_duplicada"] += 1
                continue
            ct, numero, tipo = chave
            cnt = Counter(nfs.values())
            mais = max(cnt.values())
            comp = min(c for c, n in cnt.items() if n == mais)   # mais frequente; empate -> mais antiga
            if len(cnt) > 1:
                resumo["competencia_incoerente"] += 1
            p = {"contrato_id": ct, "numero": numero, "tipo": tipo, "competencia": comp,
                 "valor_centavos": valor, "nfs": len(nfs)}
            plano.append(p)
            resumo["grupos"] += 1
            resumo["nfs_cobertas"] += len(nfs)
            if aplicar:
                mid = medicoes.criar(conn, usuario_id, {"contrato_id": ct, "numero": numero,
                                                        "tipo": tipo, "competencia": comp})
                medicoes.definir_valor(conn, usuario_id, mid, "protocolado", valor, "aceito")
                medicoes.registrar_protocolo(
                    conn, usuario_id, mid, _ultimo_dia(comp), None, None, "aceito",
                    apesar_das_pendencias=True,
                    justificativa="Carga do historico: medicao faturada no ledger antigo sem entrar na lista "
                                  "de medicoes; valor da(s) NF(s) do RM, data estimada pelo fim da competencia, "
                                  "sem numero de oficio.")
                p["medicao_id"] = mid
                resumo["criadas"] += 1

    if aplicar:
        with db.mutacao(conn):
            montar_e_criar()
    else:
        montar_e_criar()
    resumo["plano"] = plano
    return resumo
