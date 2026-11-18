// Fundo do login: ponte, rodovia, edificio e hospital se desenhando aresta por aresta.
// Portado de prototipos/login-3d/index.html (aprovado em 08/10/2026). Carregado por import()
// dinamico no Login, para o Three nao entrar no pacote das outras telas.
import * as THREE from "three";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/examples/jsm/lines/LineSegmentsGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";

type V = number[];
type Seg = [V, V, number];

// ================= construtor de arestas =================
// k: 0 = silhueta estrutural, 1 = elemento/detalhe, 2 = terreno, cota, eixo
let S: Seg[] = [];
const L = (a: V, b: V, k = 0) => { S.push([a, b, k]); };
const poly = (p: V[], fechado = false, k = 0) => { for (let i = 0; i < p.length - 1; i++) L(p[i], p[i + 1], k); if (fechado) L(p[p.length - 1], p[0], k); };
const retY = (x0: number, z0: number, x1: number, z1: number, y: number, k = 0) => poly([[x0, y, z0], [x1, y, z0], [x1, y, z1], [x0, y, z1]], true, k);
const caixa = (x0: number, y0: number, z0: number, x1: number, y1: number, z1: number, k = 0) => { retY(x0, z0, x1, z1, y0, k); for (const [x, z] of [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]) L([x, y0, z], [x, y1, z], k); retY(x0, z0, x1, z1, y1, k); };
const circ = (cx: number, y: number, cz: number, r: number, n = 32): V[] => Array.from({ length: n }, (_, i) => { const a = i / n * Math.PI * 2; return [cx + r * Math.cos(a), y, cz + r * Math.sin(a)]; });
const anel = (cx: number, y: number, cz: number, r: number, n = 32, k = 0) => poly(circ(cx, y, cz, r, n), true, k);
const cil = (cx: number, cz: number, r: number, y0: number, y1: number, k = 0, n = 20, g = 8) => { anel(cx, y0, cz, r, n, k); for (let i = 0; i < g; i++) { const a = Math.PI / g + i * 2 * Math.PI / g; L([cx + r * Math.cos(a), y0, cz + r * Math.sin(a)], [cx + r * Math.cos(a), y1, cz + r * Math.sin(a)], k); } anel(cx, y1, cz, r, n, k); };
const lerp = (a: V, b: V, t: number): V => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
const trac = (a: V, b: V, traco: number, vao: number, k = 2) => { const d = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]); for (let s = 0; s < d; s += traco + vao) L(lerp(a, b, s / d), lerp(a, b, Math.min(s + traco, d) / d), k); };
// cota: linha de cota deslocada por "off", linhas de chamada e tiques a 45 graus
const cota = (a: V, b: V, off: V, k = 2) => {
  const A = [a[0] + off[0], a[1] + off[1], a[2] + off[2]], B = [b[0] + off[0], b[1] + off[1], b[2] + off[2]];
  const ext = 1.12; L(a, [a[0] + off[0] * ext, a[1] + off[1] * ext, a[2] + off[2] * ext], k); L(b, [b[0] + off[0] * ext, b[1] + off[1] * ext, b[2] + off[2] * ext], k); L(A, B, k);
  const u = [B[0] - A[0], B[1] - A[1], B[2] - A[2]], lu = Math.hypot(...u) || 1, on = Math.hypot(...off) || 1, t = [(u[0] / lu + off[0] / on) * .45, (u[1] / lu + off[1] / on) * .45, (u[2] / lu + off[2] / on) * .45];
  for (const P of [A, B]) L([P[0] - t[0], P[1] - t[1], P[2] - t[2]], [P[0] + t[0], P[1] + t[1], P[2] + t[2]], k);
};
// arvore: copa irregular em dois niveis e tronco
const arvore = (x: number, z: number, r: number, sem = 1) => { for (const [y, f] of [[3.4, .8], [5, 1]]) { const p: V[] = []; for (let i = 0; i < 14; i++) { const a = i / 14 * Math.PI * 2, rr = r * f * (1 + .18 * Math.sin(3 * a + sem) + .1 * Math.cos(5 * a + sem * 2)); p.push([x + rr * Math.cos(a), y + Math.sin(a * 2 + sem) * .3, z + rr * Math.sin(a)]); } poly(p, true, 2); } L([x - .15, 0, z], [x - .15, 3.2, z], 2); L([x + .15, 0, z], [x + .15, 3.2, z], 2); };
// escada em U entre y0 e y1, caixa x0..x1, z0..z1 (lances ao longo de z)
const escada = (x0: number, x1: number, z0: number, z1: number, y0: number, y1: number, k = 1) => {
  const h = (y1 - y0) / 2, n = Math.max(6, Math.round(h / .178)), pz = (z1 - z0 - 1.2) / n, xm = (x0 + x1) / 2;
  const lance = (xa: number, xb: number, ya: number, za: number, dir: number) => { const p: V[] = []; let y = ya, z = za; p.push([xa, y, z]); for (let i = 0; i < n; i++) { y += h / n; p.push([xa, y, z]); z += dir * pz; p.push([xa, y, z]); } poly(p, false, k); L([xb, ya, za], [xb, ya + h, za + dir * pz * n], 2); };
  lance(x0, xm - .1, y0, z0, 1); retY(x0, z1 - 1.2, x1, z1, y0 + h, k); lance(x1, xm + .1, y0 + h, z1 - 1.2, -1);
};

