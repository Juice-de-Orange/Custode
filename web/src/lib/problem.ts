// Shared RFC-9457 problem handling. Clients branch on the stable ``slug`` (the last path or
// fragment segment of ``type``), never on message strings (ARCHITECTURE §12, errors.md). Lives in
// ``lib`` so both the member app (auth/session) and the ops bundle reuse one implementation.

export class ProblemError extends Error {
  constructor(
    readonly slug: string,
    readonly reference?: string,
    message?: string,
    // Additional problem members (the backend merges ``extra`` FLAT into the body, e.g.
    // ``category`` on caldav_write_failed, ``field`` on external_field_readonly).
    readonly extra: Record<string, unknown> = {},
  ) {
    super(message ?? slug);
    this.name = "ProblemError";
  }
}

type ProblemBody = {
  type?: string;
  reference?: string;
  title?: string;
  status?: number;
  detail?: string;
};

export function toProblem(error: unknown, status?: number): ProblemError {
  const body = (error ?? {}) as ProblemBody & Record<string, unknown>;
  const slug = body.type ? (body.type.split(/[/#]/).pop() ?? "error") : `http_${status ?? 0}`;
  const extra: Record<string, unknown> = { ...body };
  for (const known of ["type", "reference", "title", "status", "detail"]) {
    delete extra[known];
  }
  return new ProblemError(slug, body.reference, body.title, extra);
}
