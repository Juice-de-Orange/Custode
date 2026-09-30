// Client-side vault crypto (KONZEPT §5, ADR-0067). libsodium-wasm is loaded lazily (dynamic import)
// so it only enters the bundle on the vault route. Every value that crosses the wire is base64; the
// server stores it opaquely and never decrypts. Argon2id (crypto_pwhash) derives a wrapping key from
// a passphrase/recovery-code; secretbox (XSalsa20-Poly1305) wraps the household key and encrypts items.

type Sodium = typeof import("libsodium-wrappers-sumo");

let sodiumPromise: Promise<Sodium> | null = null;

async function getSodium(): Promise<Sodium> {
  if (sodiumPromise === null) {
    sodiumPromise = import("libsodium-wrappers-sumo").then(async (ns) => {
      // libsodium attaches its functions to the default export, and only once `ready` resolves.
      const sodium = (ns as unknown as { default?: Sodium }).default ?? ns;
      await sodium.ready;
      return sodium;
    });
  }
  return sodiumPromise;
}

// KDF cost. INTERACTIVE keeps unlock snappy in the browser while staying memory-hard. The chosen
// ops/mem are recorded in wrap_meta so a future raise stays backwards-compatible.
export type KdfParams = { alg: "argon2id"; ops: number; mem: number; salt: string };

export type WrapMeta = KdfParams & { nonce: string };

// An item's opaque metadata: the body nonce plus the separately-encrypted name (so the list view can
// show titles from item_meta without fetching the secret body ciphertext).
export type ItemMeta = { body_nonce: string; name_ct: string; name_nonce: string };

async function deriveWrapKey(
  secret: string,
  params: KdfParams,
  sodium: Sodium,
): Promise<Uint8Array> {
  return sodium.crypto_pwhash(
    sodium.crypto_secretbox_KEYBYTES,
    secret,
    sodium.from_base64(params.salt),
    params.ops,
    params.mem,
    sodium.crypto_pwhash_ALG_ARGON2ID13,
  );
}

function freshKdfParams(sodium: Sodium): KdfParams {
  return {
    alg: "argon2id",
    ops: sodium.crypto_pwhash_OPSLIMIT_INTERACTIVE,
    mem: sodium.crypto_pwhash_MEMLIMIT_INTERACTIVE,
    salt: sodium.to_base64(sodium.randombytes_buf(sodium.crypto_pwhash_SALTBYTES)),
  };
}

// A new random household vault key (raw bytes, never leaves memory un-wrapped).
export async function generateHouseholdKey(): Promise<Uint8Array> {
  const sodium = await getSodium();
  return sodium.randombytes_buf(sodium.crypto_secretbox_KEYBYTES);
}

// A high-entropy recovery code (base32-ish, grouped) — shown to the user once, never stored as plaintext.
export async function generateRecoveryCode(): Promise<string> {
  const sodium = await getSodium();
  const raw = sodium.to_base64(sodium.randombytes_buf(20)).replace(/[+/=]/g, "");
  return (raw.match(/.{1,5}/g) ?? [raw]).join("-").toUpperCase();
}

// Wrap the household key under a passphrase/recovery secret. Returns the base64 wrapped_key plus the
// wrap_meta (KDF params + nonce) — exactly what `PUT /v1/vault/keys` stores.
export async function wrapHouseholdKey(
  householdKey: Uint8Array,
  secret: string,
): Promise<{ wrapped_key: string; wrap_meta: WrapMeta }> {
  const sodium = await getSodium();
  const params = freshKdfParams(sodium);
  const wrapKey = await deriveWrapKey(secret, params, sodium);
  const nonce = sodium.randombytes_buf(sodium.crypto_secretbox_NONCEBYTES);
  const wrapped = sodium.crypto_secretbox_easy(householdKey, nonce, wrapKey);
  return {
    wrapped_key: sodium.to_base64(wrapped),
    wrap_meta: { ...params, nonce: sodium.to_base64(nonce) },
  };
}

// Recover the household key from a stored envelope + the secret. Throws if the secret is wrong.
export async function unwrapHouseholdKey(
  wrappedKey: string,
  wrapMeta: WrapMeta,
  secret: string,
): Promise<Uint8Array> {
  const sodium = await getSodium();
  const wrapKey = await deriveWrapKey(secret, wrapMeta, sodium);
  const opened = sodium.crypto_secretbox_open_easy(
    sodium.from_base64(wrappedKey),
    sodium.from_base64(wrapMeta.nonce),
    wrapKey,
  );
  return opened;
}

async function encryptString(
  plaintext: string,
  householdKey: Uint8Array,
  sodium: Sodium,
): Promise<{ ct: string; nonce: string }> {
  const nonce = sodium.randombytes_buf(sodium.crypto_secretbox_NONCEBYTES);
  // libsodium accepts a string message directly and UTF-8 encodes it.
  const ct = sodium.crypto_secretbox_easy(plaintext, nonce, householdKey);
  return { ct: sodium.to_base64(ct), nonce: sodium.to_base64(nonce) };
}

function decryptString(
  ctB64: string,
  nonceB64: string,
  householdKey: Uint8Array,
  sodium: Sodium,
): string {
  const opened = sodium.crypto_secretbox_open_easy(
    sodium.from_base64(ctB64),
    sodium.from_base64(nonceB64),
    householdKey,
  );
  return sodium.to_string(opened);
}

// Encrypt an item (name + secret body) under the household key. The name is encrypted separately so a
// list view can show titles from item_meta alone (the body ciphertext is the `ciphertext` column).
export async function encryptItem(
  name: string,
  body: string,
  householdKey: Uint8Array,
): Promise<{ ciphertext: string; item_meta: ItemMeta }> {
  const sodium = await getSodium();
  const nameEnc = await encryptString(name, householdKey, sodium);
  const bodyEnc = await encryptString(body, householdKey, sodium);
  return {
    ciphertext: bodyEnc.ct,
    item_meta: { body_nonce: bodyEnc.nonce, name_ct: nameEnc.ct, name_nonce: nameEnc.nonce },
  };
}

// Decrypt just the name (for the list view) from an item's opaque meta.
export async function decryptItemName(meta: ItemMeta, householdKey: Uint8Array): Promise<string> {
  const sodium = await getSodium();
  return decryptString(meta.name_ct, meta.name_nonce, householdKey, sodium);
}

// Decrypt the secret body (for the detail view) from the ciphertext + meta.
export async function decryptItemBody(
  ciphertext: string,
  meta: ItemMeta,
  householdKey: Uint8Array,
): Promise<string> {
  const sodium = await getSodium();
  return decryptString(ciphertext, meta.body_nonce, householdKey, sodium);
}
