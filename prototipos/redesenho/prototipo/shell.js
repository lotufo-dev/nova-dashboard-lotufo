// Casca dos protótipos: o trilho índigo e a barra superior iguais aos do sistema (Casca.tsx).
// Uso: <body data-secao="obras" data-titulo="Obras"> com o conteúdo dentro de <main id="conteudo">.
(function () {
  const IC = {
    inicio: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
    medicoes: '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M16 2v4M8 2v4M3 10h18M8 14h3M8 17h6"/>',
    obras: '<path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 21v-6h6v6"/><path d="M9 10h.01M15 10h.01"/>',
    documentos: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M9 13h6M9 17h4"/>',
    "a-receber": '<path d="M12 2v20"/><path d="M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    carteira: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    admin: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>'
  };
  const ITENS = [["inicio","Início","index.html"],["medicoes","Medições","enviar-nota.html"],["obras","Obras","obras.html"],
    ["documentos","Documentos","documentos.html"],["a-receber","A receber","a-receber.html"],["carteira","Carteira","carteira.html"],["admin","Administração","administracao.html"]];
  const svg = d => '<svg class="icone trilho__icone" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
  const b = document.body, secao = b.dataset.secao || "", titulo = b.dataset.titulo || "";
  const main = document.getElementById("conteudo");
  const nav = '<nav class="trilho" aria-label="Navegação principal"><div class="trilho__bloco">' +
    '<span class="trilho__marca" aria-hidden="true"><span class="trilho__celula"><svg class="trilho__simbolo" viewBox="0 0 22 34" fill="currentColor"><rect x="0" y="0" width="10" height="10" rx="2"/><rect x="0" y="12" width="10" height="10" rx="2"/><rect x="0" y="24" width="10" height="10" rx="2"/><rect x="12" y="24" width="10" height="10" rx="2"/></svg></span>' +
    '<span class="trilho__rotulo trilho__nome"><span class="trilho__nome-1">grupolotufo</span><span class="trilho__nome-2">Plataforma de Obras</span></span></span>' +
    ITENS.map(([k, r, h]) => '<a class="trilho__item" href="' + h + '"' + (k === secao ? ' aria-current="page"' : '') + '><span class="trilho__celula">' + svg(IC[k]) + '</span><span class="trilho__rotulo">' + r + '</span></a>').join("") +
    '</div></nav>';
  const barra = '<header class="barra"><p class="barra__titulo">' + titulo + '</p><div class="conta"><a class="conta__botao" href="minha-conta.html" style="text-decoration:none"><span class="conta__avatar" aria-hidden="true">US</span><span class="conta__nome">Usuário de exemplo</span></a></div></header>';
  const shell = document.createElement("div"); shell.className = "shell";
  shell.innerHTML = nav + '<div class="coluna">' + barra + '</div>';
  main.classList.add("principal");
  shell.querySelector(".coluna").appendChild(main);
  b.prepend(shell);
  // Aviso de protótipo e botões que só mostram o que fariam.
  const faixa = document.createElement("div");
  faixa.className = "proto-faixa";
  faixa.innerHTML = 'Protótipo com dados inventados · <a href="index.html">Voltar à lista de protótipos</a>';
  b.prepend(faixa);
  window.protoAviso = function (txt) {
    let t = document.getElementById("proto-toast");
    if (!t) { t = document.createElement("div"); t.id = "proto-toast"; t.setAttribute("role", "status"); b.appendChild(t); }
    t.textContent = txt; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), 2600);
  };
  document.addEventListener("click", e => {
    const el = e.target.closest("[data-acao]");
    if (el) { e.preventDefault(); window.protoAviso(el.dataset.acao); }
  });
})();
