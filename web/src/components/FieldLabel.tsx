import { LockSimple } from "@phosphor-icons/react/LockSimple";
import type { ReactNode } from "react";

export function FieldLabel({
  children,
  lockReason,
}: {
  children: ReactNode;
  lockReason?: string | null;
}) {
  return (
    <span className="field-label-content">
      <span>{children}</span>
      {lockReason && (
        <span
          className="field-lock-indicator"
          aria-hidden="true"
          data-lock-reason={lockReason}
          title={lockReason}
        >
          <LockSimple weight="bold" />
        </span>
      )}
    </span>
  );
}