// ================= 1. PONTE =================
function ponte() {
  S = [];
  const g = (x: number) => Math.abs(x) < 70 ? -8 * (1 - (x / 70) ** 2) : 0, YD = 12.25, GZ = [-4.95, -1.65, 1.65, 4.95];
  for (let y = -7; y <= 1; y += 2) { const x0 = 70 * Math.sqrt(1 + Math.min(y, 0) / 8) + Math.max(y, 0) * 6; for (const s of [-1, 1]) { const p: V[] = []; for (let z = -30; z <= 30; z += 2) p.push([s * (x0 + Math.sin(z * .17 + y * 1.3) * .7), y, z]); poly(p, false, 2); } }
  for (const xm of [-11, 11]) { const p: V[] = []; for (let z = -44; z <= 44; z += 2) p.push([xm + Math.sin(z * .11) * 1.6, -7.8, z]); poly(p, false, 1); }
  { const p: V[] = []; for (let z = -44; z <= 44; z += 2) p.push([Math.sin(z * .11) * 1.6, -8, z]); poly(p, false, 2); }
  // fundacoes: estacas (tracejadas, enterradas) e blocos
  for (const x of [-35, 0, 35]) {
    const y0 = g(x);
    for (const dx of [-1.6, 1.6]) for (const z of [-4.5, -1.5, 1.5, 4.5]) trac([x + dx, y0 - 2, z], [x + dx, y0 - 16, z], .8, .8, 2);
    caixa(x - 2.6, y0 - 2, -6.2, x + 2.6, y0, 6.2, 1);
  }
  // pilares e travessas
  for (const x of [-35, 0, 35]) {
    const y0 = g(x); for (const z of [-3.6, 3.6]) cil(x, z, .8, y0, 8, 1);
    caixa(x - 1.3, 8, -6.8, x + 1.3, 9.45, 6.8, 1); L([x - 1.3, 9.45, -6.8], [x - 1.3, 9.45, 6.8], 0); L([x + 1.3, 9.45, -6.8], [x + 1.3, 9.45, 6.8], 0);
  }
  // encontros e alas
  for (const s of [-1, 1]) {
    const xf = s * 70, xm = s * 71.4, xc = s * 72;
    caixa(Math.min(xf, xm), -2, -7.5, Math.max(xf, xm), 9.45, 7.5, 1); caixa(Math.min(xm, xc), 9.45, -7.5, Math.max(xm, xc), 12, 7.5, 1);
    L([xf, 9.45, -7.5], [xf, 9.45, 7.5], 0);
    for (const z of [-7.5, 7.5]) poly([[xc, -2, z], [xc, 12, z], [xc + s * 7, 12, z], [xc + s * 7, 7.5, z]], false, 1);
  }
  // aterros de acesso (talude 1:1,5)
  for (const s of [-1, 1]) {
    for (const z of [-7.5, 7.5]) L([s * 72, YD, z], [s * 104, YD, z], 1); for (const z of [-25.9, 25.9]) L([s * 72, 0, z], [s * 104, 0, z], 2);
    for (let x = 74; x <= 104; x += 6) { const X = s * x; poly([[X, 0, -25.9], [X, YD, -7.5], [X, YD, 7.5], [X, 0, 25.9]], false, 2); }
  }
  // aparelhos de apoio
  for (const x of [-70.6, -35.8, -34.2, -.8, .8, 34.2, 35.8, 70.6]) for (const z of GZ) caixa(x - .3, 9.45, z - .35, x + .3, 9.8, z + .35, 1);
  // vigas I pre-moldadas h = 2,20 m
  const perfil = (x: number, z: number) => poly([[x, 9.8, z - .35], [x, 9.8, z + .35], [x, 10.15, z + .35], [x, 10.15, z + .09], [x, 11.75, z + .09], [x, 11.75, z + .55], [x, 12, z + .55], [x, 12, z - .55], [x, 11.75, z - .55], [x, 11.75, z - .09], [x, 10.15, z - .09], [x, 10.15, z - .35]], true, 0);
  const vaos = [[-71, -35.4], [-34.6, -.4], [.4, 34.6], [35.4, 71]];
  for (const [a, b] of vaos) for (const z of GZ) {
    perfil(a, z);
    for (const zz of [z - .35, z + .35]) { L([a, 9.8, zz], [b, 9.8, zz], 1); L([a, 10.15, zz], [b, 10.15, zz], 2); }
    L([a, 10.95, z], [b, 10.95, z], 2); for (const zz of [z - .55, z + .55]) { L([a, 11.75, zz], [b, 11.75, zz], 2); L([a, 12, zz], [b, 12, zz], 1); } perfil(b, z);
  }
  for (const x of [-70.8, -53, -35, -17.5, 0, 17.5, 35, 53, 70.8]) caixa(x - .15, 10.15, -4.95, x + .15, 11.6, 4.95, 2);
  // laje
  caixa(-72, 12, -6.8, 72, YD, 6.8, 0);
  // barreiras New Jersey
  for (const s of [-1, 1]) {
    const pf = [[6.8, 0], [6.38, 0], [6.3, .08], [6.5, .33], [6.62, .87], [6.8, .87]].map(([z, y]) => [s * z, YD + y]);
    for (const x of [-72, 72]) poly(pf.map(([z, y]) => [x, y, z]), true, 1);
    L([-72, YD + .87, s * 6.62], [72, YD + .87, s * 6.62], 1); L([-72, YD + .87, s * 6.8], [72, YD + .87, s * 6.8], 1); L([-72, YD + .33, s * 6.5], [72, YD + .33, s * 6.5], 2); L([-72, YD, s * 6.38], [72, YD, s * 6.38], 2);
  }
  // sinalizacao, juntas, drenos
  trac([-104, YD + .01, 0], [104, YD + .01, 0], 4, 12, 2); for (const z of [-5.4, 5.4]) L([-104, YD + .01, z], [104, YD + .01, z], 2);
  for (const x of [-70.8, -35, 0, 35, 70.8]) L([x, YD + .01, -6.3], [x, YD + .01, 6.3], 2);
  for (let x = -65; x <= 65; x += 10) for (const s of [-1, 1]) L([x, 12, s * 6.6], [x, 10.6, s * 6.6], 2);
  for (const x of [-52.5, -17.5, 17.5, 52.5]) { const s = x < 0 ? -1 : 1; L([x, YD + .87, s * 6.7], [x, YD + 9, s * 6.7], 1); L([x, YD + 9, s * 6.7], [x, YD + 9, s * 4.7], 1); L([x, YD + 8.8, s * 4.7], [x, YD + 8.8, s * 4.1], 1); }
  // cotas: vaos e altura do pilar
  for (let i = 0; i < 4; i++) { const a = -70 + 35 * i, b = a + 35; cota([a, 9.8, -9], [b, 9.8, -9], [0, -3.4, 0]); }
  cota([38, g(35), -9], [38, 8, -9], [3, 0, 0]);
  return S;
}

