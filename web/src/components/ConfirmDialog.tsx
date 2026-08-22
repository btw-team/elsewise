import { Warning } from "@phosphor-icons/react/Warning";
import { X } from "@phosphor-icons/react/X";
import { useId, useRef } from "react";
import { ModalPortal } from "./ModalPortal";
import { useModalFocus } from "./useModalFocus";

export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  cancelLabel,
  closeLabel,
  destructive = false,
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  closeLabel: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const messageId = useId();
  const cancelButton = useRef<HTMLButtonElement>(null);
  const dialog = useModalFocus(onCancel, busy, cancelButton);

  return (
    <ModalPortal>
      <div
        className="dialog-backdrop confirmation-backdrop"
        role="presentation"
        onMouseDown={(event) => {
          event.stopPropagation();
          if (event.target === event.currentTarget && !busy) onCancel();
        }}
      >
        <section
          ref={dialog}
          tabIndex={-1}
          className="dialog confirmation-dialog"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={messageId}
          aria-busy={busy}
          onMouseDown={(event) => event.stopPropagation()}
        >
          <header className="dialog-heading confirmation-heading">
            <div>
              <Warning
                aria-hidden="true"
                weight={destructive ? "fill" : "regular"}
              />
              <h2 id={titleId}>{title}</h2>
            </div>
            <button
              type="button"
              aria-label={closeLabel}
              title={closeLabel}
              disabled={busy}
              onClick={onCancel}
            >
              <X aria-hidden="true" weight="regular" />
            </button>
          </header>
          <p id={messageId}>{message}</p>
          <div className="dialog-actions confirmation-actions">
            <button
              ref={cancelButton}
              type="button"
              disabled={busy}
              onClick={onCancel}
            >
              {cancelLabel}
            </button>
            <button
              type="button"
              className={destructive ? "danger" : "primary"}
              disabled={busy}
              onClick={onConfirm}
            >
              {confirmLabel}
            </button>
          </div>
        </section>
      </div>
    </ModalPortal>
  );
}
