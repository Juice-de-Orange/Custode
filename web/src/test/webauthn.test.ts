import { expect, test } from "vitest";

import {
  assertionToJson,
  attestationToJson,
  optionsToCreate,
  optionsToGet,
  passkeysSupported,
} from "../auth/webauthn";

function buf(...bytes: number[]): ArrayBuffer {
  return new Uint8Array(bytes).buffer;
}

test("optionsToGet decodes the base64url challenge to bytes and passes options through", () => {
  const out = optionsToGet({
    challenge: "AQID", // bytes 1,2,3
    rpId: "custode.example",
    userVerification: "preferred",
    allowCredentials: [{ id: "AQID", type: "public-key" }],
  });
  expect(Array.from(out.challenge as Uint8Array)).toEqual([1, 2, 3]);
  expect(out.rpId).toBe("custode.example");
  expect(out.userVerification).toBe("preferred");
  expect(out.allowCredentials?.map((c) => Array.from(c.id as Uint8Array))).toEqual([[1, 2, 3]]);
});

test("assertionToJson serialises the credential to base64url without padding", () => {
  const credential = {
    id: "cred-id",
    rawId: buf(1, 2, 3),
    type: "public-key",
    response: {
      clientDataJSON: buf(4, 5),
      authenticatorData: buf(6, 7),
      signature: buf(8, 9),
      userHandle: buf(10),
    },
    getClientExtensionResults: () => ({}),
  } as unknown as PublicKeyCredential;

  const json = assertionToJson(credential);
  expect(json.id).toBe("cred-id");
  expect(json.rawId).toBe("AQID");
  expect(json.type).toBe("public-key");
  expect(json.clientExtensionResults).toEqual({});
  const response = json.response as Record<string, unknown>;
  expect(response.clientDataJSON).toBe("BAU"); // base64 "BAU=" without padding
  expect(response.userHandle).toBe("Cg"); // base64 "Cg==" without padding
});

test("assertionToJson keeps a null userHandle null", () => {
  const credential = {
    id: "x",
    rawId: buf(1),
    type: "public-key",
    response: {
      clientDataJSON: buf(1),
      authenticatorData: buf(1),
      signature: buf(1),
      userHandle: null,
    },
    getClientExtensionResults: () => ({}),
  } as unknown as PublicKeyCredential;
  const response = assertionToJson(credential).response as Record<string, unknown>;
  expect(response.userHandle).toBeNull();
});

test("optionsToCreate decodes challenge, user.id and excludeCredentials ids to bytes", () => {
  const out = optionsToCreate({
    challenge: "AQID", // bytes 1,2,3
    rp: { id: "custode.example", name: "Custode" },
    user: { id: "AQID", name: "a@b.de", displayName: "A B" },
    pubKeyCredParams: [{ type: "public-key", alg: -7 }],
    excludeCredentials: [{ id: "AQID", type: "public-key" }],
  });
  expect(Array.from(out.challenge as Uint8Array)).toEqual([1, 2, 3]);
  expect(Array.from(out.user.id as Uint8Array)).toEqual([1, 2, 3]);
  expect(out.rp).toEqual({ id: "custode.example", name: "Custode" });
  expect(out.pubKeyCredParams).toEqual([{ type: "public-key", alg: -7 }]);
  expect(out.excludeCredentials?.map((c) => Array.from(c.id as Uint8Array))).toEqual([[1, 2, 3]]);
});

test("attestationToJson serialises the attestation to base64url without padding", () => {
  const credential = {
    id: "cred-id",
    rawId: buf(1, 2, 3),
    type: "public-key",
    response: {
      clientDataJSON: buf(4, 5),
      attestationObject: buf(6, 7),
    },
    getClientExtensionResults: () => ({}),
  } as unknown as PublicKeyCredential;

  const json = attestationToJson(credential);
  expect(json.id).toBe("cred-id");
  expect(json.rawId).toBe("AQID");
  expect(json.type).toBe("public-key");
  expect(json.clientExtensionResults).toEqual({});
  const response = json.response as Record<string, unknown>;
  expect(response.clientDataJSON).toBe("BAU"); // [4,5] → base64 "BAU=" without padding
  expect(response.attestationObject).toBe("Bgc"); // [6,7] → base64 "Bgc=" without padding
});

test("passkeysSupported is false without window.PublicKeyCredential (jsdom)", () => {
  expect(passkeysSupported()).toBe(false);
});