// ================= 2. RODOVIA =================
// pista=true: as linhas da pista seguem 0,5 rad alem da obra para cada lado, num traco so', ate sumir
// na neblina; com false sai so' a obra, usada para enquadrar a camera.
function rodovia(pista = true) {
  S = [];
  const R = 350, t0 = -.3, t1 = .3, N = 120, E = .07, X = pista ? .5 : 0, a0 = t0 - X, a1 = t1 + X, NA = Math.round(N * (a1 - a0) / (t1 - t0));
  const P = (t: number, o: number, y: number): V => [Math.sin(t) * (R + o), y, R - Math.cos(t) * (R + o)];
  const st = (i: number) => t0 + (t1 - t0) * i / N, sa = (i: number) => a0 + (a1 - a0) * i / NA, sup = (o: number) => o * E;
  const ao = (o: number, y: number, k: number, n = NA, t = sa) => { const p: V[] = []; for (let i = 0; i <= n; i++) p.push(P(t(i), o, y)); poly(p, false, k); };
  const aoT = (o: number, y: number, traco: number, vao: number, k: number) => { const tot = (a1 - a0) * (R + o); for (let s = 0; s < tot; s += traco + vao) { const p: V[] = []; for (let j = 0; j <= 4; j++) { const ss = Math.min(s + traco * j / 4, tot); p.push(P(a0 + ss / (R + o), o, y)); } poly(p, false, k); } };
  // secao transversal: corte (lado interno) e aterro (lado externo)
  const secao = [[-48, 2.21], [-17.5, 2.21], [-17.1, 1.81], [-16.7, 1.81], [-16.3, 2.21], [-15.3, 2.21], [-12.3, -.79], [-12, -1.09], [-11.6, -1.09], [-11.3, sup(-11.3)], [11.3, sup(11.3)], [16.99, -3], [18.2, -3], [18.6, -3.4], [19, -3.4], [19.4, -3], [48, -3]];
  // linhas longitudinais: terreno, plataforma, faixas, eixo e barreira central
  const longas = [...secao.filter(([o]) => Math.abs(o) !== 11.3).map(([o, y]) => [o, y, [-15.3, -12.3, 16.99].includes(o) ? 1 : 2]),
    ...[-11.3, 11.3].map(o => [o, sup(o), 0]), ...[-8.8, -1.6, 1.6, 8.8].map(o => [o, sup(o), 1]), ...[-.45, .45].map(o => [o, sup(o), 2]),
    [-.15, .87, 1], [.15, .87, 1]];
  for (const [o, y, k] of longas) ao(o, y, k);
  for (let i = 0; i <= NA; i += 10) { const t = sa(i); poly(secao.slice(0, 10).map(([o, y]) => P(t, o, y)), false, 2); poly(secao.slice(10).map(([o, y]) => P(t, o, y)), false, 2); }
  for (const o of [-5.2, 5.2]) aoT(o, sup(o) + .01, 4, 12, 2);
  // defensa no bordo do aterro, so' na obra (na pista os montantes viram uma faixa hachurada)
  ao(11.55, sup(11.3) + .75, 2, N, st); for (let i = 0; i <= N; i += 2) L(P(st(i), 11.55, sup(11.3)), P(st(i), 11.55, sup(11.3) + .75), 2);
  // iluminacao no canteiro e portico de sinalizacao
  for (let i = 8; i < N; i += 17) { const t = st(i); L(P(t, 0, .87), P(t, 0, 12), 1); for (const s of [-1, 1]) { L(P(t, 0, 12), P(t, s * 2.6, 12), 1); L(P(t, s * 2.6, 11.8), P(t, s * 3.2, 11.8), 1); } }
  { const t = st(78); for (const o of [1, 11]) L(P(t, o, sup(o)), P(t, o, 7.4), 1); for (const y of [7.4, 6.8]) L(P(t, 1, y), P(t, 11, y), 1); poly([P(t, 2.6, 4.8), P(t, 9.6, 4.8), P(t, 9.6, 6.6), P(t, 2.6, 6.6)], true, 1); }
  return S;
}

