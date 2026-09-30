import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { Field } from "../components/field";

test("Field associates its label with the input", () => {
  render(<Field id="x" label="Mein Label" />);
  expect(screen.getByLabelText("Mein Label")).toBeInTheDocument();
});
