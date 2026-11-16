// Simbolo da marca: o L da empresa em vetor. A haste em L herda a cor do texto (currentColor); o bloco do canto e' o
// laranja da marca (--cor-marca), o unico lugar fixo do laranja alem do item ativo do menu e do foco na casca escura.
export default function Simbolo({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 506 524" aria-hidden="true" focusable="false">
      <path fill="currentColor" d="M72 13H130V325C130 400 190 472 330 477L478 481C490 481 492 488 484 494L462 507Q456 511 448 511H72C40 511 14 485 14 453V71C14 39 40 13 72 13Z" />
      <path fill="var(--cor-marca)" d="M258 13H432C465 13 492 40 492 73V351H345C297 351 258 312 258 264Z" />
    </svg>
  );
}
