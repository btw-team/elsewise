import { CheckCircle } from "@phosphor-icons/react/CheckCircle";
import { WarningCircle } from "@phosphor-icons/react/WarningCircle";
import { X } from "@phosphor-icons/react/X";
import { useEffect, useRef } from "react";

export function NotificationToast({
  variant,
  message,
  closeLabel,
  autoDismissMs,
  onClose,
}: {
  variant: "success" | "error";
  message: string;
  closeLabel: string;
  autoDismissMs?: number;
  onClose?: () => void;
}) {
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    if (onClose) onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const close = onCloseRef.current;
    if (!autoDismissMs || !close) return;
    const timeout = window.setTimeout(close, autoDismissMs);
    return () => window.clearTimeout(timeout);
  }, [autoDismissMs, message]);

  const Icon = variant === "success" ? CheckCircle : WarningCircle;
  return (
    <div
      className={`notification-toast ${variant}`}
      role={variant === "error" ? "alert" : "status"}
      aria-live={variant === "error" ? "assertive" : "polite"}
    >
      <Icon aria-hidden="true" weight="fill" />
      <span>{message}</span>
      {onClose && (
        <button
          type="button"
          aria-label={closeLabel}
          title={closeLabel}
          onClick={onClose}
        >
          <X aria-hidden="true" weight="regular" />
        </button>
      )}
    </div>
  );
}