// ================= 3. EDIFICIO =================
function predio() {
  S = [];
  const X = [-12, -6, 0, 6, 12], Z = [-8, 0, 8], F = 8, HT = 6, H = 3.2, yf = (f: number) => f === 0 ? 0 : HT + (f - 1) * H, yt = yf(F);
  // entorno: lote, calcada com meio-fio, rua, faixa de pedestres, arvores
  retY(-28, -18, 28, 22, 0, 2);
  for (const y of [0, .15]) L([-40, y, -18], [40, y, -18], 2); L([-40, 0, -28], [40, 0, -28], 2); trac([-40, 0, -23], [40, 0, -23], 3, 3, 2);
  for (let x = -22; x <= -16; x += .8) L([x, 0, -22], [x, 0, -19], 2);
  arvore(-22, -12, 3.4, 1); arvore(-19, 15, 2.8, 2); arvore(23, -8, 3.8, 3); arvore(25, 14, 2.6, 4);
  // eixos (A-E / 1-3)
  for (const x of X) trac([x, .02, -14], [x, .02, 13], 1.2, .8, 2); for (const z of Z) trac([-18, .02, z], [18, .02, z], 1.2, .8, 2);
  for (let f = 0; f < F; f++) {
    const y0 = yf(f), y1 = yf(f + 1);
    for (const x of X) for (const z of Z) L([x, y0, z], [x, y1 - .25, z], 0);
    // nucleo: 2 pocos de elevador + escada em U
    caixa(-2.5, y0, -3.4, -.7, y1 - .25, -1.3, 1); caixa(.7, y0, -3.4, 2.5, y1 - .25, -1.3, 1);
    escada(-2.4, 2.4, -.6, 5.6, y0, y1, 1);
    // laje e vigas de borda
    caixa(-12.6, y1 - .25, -8.6, 12.6, y1, 8.6, 1); retY(-12.6, -8.6, 12.6, 8.6, y1, 0);
    for (const z of [-8.45, 8.45]) L([-12.45, y1 - .85, z], [12.45, y1 - .85, z], 1); for (const x of [-12.45, 12.45]) L([x, y1 - .85, -8.45], [x, y1 - .85, 8.45], 1);
    if (f === 0) {
      // terreo: vidro recuado 2 m, portaria e marquise de 3 m
      L([-12, .02, -6], [12, .02, -6], 1); for (let x = -12; x <= 12; x += 3) L([x, 0, -6], [x, 3.4, -6], 2); L([-12, 3.4, -6], [12, 3.4, -6], 1);
      caixa(-6, 3.6, -11, 6, 3.85, -8.6, 1); poly([[-1.2, 0, -6], [-1.2, 2.4, -6], [1.2, 2.4, -6], [1.2, 0, -6]], false, 1);
    } else {
      // fachadas visiveis (-z e +x): peitoril, verga, montantes nos pilares
      for (const yy of [y0 + .95, y1 - .45]) { L([-12.6, yy, -8.6], [12.6, yy, -8.6], 1); L([12.6, yy, -8.6], [12.6, yy, 8.6], 1); }
      for (let x = -12; x <= 12; x += 3) L([x, y0 + .95, -8.62], [x, y1 - .45, -8.62], 2); for (let z = -8; z <= 8; z += 2) L([12.62, y0 + .95, z], [12.62, y1 - .45, z], 2);
      for (const [a, b] of [[-11, -4], [4, 11]]) { caixa(a, y0, -10.4, b, y0 + .18, -8.6, 1); L([a, y0 + 1.1, -10.4], [b, y0 + 1.1, -10.4], 1); for (let x = a; x <= b + .01; x += 1.75) L([x, y0 + .18, -10.4], [x, y0 + 1.1, -10.4], 2); }
    }
  }
  // cobertura: platibanda, casa de maquinas, caixa d'agua, antena
  caixa(-12.6, yt, -8.6, 12.6, yt + 1.1, 8.6, 0); caixa(-2.8, yt, -3.6, 2.8, yt + 3.2, 6, 1); caixa(-2.2, yt + 3.2, -2.4, 2.2, yt + 5, 2.4, 1); L([1.5, yt + 5, 1.5], [1.5, yt + 9.5, 1.5], 2);
  // cotas de pe-direito
  cota([14.5, HT, -10], [14.5, HT + H, -10], [1.6, 0, 0]); cota([14.5, 0, -10], [14.5, HT, -10], [1.6, 0, 0]);
  return S;
}

