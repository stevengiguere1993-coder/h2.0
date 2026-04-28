export type {
  AnalyseInputs,
  AnalyseResultats,
  DepensesDetail,
  FraisDemarrageInputs,
  ScenarioId,
  ScenarioResultat,
} from "./types";

export { BAREMES, INPUTS_DEFAULTS, SCENARIO_PARAMS } from "./defaults";

export {
  concierge,
  entretien,
  gestion,
  hypothequeRCD,
  inoccupation,
  presentValue,
  tauxMensuelCanadien,
  thermopompes,
  valeurTGA,
  wifi,
} from "./formulas";

export { calculerAnalyse } from "./scenarios";
