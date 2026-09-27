"use client";

import { useState } from "react";

import { EditableCell } from "@/components/EditableCell";
import { Button, Input, Select } from "@/components/ui";
import { del, patch, post, type Item, type Section, type Version } from "@/lib/api";
import { inr } from "@/lib/format";

import { sortUnits, type WorkspaceProps } from "./context";

export function BoqTab({ version, mutate, units, editable, onShowLines }: WorkspaceProps & { onShowLines: () => void }) {
  const vid = version.version.id;
  const [newSection, setNewSection] = useState("");
  const itemUnits = sortUnits(units);

  const saveItem = (item: Item, field: string) => (value: string) =>
    mutate(() => patch<Version>(`/boq-items/${item.id}`, { [field]: value.trim() === "" ? null : value }));

  async function move(section: Section, index: number, delta: number) {
    const ids = section.items.map((i) => i.id);
    const [moved] = ids.splice(index, 1);
    if (!moved) return;
    ids.splice(index + delta, 0, moved);
    await mutate(() => post<Version>(`/versions/${vid}/boq-items/reorder`, { section_id: section.id, ids }));
  }

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded border border-line">
        <table className="w-full min-w-[980px] border-collapse text-left">
          <thead className="bg-panel text-xs text-muted uppercase">
            <tr>
              <th className="w-14 px-2 py-2">Sl.No</th>
              <th className="w-20 px-2 py-2">Item No</th>
              <th className="px-2 py-2">Description</th>
              <th className="w-24 px-2 py-2">Unit</th>
              <th className="w-32 px-2 py-2 text-right">Quantity</th>
              <th className="w-32 px-2 py-2 text-right">Rate ₹</th>
              <th className="w-36 px-2 py-2 text-right">Amount ₹</th>
              <th className="w-40 px-2 py-2">Remarks</th>
              {editable ? <th className="w-24 px-2 py-2" aria-label="Actions" /> : null}
            </tr>
          </thead>
          {version.sections.map((section) => (
            <tbody key={section.id} className="border-t-2 border-line">
              <tr className="bg-panel/60">
                <td className="px-2 py-1.5 font-semibold">{section.sl_no}</td>
                <td colSpan={5} className="py-1 font-semibold">
                  <EditableCell
                    label="Section title"
                    value={section.title}
                    editable={editable}
                    onSave={(title) => mutate(() => patch<Version>(`/sections/${section.id}`, { title }))}
                  />
                </td>
                <td className="num px-2 py-1.5 text-right font-semibold">{inr(section.subtotal)}</td>
                <td className="px-2 py-1.5 text-xs text-muted">
                  {section.unpriced_count ? `${section.unpriced_count} without rate` : ""}
                </td>
                {editable ? (
                  <td className="px-2 py-1.5 text-right">
                    <button
                      className="text-xs text-bad hover:underline"
                      onClick={() => {
                        const warn = section.items.length ? ` and its ${section.items.length} item(s)` : "";
                        if (window.confirm(`Delete section “${section.title}”${warn}?`)) {
                          void mutate(() => del<Version>(`/sections/${section.id}`)).catch(() => undefined);
                        }
                      }}
                    >
                      Delete
                    </button>
                  </td>
                ) : null}
              </tr>
              {section.items.map((item, index) => (
                <tr key={item.id} className="border-t border-line align-top hover:bg-panel/40">
                  <td className="px-2 py-1.5 text-muted">{item.sl_no}</td>
                  <td>
                    <EditableCell label="Item number" value={item.item_no} placeholder={item.sl_no} editable={editable} onSave={saveItem(item, "item_no")} />
                  </td>
                  <td>
                    <EditableCell label="Description" value={item.description} editable={editable} multiline onSave={saveItem(item, "description")} />
                  </td>
                  <td className="px-1 py-1">
                    {editable ? (
                      <Select
                        aria-label="Unit"
                        value={item.unit ?? ""}
                        onChange={(e) => void saveItem(item, "unit")(e.target.value).catch(() => undefined)}
                        className="w-24 px-1 py-1"
                      >
                        <option value="">—</option>
                        {itemUnits.map((u) => (
                          <option key={u.code} value={u.code}>
                            {u.display_name}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <div className="px-2 py-1.5">{item.unit_display ?? "—"}</div>
                    )}
                  </td>
                  <td>
                    {item.quantity_source === "measurements" ? (
                      <button
                        onClick={onShowLines}
                        title="Total of the measurement lines. Open the detailed estimate to change it."
                        className="num block w-full px-2 py-1.5 text-right hover:bg-accent-soft"
                      >
                        {item.quantity} <span className="text-xs text-accent">ƒ</span>
                      </button>
                    ) : (
                      <EditableCell label="Quantity" value={item.quantity} numeric editable={editable} onSave={saveItem(item, "quantity")} />
                    )}
                  </td>
                  <td>
                    <EditableCell
                      label="Rate"
                      value={item.rate}
                      numeric
                      editable={editable}
                      placeholder={item.quantity ? "add rate" : "—"}
                      display={item.rate ? inr(item.rate).slice(1) : undefined}
                      onSave={saveItem(item, "rate")}
                      className={!item.rate && item.quantity ? "text-warn" : ""}
                    />
                  </td>
                  <td className="num px-2 py-1.5 text-right">{item.amount ? inr(item.amount).slice(1) : "—"}</td>
                  <td>
                    <EditableCell label="Remarks" value={item.remarks} editable={editable} onSave={saveItem(item, "remarks")} />
                  </td>
                  {editable ? (
                    <td className="px-1 py-1">
                      <RowActions
                        canUp={index > 0}
                        canDown={index < section.items.length - 1}
                        onUp={() => move(section, index, -1)}
                        onDown={() => move(section, index, 1)}
                        onDuplicate={() => mutate(() => post<Version>(`/boq-items/${item.id}/duplicate`))}
                        onDelete={() => {
                          if (window.confirm(`Delete item ${item.item_no_display}?`)) {
                            void mutate(() => del<Version>(`/boq-items/${item.id}`)).catch(() => undefined);
                          }
                        }}
                      />
                    </td>
                  ) : null}
                </tr>
              ))}
              {editable ? (
                <tr className="border-t border-line">
                  <td />
                  <td colSpan={editable ? 8 : 7} className="px-1 py-1">
                    <AddItemRow sectionId={section.id} versionId={vid} mutate={mutate} unitOptions={itemUnits} />
                  </td>
                </tr>
              ) : null}
            </tbody>
          ))}
          <tfoot className="border-t-2 border-line bg-panel">
            <tr>
              <td colSpan={6} className="px-2 py-2 text-right font-semibold">
                Works subtotal
              </td>
              <td className="num px-2 py-2 text-right font-semibold">{inr(version.totals.works_subtotal)}</td>
              <td colSpan={editable ? 2 : 1} className="px-2 py-2 text-xs text-muted">
                {version.totals.item_count} items
                {version.totals.unpriced_count ? ` · ${version.totals.unpriced_count} without rate` : ""}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="text-xs text-muted">
        {version.totals.amount_in_words}. GST, contingencies and other charges are added in the abstract (M5).
      </p>

      {editable ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!newSection.trim()) return;
            await mutate(() => post<Version>(`/versions/${vid}/sections`, { title: newSection })).catch(() => undefined);
            setNewSection("");
          }}
        >
          <Input
            aria-label="New section title"
            placeholder="New section, e.g. Earthwork"
            value={newSection}
            onChange={(e) => setNewSection(e.target.value)}
            className="max-w-xs"
          />
          <Button type="submit" variant="secondary" disabled={!newSection.trim()}>
            Add section
          </Button>
        </form>
      ) : null}
    </div>
  );
}

