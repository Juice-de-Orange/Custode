import { describe, expect, test } from "vitest";

import {
  decryptItemBody,
  decryptItemName,
  encryptItem,
  generateHouseholdKey,
  generateRecoveryCode,
  unwrapHouseholdKey,
  wrapHouseholdKey,
} from "../vault/crypto";

describe("vault crypto (ADR-0067)", () => {
  test("wrap then unwrap with the same passphrase recovers the household key", async () => {
    const key = await generateHouseholdKey();
    const { wrapped_key, wrap_meta } = await wrapHouseholdKey(key, "richtige-passphrase");
    const recovered = await unwrapHouseholdKey(wrapped_key, wrap_meta, "richtige-passphrase");
    expect([...recovered]).toEqual([...key]);
  });

  test("unwrapping with the wrong passphrase fails", async () => {
    const key = await generateHouseholdKey();
    const { wrapped_key, wrap_meta } = await wrapHouseholdKey(key, "richtig");
    await expect(unwrapHouseholdKey(wrapped_key, wrap_meta, "falsch")).rejects.toBeDefined();
  });

  test("a recovery code is a second, independent envelope for the same key", async () => {
    const key = await generateHouseholdKey();
    const code = await generateRecoveryCode();
    expect(code.length).toBeGreaterThan(10);
    const { wrapped_key, wrap_meta } = await wrapHouseholdKey(key, code);
    const recovered = await unwrapHouseholdKey(wrapped_key, wrap_meta, code);
    expect([...recovered]).toEqual([...key]);
  });

  test("item name + body round-trip under the household key", async () => {
    const key = await generateHouseholdKey();
    const { ciphertext, item_meta } = await encryptItem("Online-Banking", "geheim123", key);
    expect(ciphertext).not.toContain("geheim123"); // stored opaquely
    expect(await decryptItemName(item_meta, key)).toBe("Online-Banking");
    expect(await decryptItemBody(ciphertext, item_meta, key)).toBe("geheim123");
  });

  test("a different key cannot decrypt another household's item", async () => {
    const key = await generateHouseholdKey();
    const other = await generateHouseholdKey();
    const { ciphertext, item_meta } = await encryptItem("X", "Y", key);
    await expect(decryptItemBody(ciphertext, item_meta, other)).rejects.toBeDefined();
  });
});
