// WebAuthn browser helpers (ADR-0023). The backend speaks the standard WebAuthn JSON
// (base64url, no padding); the browser speaks ArrayBuffers. These convert between the two:
// `optionsToGet` turns the server's assertion options into what `navigator.credentials.get`
// wants, and `assertionToJson` serialises the resulting credential back to the shape
// py-webauthn verifies (mirrors test_auth_http.py::_login_passkey).

function b64urlToBytes(value: string): Uint8Array {
  const padded = value + "=".repeat((4 - (value.length % 4)) % 4);
  const binary = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function bytesToB64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export type ServerAssertionOptions = {
  challenge: string;
  rpId?: string;
  timeout?: number;
  userVerification?: UserVerificationRequirement;
  allowCredentials?: {
    id: string;
    type: "public-key";
    transports?: AuthenticatorTransport[];
  }[];
};

// Decode the base64url fields the browser needs as BufferSource.
export function optionsToGet(options: ServerAssertionOptions): PublicKeyCredentialRequestOptions {
  return {
    challenge: b64urlToBytes(options.challenge),
    rpId: options.rpId,
    timeout: options.timeout,
    userVerification: options.userVerification,
    allowCredentials: options.allowCredentials?.map((cred) => ({
      id: b64urlToBytes(cred.id),
      type: cred.type,
      transports: cred.transports,
    })),
  };
}

// Serialise the assertion to the base64url JSON the backend verifies.
export function assertionToJson(credential: PublicKeyCredential): Record<string, unknown> {
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: bytesToB64url(credential.rawId),
    response: {
      clientDataJSON: bytesToB64url(response.clientDataJSON),
      authenticatorData: bytesToB64url(response.authenticatorData),
      signature: bytesToB64url(response.signature),
      userHandle: response.userHandle ? bytesToB64url(response.userHandle) : null,
    },
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}

// --- Registration (create) side, mirrors test_auth_http.py::_register_passkey -------------
// The server's creation options (py-webauthn `options_to_json`): the same base64url-encoded
// binary fields (challenge, user.id, excludeCredentials[].id) the browser needs as BufferSource.
export type ServerCreationOptions = {
  challenge: string;
  rp: { id: string; name: string };
  user: { id: string; name: string; displayName: string };
  pubKeyCredParams: { type: "public-key"; alg: number }[];
  timeout?: number;
  excludeCredentials?: {
    id: string;
    type: "public-key";
    transports?: AuthenticatorTransport[];
  }[];
  authenticatorSelection?: AuthenticatorSelectionCriteria;
  attestation?: AttestationConveyancePreference;
};

// Decode the base64url fields and hand the rest to `navigator.credentials.create`.
export function optionsToCreate(
  options: ServerCreationOptions,
): PublicKeyCredentialCreationOptions {
  return {
    challenge: b64urlToBytes(options.challenge),
    rp: options.rp,
    user: {
      id: b64urlToBytes(options.user.id),
      name: options.user.name,
      displayName: options.user.displayName,
    },
    pubKeyCredParams: options.pubKeyCredParams,
    timeout: options.timeout,
    attestation: options.attestation,
    authenticatorSelection: options.authenticatorSelection,
    excludeCredentials: options.excludeCredentials?.map((cred) => ({
      id: b64urlToBytes(cred.id),
      type: cred.type,
      transports: cred.transports,
    })),
  };
}

// Serialise the new credential to the base64url JSON the backend verifies. The attestation
// response carries clientDataJSON + attestationObject (no authenticatorData/signature).
export function attestationToJson(credential: PublicKeyCredential): Record<string, unknown> {
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: bytesToB64url(credential.rawId),
    response: {
      clientDataJSON: bytesToB64url(response.clientDataJSON),
      attestationObject: bytesToB64url(response.attestationObject),
    },
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}

// True when the browser can do WebAuthn at all — gate the passkey UI on this.
export function passkeysSupported(): boolean {
  return typeof window !== "undefined" && typeof window.PublicKeyCredential !== "undefined";
}
