/**
 * What the spend card says, and what it refuses to say (Phase 6.21d).
 *
 * The thing to get right here is not the arithmetic — that is tested in Python — it is
 * the wording. With no rate configured the card must not show a zero that reads as
 * "this cost nothing"; and when a month goes over its band the card must say plainly
 * that nothing was stopped, because a warning somebody reads as a block is a support
 * call and a delivery nobody submitted.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SpendCard } from "./spend-card";
import type { Spend } from "@/lib/types";

function spend(overrides: Partial<Spend> = {}): Spend {
  return {
    rate_per_million: 3,
    currency: "USD",
    tokens: 2_400_000,
    cost: 7.2,
    month_tokens: 9_000_000,
    month_cost: 27,
    monthly_warning: 0,
    cached_calls: 0,
    calls: 120,
    per_day: [],
    ...overrides,
  };
}

describe("with no rate set", () => {
  const none = spend({ rate_per_million: 0, cost: 0, month_cost: 0 });

  it("shows tokens and says why there is no money", () => {
    render(<SpendCard spend={none} />);

    expect(screen.getByText("no rate set")).toBeInTheDocument();
    expect(screen.getByText("2,400,000")).toBeInTheDocument();
    expect(screen.getByText(/Set a cost per million tokens/)).toBeInTheDocument();
  });

  it("shows no currency anywhere", () => {
    const { container } = render(<SpendCard spend={none} />);
    // A zero with a currency on it reads as "this cost nothing", which is a different
    // and wrong claim from "nobody has told us what it costs".
    expect(container.textContent).not.toMatch(/\$|USD/);
  });
});

describe("with a rate set", () => {
  it("shows the period, the month and the tokens", () => {
    render(<SpendCard spend={spend()} />);

    expect(screen.getByText("This period")).toBeInTheDocument();
    expect(screen.getByText("This month")).toBeInTheDocument();
    expect(
      screen.getByText(/per million tokens, which was typed in rather than measured/)
    ).toBeInTheDocument();
  });

  it("counts cached calls apart rather than folding them in", () => {
    render(<SpendCard spend={spend({ cached_calls: 80, calls: 120 })} />);
    expect(
      screen.getByText(/80 of 200 calls \(40%\) were served from the cache/)
    ).toBeInTheDocument();
  });

  it("says nothing about the cache when there was none", () => {
    render(<SpendCard spend={spend({ cached_calls: 0 })} />);
    expect(screen.queryByText(/served from the cache/)).not.toBeInTheDocument();
  });
});

describe("the monthly band", () => {
  it("says plainly that nothing has been stopped", () => {
    render(<SpendCard spend={spend({ month_cost: 600, monthly_warning: 500 })} />);

    expect(screen.getByText(/Nothing has been stopped/)).toBeInTheDocument();
    expect(screen.getByText(/only hard limit in the tool is the token budget/)).toBeInTheDocument();
  });

  it("stays quiet below the band", () => {
    render(<SpendCard spend={spend({ month_cost: 400, monthly_warning: 500 })} />);
    expect(screen.queryByText(/Nothing has been stopped/)).not.toBeInTheDocument();
  });

  it("stays quiet when no band is set", () => {
    render(<SpendCard spend={spend({ month_cost: 9_999, monthly_warning: 0 })} />);
    expect(screen.queryByText(/Nothing has been stopped/)).not.toBeInTheDocument();
  });
});

describe("the strip", () => {
  it("is drawn once there is more than one day", () => {
    render(
      <SpendCard
        spend={spend({
          per_day: [
            { day: "2026-09-01", tokens: 100, cost: 0.3 },
            { day: "2026-09-02", tokens: 200, cost: 0.6 },
          ],
        })}
      />
    );
    expect(screen.getByRole("img", { name: /Cost per day this month/ })).toBeInTheDocument();
  });

  it("is not drawn for a single day, where it would be one block", () => {
    render(
      <SpendCard spend={spend({ per_day: [{ day: "2026-09-01", tokens: 100, cost: 0.3 }] })} />
    );
    expect(screen.queryByRole("img", { name: /per day/ })).not.toBeInTheDocument();
  });
});
