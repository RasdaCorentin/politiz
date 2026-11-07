// Page « popularité » : barre d'opinion en tête, puis cote (candidats ou partis) et courbes.
// La cible (`cible` dans l'URL) se lit dans l'état de la page.
import { Barre } from "../components/Barre.jsx";
import { Cote } from "../components/Cote.jsx";

export function Popularite({ data, etat, onEtat }) {
  return (
    <>
      <Barre data={data} />
      <Cote data={data} cible={etat.cible} onCible={(c) => onEtat((e) => ({ ...e, cible: c }))} />
    </>
  );
}
