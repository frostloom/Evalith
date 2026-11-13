import { X as CloseRounded } from "lucide-react";
import { useId, type ReactNode } from "react";
import { Dialog, Drawer, IconButton, Typography } from "@mui/material";
import { ThemeToggle, ui } from "./theme";

/** Centered forms and contextual source drawers share the same controls. */
export function FormDrawer({
  title,
  onClose,
  children,
  footer,
  busy = false,
  presentation = "drawer",
  width,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  busy?: boolean;
  presentation?: "dialog" | "drawer";
  width?: number;
}) {
  const titleId = useId();
  const content = (
    <>
      <div className="drawer-heading">
        <Typography id={titleId} component="h2" variant="h5">
          {title}
        </Typography>
        <div className="drawer-heading-actions">
          <ThemeToggle />
          <IconButton onClick={onClose} disabled={busy} aria-label="关闭">
            <CloseRounded />
          </IconButton>
        </div>
      </div>
      <div className="drawer-content">{children}</div>
      {footer && <footer className="drawer-footer">{footer}</footer>}
    </>
  );
  if (presentation === "dialog") {
    return (
      <Dialog
        open
        fullWidth
        maxWidth={false}
        aria-labelledby={titleId}
        onClose={busy ? undefined : onClose}
        slotProps={{
          backdrop: { sx: { backgroundColor: "var(--overlay)" } },
          paper: {
            className: "form-dialog",
            sx: {
              width: 640,
              maxWidth: "calc(100% - 48px)",
              maxHeight: "calc(100dvh - 64px)",
              borderRadius: "14px",
              border: "1px solid var(--border-strong)",
              boxShadow: "0 20px 80px #00000024",
            },
          },
        }}
      >
        {content}
      </Dialog>
    );
  }
  return (
    <Drawer
      open
      anchor="right"
      onClose={busy ? undefined : onClose}
      slotProps={{
        backdrop: { sx: { backgroundColor: "var(--overlay)" } },
        paper: {
          role: "dialog",
          "aria-modal": true,
          "aria-label": title,
          sx: { width: { xs: "100%", sm: width ?? ui.drawer }, maxWidth: "100%" },
        },
      }}
    >
      {content}
    </Drawer>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  breadcrumb?: ReactNode;
}) {
  return (
    <header className="page-heading">
      {breadcrumb && <div className="page-breadcrumb">{breadcrumb}</div>}
      <div className="page-heading-row">
        <div>
          <Typography component="h1" variant="h4">
            {title}
          </Typography>
          {description && (
            <Typography
              component="p"
              variant="body2"
              color="text.secondary"
              className="page-description"
            >
              {description}
            </Typography>
          )}
        </div>
        <div className="page-actions">{actions}</div>
      </div>
    </header>
  );
}

export function EvalithMark() {
  return (
    <svg
      className="evalith-mark"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path d="M4 4h16v4H8v2h10v4H8v2h12v4H4V4Z" fill="currentColor" />
    </svg>
  );
}
