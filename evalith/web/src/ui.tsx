import type { ReactNode } from "react";
import { Drawer, IconButton, Typography } from "@mui/material";
import CloseRounded from "@mui/icons-material/CloseRounded";
import { ThemeToggle, ui } from "./theme";

/** Right-hand form drawer matching the upstream BaseDrawer interaction. */
export function FormDrawer({
  title,
  onClose,
  children,
  footer,
  busy = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  busy?: boolean;
}) {
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
          sx: { width: { xs: "100%", sm: ui.drawer }, maxWidth: "100%" },
        },
      }}
    >
      <div className="drawer-heading">
        <Typography component="h2" variant="h5">
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