// ================= 4. HOSPITAL =================
function hospital() {
  S = [];
  const H = 4, blocos = [{ x0: -36, x1: 36, z0: -9, z1: 9, n: 4, ala: 0 }, { x0: -31, x1: -17, z0: 9, z1: 34, n: 3, ala: 1 }, { x0: 17, x1: 31, z0: 9, z1: 34, n: 3, ala: 1 }];
  // entorno: lote, rua, estacionamento, arvores
  retY(-52, -30, 62, 48, 0, 2); for (const y of [0, .15]) L([-70, y, -34], [70, y, -34], 2); trac([-70, 0, -40], [70, 0, -40], 3, 3, 2);
  for (let x = -48; x <= -6; x += 2.5) L([x, 0, -31], [x, 0, -26], 2); L([-48, 0, -26], [-6, 0, -26], 2);
  arvore(-46, 22, 3.4, 1); arvore(-41, 40, 2.8, 2); arvore(54, -22, 3.6, 3); arvore(4, 42, 3, 4); arvore(56, 40, 2.6, 5);
  for (const b of blocos) trac([b.x0, .02, (b.z0 + b.z1) / 2], [b.x1, .02, (b.z0 + b.z1) / 2], 1.2, .8, 2);
  for (const b of blocos) retY(b.x0, b.z0, b.x1, b.z1, 0, 1);
  for (let f = 0; f < 4; f++) {
    const y0 = f * H, y1 = y0 + H;
    for (const b of blocos) {
      if (f >= b.n) continue;
      for (let x = b.x0; x <= b.x1 + .01; x += 6) for (const z of [b.z0, b.z1]) L([x, y0, z], [x, y1, z], 1);
      for (let z = b.z0 + 6; z < b.z1; z += 6) for (const x of [b.x0, b.x1]) L([x, y0, z], [x, y1, z], 1);
      if (b.ala) { for (let j = 1; j <= 3; j++) { const yy = y0 + j; for (const x of [b.x0 - .6, b.x1 + .6]) L([x, yy, b.z0 + 1], [x, yy, b.z1], 1); L([b.x0 - .6, yy, b.z1 + .6], [b.x1 + .6, yy, b.z1 + .6], 1); } }
      else {
        for (const yy of [y0 + 1, y0 + 3]) { for (const z of [b.z0, b.z1]) L([b.x0, yy, z], [b.x1, yy, z], 1); for (const x of [b.x0, b.x1]) L([x, yy, b.z0], [x, yy, b.z1], 1); }
        for (const z of [-2, 2]) L([b.x0, y1 - .35, z], [b.x1, y1 - .35, z], 2);
        caixa(-4, y0, -3, 4, y1 - .35, 3, 2); escada(-3.8, -.2, -2.8, 2.8, y0, y1, 2);
      }
      caixa(b.x0 - .4, y1 - .35, b.z0 - .4, b.x1 + .4, y1, b.z1 + .4, 0);
    }
  }
  // passarela entre as alas
  caixa(-17, 4, 20, 17, 8, 24, 1); for (let x = -14; x <= 14; x += 3) L([x, 4.6, 20], [x, 7.6, 20], 2);
  // acesso principal e patio de emergencia com rampa
  caixa(-11, 4.2, -17, 11, 4.6, -9, 1); for (const x of [-10, 10]) cil(x, -16, .35, 0, 4.2, 1, 12, 4);
  caixa(36, 4.2, -13, 46, 4.6, 13, 0); for (const z of [-12, 12]) cil(45, z, .35, 0, 4.2, 1, 12, 4);
  poly([[46, .96, -6], [58, 0, -6], [58, 0, 6], [46, .96, 6]], false, 0); for (let z = -6; z <= 4.5; z += 3.5) L([37, .02, z], [46, .02, z], 2);
  // central de utilidades com tanques
  caixa(36, 0, 27, 44, 4, 33, 1); for (const x of [48, 51]) cil(x, 30, 1.2, 0, 4, 1, 16, 4);
  // casas de maquinas nas alas
  for (const x of [-24, 24]) caixa(x - 3, 12, 24, x + 3, 14.2, 30, 1);
  // heliponto
  const yh = 16; caixa(-8.5, yh, -8.5, 8.5, yh + .8, 8.5, 1); anel(0, yh + .82, 0, 7.6, 48, 0); anel(0, yh + .82, 0, 6.6, 48, 1); anel(0, yh + .9, 0, 9.6, 48, 2);
  for (let i = 0; i < 8; i++) { const a = i / 8 * Math.PI * 2; L([7.6 * Math.cos(a), yh + .82, 7.6 * Math.sin(a)], [7.6 * Math.cos(a), yh + 1.25, 7.6 * Math.sin(a)], 1); }
  const yH = yh + .84; L([-2.2, yH, -3.2], [-2.2, yH, 3.2], 0); L([2.2, yH, -3.2], [2.2, yH, 3.2], 0); L([-2.2, yH, 0], [2.2, yH, 0], 0);
  return S;
}

