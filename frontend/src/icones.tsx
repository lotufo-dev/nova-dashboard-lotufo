/* Icones desenhados (traco 1.6, grade 24) — o mundo visual proibe emoji/glifo
   unicode fazendo as vezes de icone. Todos herdam currentColor via .icone. */

type Props = { className?: string; titulo?: string };

function Svg({ className, titulo, children }: Props & { children: React.ReactNode }) {
  return (
    <svg className={className ?? "icone"} viewBox="0 0 24 24"
         role={titulo ? "img" : undefined} aria-hidden={titulo ? undefined : true}>
      {titulo && <title>{titulo}</title>}
      {children}
    </svg>
  );
}

export function IconeVoltar(p: Props) {
  return <Svg {...p}>
    <path d="M14 6.5 8.5 12l5.5 5.5" />
  </Svg>;
}

export function IconeCadeado(p: Props) {
  return <Svg {...p}>
    <rect x="4.5" y="10.5" width="15" height="10" rx="2.5" />
    <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
  </Svg>;
}

export function IconeBaixar(p: Props) {
  return <Svg {...p}>
    <path d="M20 15.5V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2.5" />
    <path d="M8 11.5 12 15.5l4-4" /><path d="M12 15.5V4" />
  </Svg>;
}

export function IconeAlerta(p: Props) {
  return <Svg {...p}>
    <path d="M10.3 3.9 2.6 17.4A2 2 0 0 0 4.3 20.4h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
    <path d="M12 9.5v4" /><path d="M12 17h.01" />
  </Svg>;
}

/* Seta de abrir e fechar (cartao recolhido): aponta para a direita e gira para baixo quando abre */
export function IconeSeta(p: Props) {
  return <Svg {...p}>
    <path d="M10 6.5 15.5 12 10 17.5" />
  </Svg>;
}

/* Nivel "Acao" do aviso (DESIGN.md › Colors, D2): o proximo passo e' seu. Circulo com seta, para
   diferir do triangulo do Critico e do ponto da Atencao pela FORMA, nao so' pela cor. */
export function IconeProximo(p: Props) {
  return <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M8.5 12h6.5" /><path d="M12.5 9 15.5 12l-3 3" />
  </Svg>;
}

/* Titulo da lista de avisos: sino NEUTRO. O triangulo e' a forma do nivel Critico (D2) e, no
   titulo, dizia "critico" para uma lista que e' quase toda atencao. */
export function IconeSino(p: Props) {
  return <Svg {...p}>
    <path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2H4.5z" />
    <path d="M10 20.5a2 2 0 0 0 4 0" />
  </Svg>;
}

export function IconeMais(p: Props) {
  return <Svg {...p}>
    <path d="M12 5.5v13" /><path d="M5.5 12h13" />
  </Svg>;
}

export function IconeFaisca(p: Props) {
  return <Svg {...p}>
    <path d="M12 3.5 13.7 9l5.5 1.7-5.5 1.7L12 17.9l-1.7-5.5L4.8 10.7 10.3 9z" />
    <path d="M18.5 3.5v3.4" /><path d="M20.2 5.2h-3.4" />
  </Svg>;
}

/* Mesa da engenharia: prancheta com a lista do dia (fila, parados, pendencias). */
export function IconeEngenharia(p: Props) {
  return <Svg {...p}>
    <rect x="5" y="4.5" width="14" height="16.5" rx="1.8" />
    <path d="M9 4.5V3.2h6v1.3" />
    <path d="M8.5 10.5h7" /><path d="M8.5 14h7" /><path d="M8.5 17.5h4" />
  </Svg>;
}

export function IconeInicio(p: Props) {
  return <Svg {...p}>
    <path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" />
  </Svg>;
}

/* Icones do trilho (09/10/2026, prototipo aprovado): o desenho do prototipo, no mesmo Svg da casa. */
export function IconeMedicoes(p: Props) {
  return <Svg {...p}>
    <rect x="3" y="4" width="18" height="17" rx="2" />
    <path d="M16 2v4M8 2v4M3 10h18M8 14h3M8 17h6" />
  </Svg>;
}

export function IconeObras(p: Props) {
  return <Svg {...p}>
    <path d="M3 21h18" /><path d="M5 21V7l7-4 7 4v14" /><path d="M9 21v-6h6v6" /><path d="M9 10h.01M15 10h.01" />
  </Svg>;
}

export function IconeDocumento(p: Props) {
  return <Svg {...p}>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M9 13h6M9 17h4" />
  </Svg>;
}

export function IconeCifrao(p: Props) {
  return <Svg {...p}>
    <path d="M12 2v20" /><path d="M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
  </Svg>;
}

export function IconeGrade(p: Props) {
  return <Svg {...p}>
    <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
  </Svg>;
}

export function IconeLinkExterno(p: Props) {
  return <Svg {...p}>
    <path d="M14 3h7v7M21 3l-9 9" /><path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5" />
  </Svg>;
}

export function IconeClipe(p: Props) {
  return <Svg {...p}>
    <path d="M21 11.5l-8.6 8.6a5 5 0 0 1-7.1-7.1l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4l7.9-7.9" />
  </Svg>;
}

export function IconeArquivo(p: Props) {
  return <Svg {...p}>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" />
  </Svg>;
}

export function IconeEnviarNuvem(p: Props) {
  return <Svg {...p}>
    <path d="M7 18a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 8.5a4 4 0 0 1-.5 9.5" /><path d="M12 12v8M9 15l3-3 3 3" />
  </Svg>;
}

export function IconeRelogio(p: Props) {
  return <Svg {...p}>
    <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
  </Svg>;
}

export function IconeAjustes(p: Props) {
  return <Svg {...p}>
    <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6" />
  </Svg>;
}

export function IconeOlho(p: Props) {
  return <Svg {...p}>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" />
  </Svg>;
}

export function IconeOlhoFechado(p: Props) {
  return <Svg {...p}>
    <path d="M3 3l18 18" />
    <path d="M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.2M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.6 9.6 0 0 0 5.4-1.6" />
    <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
  </Svg>;
}

/* Trilho › SIGA: o caminho do processo entre dois setores (origem e destino ligados por um trajeto). */
export function IconeSiga(p: Props) {
  return <Svg {...p}>
    <circle cx="6" cy="19" r="2.5" /><circle cx="18" cy="5" r="2.5" />
    <path d="M8.5 19H15a3.5 3.5 0 0 0 0-7H9a3.5 3.5 0 0 1 0-7h6.5" />
  </Svg>;
}
