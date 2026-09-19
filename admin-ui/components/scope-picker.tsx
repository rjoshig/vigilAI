"use client";

/**
 * Where a check or a compliance rule applies: everywhere, one delivery programme, or
 * one customer (Phase 6.8a). The stored value is one token, `all`, `programme:<code>`
 * or the customer's name, so the pipeline decides scope in code with no lookup.
 */

import * as React from "react";

import { Input, Label, Select } from "@/components/ui/primitives";
import type { Scope } from "@/lib/types";

export const PROGRAMME_SCOPE_PREFIX = "programme:";

export type ScopeKind = "all" | "programme" | "customer";

export function scopeKind(scope: string): ScopeKind {
  if (scope === "all" || scope === "") return "all";
  if (scope.startsWith(PROGRAMME_SCOPE_PREFIX)) return "programme";
  return "customer";
}

/** How a stored scope reads on a list: the programme's name when it is one. */
export function scopeLabel(scope: string, programmes: Scope[] | null): string {
  const kind = scopeKind(scope);
  if (kind === "all") return "Everywhere";
  if (kind === "programme") {
    const code = scope.slice(PROGRAMME_SCOPE_PREFIX.length);
    const match = programmes?.find((p) => p.code === code);
    return match ? `Programme · ${match.label}` : `Programme · ${code}`;
  }
  return `Customer · ${scope}`;
}

interface ScopePickerProps {
  /** The stored scope value. */
  value: string;
  onChange: (scope: string) => void;
  programmes: Scope[] | null;
  idPrefix: string;
  disabled?: boolean;
}

export function ScopePicker({ value, onChange, programmes, idPrefix, disabled }: ScopePickerProps) {
  const kind = scopeKind(value);
  const firstProgramme = programmes?.[0]?.code ?? "";

  function changeKind(next: ScopeKind) {
    if (next === "all") onChange("all");
    else if (next === "programme") onChange(`${PROGRAMME_SCOPE_PREFIX}${firstProgramme}`);
    else onChange("");
  }

  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${idPrefix}-scope-kind`}>Applies to</Label>
        <Select
          id={`${idPrefix}-scope-kind`}
          value={kind}
          disabled={disabled}
          onChange={(event) => changeKind(event.target.value as ScopeKind)}
        >
          <option value="all">Everywhere</option>
          <option value="programme">One delivery programme</option>
          <option value="customer">One customer</option>
        </Select>
      </div>
      {kind === "programme" ? (
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${idPrefix}-scope-programme`}>Programme</Label>
          <Select
            id={`${idPrefix}-scope-programme`}
            value={value.slice(PROGRAMME_SCOPE_PREFIX.length)}
            disabled={disabled || !programmes?.length}
            onChange={(event) => onChange(`${PROGRAMME_SCOPE_PREFIX}${event.target.value}`)}
          >
            {(programmes ?? []).map((programme) => (
              <option key={programme.code} value={programme.code}>
                {programme.label} ({programme.code})
              </option>
            ))}
          </Select>
        </div>
      ) : null}
      {kind === "customer" ? (
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${idPrefix}-scope-customer`}>Customer name</Label>
          <Input
            id={`${idPrefix}-scope-customer`}
            value={value}
            disabled={disabled}
            placeholder="Exactly as entered on runs"
            onChange={(event) => onChange(event.target.value)}
          />
        </div>
      ) : null}
    </div>
  );
}
