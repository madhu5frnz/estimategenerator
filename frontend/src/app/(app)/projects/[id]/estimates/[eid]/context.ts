import type { Template, Unit, Version } from "@/lib/api";

export type Mutate = (request: () => Promise<Version>) => Promise<Version>;

export type WorkspaceProps = {
  version: Version;
  mutate: Mutate;
  units: Unit[];
  templates: Template[];
  editable: boolean;
};

/** Units an item can be measured in, grouped the way engineers look for them. */
export const ITEM_UNIT_ORDER = ["cum", "sqm", "rmt", "m", "nos", "kg", "mt", "qtl", "cuft", "sqft", "l", "set", "ls", "km", "mm", "cm", "ft", "acre", "ha", "kgpm"];

export function sortUnits(units: Unit[]): Unit[] {
  const rank = (code: string) => {
    const i = ITEM_UNIT_ORDER.indexOf(code);
    return i === -1 ? 99 : i;
  };
  return [...units].sort((a, b) => rank(a.code) - rank(b.code));
}

export const LENGTH_UNITS = ["m", "mm", "cm", "ft", "km"];