const OBRAS = [
  { f: ponte, elev: .3, az0: -1.0, zoom: .55, alvo: [0, 4, 0] },
  { f: rodovia, quadro: () => rodovia(false), elev: .55, az0: -1.25, zoom: .44, alvo: [-10, 0, 4] },
  { f: predio, elev: .23, az0: -.75, zoom: .78, alvo: [0, 13, 0] },
  { f: hospital, elev: .4, az0: .6, zoom: .6, alvo: [6, 5, 8] },
];

// As cores do desenho sao as variaveis da fundacao (tokens.css), lidas do proprio canvas: o traco forte no texto do
// menu, o medio e o fino nos tons de apoio, a neblina na cor do menu. Nenhum tom fora da marca (laranja, preto, branco).
const ESTILO = [{ cor: "--cor-menu-texto", w: 1.8, op: 1 }, { cor: "--cor-menu-texto-secundario", w: 1.1, op: 1 }, { cor: "--cor-texto-terciario", w: .8, op: .9 }];
// sem arranco: senoide em vez de cubica (pico de velocidade ~pela metade)
const DES = 16, PARA = 4, SAI = 2, CICLO = DES + PARA + SAI;
const ease = (t: number) => (1 - Math.cos(Math.PI * t)) / 2;

/**
 * Liga o fundo no canvas e devolve a funcao de limpeza.
 * Lanca se o WebGL nao abrir; chama aoFalhar se um quadro der erro depois (o laco para).
 * Com parado=true desenha a primeira obra completa, sem animar (prefers-reduced-motion).
 */
