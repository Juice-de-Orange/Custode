import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import type { InstanceWithEtag } from "../tasks/queries";
import { i18n } from "../i18n";
import { TaskRow } from "../routes/tasks";

function makeInstance(overrides: Partial<InstanceWithEtag> = {}): InstanceWithEtag {
  return {
    id: "i1",
    template_id: null,
    title: "Bad putzen",
    points: 10,
    assigned_to: null,
    due_at: null,
    status: "open",
    done_at: null,
    done_by: null,
    awarded_points: null,
    room_id: null,
    version: 1,
    etag: "1",
    ...overrides,
  };
}

function renderRow(instance: InstanceWithEtag, onComplete = vi.fn()) {
  render(
    <I18nProvider i18n={i18n}>
      <ul>
        <TaskRow instance={instance} onComplete={onComplete} pending={false} />
      </ul>
    </I18nProvider>,
  );
  return onComplete;
}

test("shows the title and points", () => {
  renderRow(makeInstance());
  expect(screen.getByText("Bad putzen")).toBeTruthy();
  expect(screen.getByText(/10\s*Punkte/)).toBeTruthy();
});

test("completing calls back with the instance (carrying its ETag for If-Match)", () => {
  const instance = makeInstance({ etag: "7" });
  const onComplete = renderRow(instance);
  fireEvent.click(screen.getByText("Erledigt"));
  expect(onComplete).toHaveBeenCalledWith(instance);
  expect(onComplete.mock.calls[0][0].etag).toBe("7");
});

test("shows an assigned badge only when assigned", () => {
  const { rerender } = render(
    <I18nProvider i18n={i18n}>
      <ul>
        <TaskRow instance={makeInstance()} onComplete={vi.fn()} pending={false} />
      </ul>
    </I18nProvider>,
  );
  expect(screen.queryByText("zugewiesen")).toBeNull();
  rerender(
    <I18nProvider i18n={i18n}>
      <ul>
        <TaskRow
          instance={makeInstance({ assigned_to: "u9" })}
          onComplete={vi.fn()}
          pending={false}
        />
      </ul>
    </I18nProvider>,
  );
  expect(screen.getByText("zugewiesen")).toBeTruthy();
});
