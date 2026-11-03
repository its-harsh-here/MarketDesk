import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ChangeText } from "@/components/ui/Change";
import { Segmented } from "@/components/ui/Segmented";
import { DataTable, type SortState } from "@/components/ui/DataTable";
import { isTypingTarget } from "@/lib/hooks";

describe("ChangeText", () => {
  it("conveys direction with sign, arrow and words, not colour alone", () => {
    render(<ChangeText value="-0.65" percent="-0.38" />);
    const el = screen.getByText("down", { exact: false }).parentElement!;
    expect(el.textContent).toContain("−₹0.65");
    expect(el.textContent).toContain("(−0.38%)");
    expect(el.querySelector("svg")).not.toBeNull();
  });
  it("shows an em dash when nothing is known", () => {
    render(<ChangeText value={null} percent={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("Segmented", () => {
  it("is a radio group operable with arrow keys", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [v, setV] = useState<"1M" | "3M" | "6M">("3M");
      return <Segmented label="Range" value={v} onChange={setV} options={[{ value: "1M", label: "1M" }, { value: "3M", label: "3M" }, { value: "6M", label: "6M" }]} />;
    }
    render(<Harness />);
    const group = screen.getByRole("radiogroup", { name: "Range" });
    expect(screen.getByRole("radio", { name: "3M" })).toHaveAttribute("aria-checked", "true");
    screen.getByRole("radio", { name: "3M" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "6M" })).toHaveAttribute("aria-checked", "true");
    expect(group).toBeInTheDocument();
  });
});

describe("DataTable", () => {
  it("exposes sort state through aria-sort and right-aligns numeric columns", async () => {
    const user = userEvent.setup();
    const onSort = vi.fn();
    function Harness() {
      const [sort, setSort] = useState<SortState | null>(null);
      return (
        <DataTable
          caption="Prices"
          rows={[{ s: "A", p: "1" }]}
          rowKey={(r) => r.s}
          sort={sort}
          onSortChange={(x) => {
            onSort(x);
            setSort(x);
          }}
          columns={[
            { key: "s", header: "Symbol", render: (r) => r.s },
            { key: "p", header: "Price", align: "right", sortable: true, render: (r) => r.p },
          ]}
        />
      );
    }
    render(<Harness />);
    const th = screen.getByRole("columnheader", { name: /Price/ });
    expect(th).toHaveAttribute("aria-sort", "none");
    expect(th.className).toContain("text-right");
    await user.click(screen.getByRole("button", { name: /Price/ }));
    expect(onSort).toHaveBeenCalledWith({ key: "p", dir: "desc" });
    expect(screen.getByRole("columnheader", { name: /Price/ })).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("table", { name: "Prices" })).toBeInTheDocument();
  });
});

describe("keyboard shortcut guard", () => {
  it("does not capture shortcuts while typing", () => {
    const input = document.createElement("input");
    const div = document.createElement("div");
    expect(isTypingTarget(input)).toBe(true);
    expect(isTypingTarget(document.createElement("textarea"))).toBe(true);
    expect(isTypingTarget(div)).toBe(false);
  });
});