export function iniciarFundo(canvas: HTMLCanvasElement, parado: boolean, aoFalhar: () => void): () => void {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  const scene = new THREE.Scene();
  const css = getComputedStyle(canvas);
  // sem a variavel (folha ainda nao aplicada), o traco fica na cor do texto do canvas
  const tom = (nome: string) => css.getPropertyValue(nome).trim() || css.color;
  const fog = new THREE.Fog(tom("--cor-menu"), 200, 600);
  scene.fog = fog;
  const camera = new THREE.PerspectiveCamera(36, 1, .5, 3000);
  const mats: LineMaterial[] = [];
  const geos: LineSegmentsGeometry[] = [];
  const novoMat = (cor: string, w: number, op: number, add: boolean) => {
    const m = new LineMaterial({ color: cor, linewidth: w, transparent: true, opacity: op, depthWrite: !add, blending: add ? THREE.AdditiveBlending : THREE.NormalBlending });
    m.fog = true; mats.push(m); return m;
  };

  const CAUDA = 40;
  const cenas = OBRAS.map(o => {
    const segs = o.f(), n = segs.length, bb = new THREE.Box3();
    const porTipo: number[][] = [[], [], []], acum = [new Int32Array(n + 1), new Int32Array(n + 1), new Int32Array(n + 1)], todas = new Float32Array(n * 6);
    segs.forEach(([a, b, k], i) => {
      porTipo[k].push(...a, ...b); todas.set(a, i * 6); todas.set(b, i * 6 + 3); for (let j = 0; j < 3; j++) acum[j][i + 1] = acum[j][i] + (j === k ? 1 : 0);
    });
    // a camera enquadra a obra; a pista que segue alem dela nao conta
    for (const [a, b] of o.quadro?.() ?? segs) { bb.expandByPoint(new THREE.Vector3(a[0], a[1], a[2])); bb.expandByPoint(new THREE.Vector3(b[0], b[1], b[2])); }
    const grupo = new THREE.Group();
    const camadas = porTipo.map((arr, k) => {
      if (!arr.length) return null;
      const g = new LineSegmentsGeometry(); g.setPositions(arr); geos.push(g);
      const st = ESTILO[k], mat = novoMat(tom(st.cor), st.w, st.op, false), ln = new LineSegments2(g, mat); ln.frustumCulled = false; grupo.add(ln);
      return { g, mat, op: st.op };
    });
    const gc = new LineSegmentsGeometry(); gc.setPositions(new Float32Array(CAUDA * 6)); geos.push(gc);
    const mc = novoMat(tom("--cor-sobre-ponto"), 2.2, 1, true), cab = new LineSegments2(gc, mc); cab.frustumCulled = false; grupo.add(cab);
    grupo.visible = false; scene.add(grupo);
    return { ...o, n, acum, todas, camadas, gc, mc, grupo, raio: bb.getBoundingSphere(new THREE.Sphere()).radius };
  });

  let atual = -1, raf = 0, parou = false;
  const t0 = performance.now();

  function tamanho() {
    const w = canvas.clientWidth, h = canvas.clientHeight, pr = renderer.getPixelRatio();
    if (canvas.width !== Math.floor(w * pr) || canvas.height !== Math.floor(h * pr)) {
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.setViewOffset(w, h, 0, h * .07, w, h); camera.updateProjectionMatrix();
      for (const m of mats) m.resolution.set(w, h);
    }
  }

  function desenhar(t: number) {
    // painel 3D escondido (tela estreita): nao gasta GPU a toa
    if (!canvas.clientWidth || !canvas.clientHeight) return;
    tamanho();
    const i = Math.floor(t / CICLO) % cenas.length, lt = t % CICLO, o = cenas[i];
    if (i !== atual) { cenas.forEach((x, j) => { x.grupo.visible = j === i; }); atual = i; }
    const p = lt < DES ? ease(lt / DES) : 1, n = Math.floor(p * o.n);
    const sai = lt < DES + PARA ? 1 : Math.max(0, 1 - (lt - DES - PARA) / SAI);
    o.camadas.forEach((c, k) => { if (!c) return; c.g.instanceCount = o.acum[k][n]; c.mat.opacity = c.op * sai; });
    const ini = Math.max(0, n - CAUDA), m = n - ini;
    const buf = (o.gc.attributes.instanceStart as THREE.InterleavedBufferAttribute).data;
    (buf.array as Float32Array).set(o.todas.subarray(ini * 6, n * 6)); buf.needsUpdate = true; o.gc.instanceCount = m;
    o.mc.opacity = lt < DES ? 1 : Math.max(0, 1 - (lt - DES) / 1.5);
    const az = o.az0 + lt * .02, d = o.raio / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * o.zoom, e = o.elev;
    fog.near = d - o.raio * .3; fog.far = d + o.raio * 1.4;
    const c = new THREE.Vector3(o.alvo[0], o.alvo[1], o.alvo[2]);
    camera.position.set(c.x + d * Math.cos(e) * Math.cos(az), c.y + d * Math.sin(e), c.z + d * Math.cos(e) * Math.sin(az)); camera.lookAt(c);
    renderer.render(scene, camera);
  }

  function seguro(t: number): boolean {
    try { desenhar(t); return true; }
    catch { parou = true; aoFalhar(); return false; }
  }

  // Parado: primeira obra completa, ja sem a cauda branca (lt = DES + 2; ela some em 1,5 s).
  const T_PARADO = DES + 2;
  function quadro(agora: number) {
    if (parou) return;
    // o clamp em 0 evita tempo negativo no 1o quadro (bug do Edge visto no prototipo)
    if (seguro(Math.max(0, (agora - t0) / 1000))) raf = requestAnimationFrame(quadro);
  }
  const aoRedimensionar = () => { if (parado && !parou) seguro(T_PARADO); };

  if (parado) seguro(T_PARADO);
  else raf = requestAnimationFrame(quadro);
  window.addEventListener("resize", aoRedimensionar);

  return () => {
    parou = true;
    cancelAnimationFrame(raf);
    window.removeEventListener("resize", aoRedimensionar);
    for (const g of geos) g.dispose();
    for (const m of mats) m.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
  };
}