function RowActions(props: {
  canUp: boolean;
  canDown: boolean;
  onUp: () => Promise<unknown>;
  onDown: () => Promise<unknown>;
  onDuplicate: () => Promise<unknown>;
  onDelete: () => void;
}) {
  const quiet = (fn: () => Promise<unknown>) => () => void fn().catch(() => undefined);
  const btn = "rounded px-1.5 py-1 text-xs text-muted hover:bg-panel hover:text-ink disabled:opacity-30";
  return (
    <div className="flex items-center justify-end gap-0.5">
      <button className={btn} disabled={!props.canUp} onClick={quiet(props.onUp)} aria-label="Move up" title="Move up">
        ↑
      </button>
      <button className={btn} disabled={!props.canDown} onClick={quiet(props.onDown)} aria-label="Move down" title="Move down">
        ↓
      </button>
      <button className={btn} onClick={quiet(props.onDuplicate)} aria-label="Duplicate" title="Duplicate">
        ⧉
      </button>
      <button className={`${btn} hover:text-bad`} onClick={props.onDelete} aria-label="Delete item" title="Delete">
        ✕
      </button>
    </div>
  );
}

function AddItemRow({
  sectionId,
  versionId,
  mutate,
  unitOptions,
}: {
  sectionId: string;
  versionId: string;
  mutate: WorkspaceProps["mutate"];
  unitOptions: WorkspaceProps["units"];
}) {
  const empty = { description: "", unit: "cum", quantity: "", rate: "" };
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!form.description.trim()) return;
        setBusy(true);
        try {
          await mutate(() =>
            post<Version>(`/versions/${versionId}/boq-items`, {
              section_id: sectionId,
              description: form.description,
              unit: form.unit || null,
              quantity: form.quantity || null,
              rate: form.rate || null,
            }),
          );
          setForm(empty);
        } catch {
          // shown by the workspace
        } finally {
          setBusy(false);
        }
      }}
    >
      <Input aria-label="New item description" placeholder="Add item: description" value={form.description} onChange={set("description")} className="min-w-64 flex-1 py-1" />
      <Select aria-label="New item unit" value={form.unit} onChange={set("unit")} className="w-24 px-1 py-1">
        {unitOptions.map((u) => (
          <option key={u.code} value={u.code}>
            {u.display_name}
          </option>
        ))}
      </Select>
      <Input aria-label="New item quantity" placeholder="Qty (or add lines later)" inputMode="decimal" value={form.quantity} onChange={set("quantity")} className="num w-44 py-1 text-right" />
      <Input aria-label="New item rate" placeholder="Rate ₹" inputMode="decimal" value={form.rate} onChange={set("rate")} className="num w-28 py-1 text-right" />
      <Button type="submit" variant="secondary" disabled={busy || !form.description.trim()} className="py-1">
        Add
      </Button>
    </form>
  );
}
