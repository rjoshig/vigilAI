"use client";

/**
 * Where a definition applies, said one way (Phase 6.12a).
 *
 * This is the console's half of `greenlight_ai/scopes.py`, and like it, it is the only
 * place in the admin app that interprets a scope string. The canonical token is
 * `everywhere`, `programme:<code>`, `customer:<name>` or `config:<id>`; the older
 * forms — a bare `all` and a bare customer name — still read correctly, because rows
 * written before the vocabulary was unified are not rewritten (ADR-037).
 *
 * A configuration scope is not something anybody picks: it comes from a note written
 * against one configuration and applies to that one and no other (ADR-024). The picker
 * shows it rather than silently turning it into a customer name.
 */

import * as React from "react";

import { Input, Label, Select } from "@/components/ui/primitives";
import type { Scope } from "@/lib/types";

export const EVERYWHERE = "everywhere";
export const PROGRAMME_SCOPE_PREFIX = "programme:";
export const CUSTOMER_SCOPE_PREFIX = "customer:";
export const CONFIG_SCOPE_PREFIX = "config:";

export type ScopeKind = "all" | "programme" | "customer" | "configuration";

export interface ParsedScope {
  kind: ScopeKind;
  /** The programme code, the customer name, or the configuration id. */
  value: string;
}

/** Read any stored or submitted form. */
export function parseScope(raw: string | null | undefined): ParsedScope {
  const text = (raw ?? "").trim();
  const lowered = text.toLowerCase();
  if (lowered === "" || lowered === "all" || lowered === EVERYWHERE) {
    return { kind: "all", value: "" };
  }
  if (lowered.startsWith(PROGRAMME_SCOPE_PREFIX)) {
    return { kind: "programme", value: text.slice(PROGRAMME_SCOPE_PREFIX.length).trim() };
  }
  if (lowered.startsWith(CONFIG_SCOPE_PREFIX)) {
    return { kind: "configuration", value: text.slice(CONFIG_SCOPE_PREFIX.length).trim() };
  }
  if (lowered.startsWith(CUSTOMER_SCOPE_PREFIX)) {
    return { kind: "customer", value: text.slice(CUSTOMER_SCOPE_PREFIX.length).trim() };
  }
  return { kind: "customer", value: text };
}

/** The canonical token for a parsed scope, which is what the API stores. */
export function scopeToken(parsed: ParsedScope): string {
  if (parsed.kind === "all") return EVERYWHERE;
  if (parsed.kind === "programme") return `${PROGRAMME_SCOPE_PREFIX}${parsed.value}`;
  if (parsed.kind === "configuration") return `${CONFIG_SCOPE_PREFIX}${parsed.value}`;
  return `${CUSTOMER_SCOPE_PREFIX}${parsed.value}`;
}

export function scopeKind(scope: string): ScopeKind {
  return parseScope(scope).kind;
}

/** How a stored scope reads on a list: the programme's name when it is one. */
export function scopeLabel(scope: string, programmes: Scope[] | null): string {
  const parsed = parseScope(scope);
  if (parsed.kind === "all") return "Everywhere";
  if (parsed.kind === "programme") {
    const match = programmes?.find((p) => p.code === parsed.value);
    return `Programme · ${match ? match.label : parsed.value}`;
  }
  if (parsed.kind === "configuration") return `Configuration · ${parsed.value}`;
  return `Customer · ${parsed.value}`;
}

/**
 * Whether a scope names something. A scope that names nothing covers nothing, so the
 * form refuses it rather than storing a rule that never runs.
 */
export function scopeIsComplete(scope: string): boolean {
  const parsed = parseScope(scope);
  return parsed.kind === "all" || parsed.value.trim() !== "";
}

interface ScopePickerProps {
  /** The stored scope value, in any form. */
  value: string;
  /** Called with the canonical token. */
  onChange: (scope: string) => void;
  programmes: Scope[] | null;
  idPrefix: string;
  disabled?: boolean;
}

export function ScopePicker({ value, onChange, programmes, idPrefix, disabled }: ScopePickerProps) {
  const parsed = parseScope(value);
  const firstProgramme = programmes?.[0]?.code ?? "";

  function changeKind(next: ScopeKind) {
    if (next === "programme") onChange(scopeToken({ kind: "programme", value: firstProgramme }));
    else if (next === "customer") onChange(scopeToken({ kind: "customer", value: "" }));
    else onChange(EVERYWHERE);
  }

  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${idPrefix}-scope-kind`}>Applies to</Label>
        <Select
          id={`${idPrefix}-scope-kind`}
          value={parsed.kind}
          disabled={disabled || parsed.kind === "configuration"}
          onChange={(event) => changeKind(event.target.value as ScopeKind)}
        >
          <option value="all">Everywhere</option>
          <option value="programme">One delivery programme</option>
          <option value="customer">One customer</option>
          {parsed.kind === "configuration" ? (
            <option value="configuration">One configuration</option>
          ) : null}
        </Select>
      </div>
      {parsed.kind === "programme" ? (
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${idPrefix}-scope-programme`}>Programme</Label>
          <Select
            id={`${idPrefix}-scope-programme`}
            value={parsed.value}
            disabled={disabled || !programmes?.length}
            onChange={(event) =>
              onChange(scopeToken({ kind: "programme", value: event.target.value }))
            }
          >
            {(programmes ?? []).map((programme) => (
              <option key={programme.code} value={programme.code}>
                {programme.label} ({programme.code})
              </option>
            ))}
          </Select>
        </div>
      ) : null}
      {parsed.kind === "customer" ? (
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${idPrefix}-scope-customer`}>Customer name</Label>
          <Input
            id={`${idPrefix}-scope-customer`}
            value={parsed.value}
            disabled={disabled}
            placeholder="Exactly as entered on runs"
            onChange={(event) =>
              onChange(scopeToken({ kind: "customer", value: event.target.value }))
            }
          />
        </div>
      ) : null}
      {parsed.kind === "configuration" ? (
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${idPrefix}-scope-configuration`}>Configuration</Label>
          <Input id={`${idPrefix}-scope-configuration`} value={parsed.value} disabled readOnly />
        </div>
      ) : null}
    </div>
  );
}
