import { Trans } from "@lingui/react";
import { useRef } from "react";

import { i18n } from "../i18n";
import { useAttachments, useDeleteAttachment, useUploadAttachment } from "./queries";

function _formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Attachments of a guide (P7-S22): upload a file (bytes go to blob storage), list with a download
// link, delete. The download is a direct authenticated link (cookie auth + Content-Disposition).
export function AttachmentsPanel({ guideId }: { guideId: string }) {
  const attachments = useAttachments(guideId);
  const upload = useUploadAttachment();
  const remove = useDeleteAttachment();
  const fileRef = useRef<HTMLInputElement>(null);

  const onPick = (file: File | undefined) => {
    if (!file) return;
    upload.mutate(
      { guideId, file },
      { onSettled: () => fileRef.current && (fileRef.current.value = "") },
    );
  };

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-stein-text">
        <Trans id="guides.attachments" />
      </h3>
      <ul className="space-y-1">
        {attachments.data?.map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-2 text-sm">
            <a
              href={`/v1/guides/${guideId}/attachments/${a.id}`}
              className="truncate text-laurus dark:text-laurus-dark hover:underline"
              download={a.filename}
            >
              {a.filename}
            </a>
            <span className="flex shrink-0 items-center gap-2">
              <span className="text-xs text-stein-text">{_formatSize(a.byte_size)}</span>
              <button
                type="button"
                onClick={() => remove.mutate({ guideId, id: a.id })}
                className="text-xs text-bernstein hover:underline"
              >
                <Trans id="guides.attachmentRemove" />
              </button>
            </span>
          </li>
        ))}
        {(attachments.data?.length ?? 0) === 0 ? (
          <li className="text-sm text-stein-text">
            <Trans id="guides.attachmentsEmpty" />
          </li>
        ) : null}
      </ul>
      <input
        ref={fileRef}
        type="file"
        aria-label={i18n._("guides.attachmentAdd")}
        onChange={(e) => onPick(e.target.files?.[0])}
        disabled={upload.isPending}
        className="block w-full text-sm text-tinte file:mr-2 file:rounded file:border-0 file:bg-kalk file:px-2 file:py-1 file:text-sm file:text-tinte dark:text-kalk dark:file:bg-nacht-2 dark:file:text-kalk"
      />
      {upload.isError ? (
        <p className="text-xs text-bernstein" role="alert">
          <Trans id="guides.attachmentError" />
        </p>
      ) : null}
    </div>
  );
}
