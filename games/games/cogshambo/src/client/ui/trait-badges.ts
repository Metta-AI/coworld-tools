import type { TraitKind } from "./cog-traits";
import { escapeHtml } from "./html";

export function renderReadOnlyTraitBadge(kind: TraitKind, value: string): string {
  return `
    <span
      class="trait-badge trait-badge-readonly"
      data-trait-kind="${escapeHtml(kind)}"
      data-trait-value="${escapeHtml(value)}"
    >${escapeHtml(value)}</span>
  `;
}

export function renderTraitBadgeGroup(
  label: string,
  kind: TraitKind,
  values: readonly string[],
  selected: string,
  action = "set-trait",
): string {
  return `
    <fieldset class="trait-badge-group">
      <legend>${escapeHtml(label)}</legend>
      <div class="trait-badge-list">
        ${values
          .map((value) => {
            const selectedClass = value === selected ? " is-selected" : "";
            return `
              <button
                aria-pressed="${value === selected}"
                class="trait-badge${selectedClass}"
                data-action="${escapeHtml(action)}"
                data-trait-kind="${escapeHtml(kind)}"
                data-trait-value="${escapeHtml(value)}"
                type="button"
              >${escapeHtml(value)}</button>
            `;
          })
          .join("")}
      </div>
    </fieldset>
  `;
}
