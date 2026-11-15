import { X as CloseRounded } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { Button, Drawer, Input, Modal, Select } from "antd";
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
  const triggerRef = useRef<Element | null>(null);
  useEffect(() => {
    triggerRef.current = document.activeElement;
    return () => {
      const trigger = triggerRef.current;
      if (trigger instanceof HTMLElement) trigger.focus();
    };
  }, []);
  useEffect(() => {
    // Modal surfaces render through body portals; hide the app shell from
    // assistive tech (and role queries) exactly while one is open, matching
    // the previous dialog behavior.
    const shell = document.querySelector(".app-shell");
    if (!shell) return;
    shell.setAttribute("aria-hidden", "true");
    return () => shell.setAttribute("aria-hidden", "false");
  }, []);
  const guardedClose = () => {
    if (!busy) onClose();
  };
  const content = (
    <>
      <div className="drawer-heading">
        <h2 id={titleId}>{title}</h2>
        <div className="drawer-heading-actions">
          <ThemeToggle />
          <Button
            type="text"
            size="small"
            onClick={guardedClose}
            disabled={busy}
            aria-label="关闭"
            icon={<CloseRounded size={16} />}
          />
        </div>
      </div>
      <div className="drawer-content">{children}</div>
      {footer && <footer className="drawer-footer">{footer}</footer>}
    </>
  );
  // The custom heading is not passed to antd as a title prop, so the dialog
  // surfaces carry their accessible name explicitly.
  if (presentation === "dialog") {
    return (
      <Modal
        open
        title={null}
        footer={null}
        closable={false}
        width={640}
        destroyOnHidden
        transitionName=""
        maskTransitionName=""
        styles={{ body: { padding: 0 } }}
        onCancel={guardedClose}
        mask={{ closable: !busy }}
        keyboard={!busy}
      >
        <div className="form-dialog" role="dialog" aria-labelledby={titleId}>
          {content}
        </div>
      </Modal>
    );
  }
  return (
    <Drawer
      open
      placement="right"
      closable={false}
      width={width ?? ui.drawer}
      destroyOnHidden
      motion={{ motionAppear: false, motionEnter: false, motionLeave: false }}
      styles={{ content: { padding: 0 } }}      onClose={guardedClose}
      maskClosable={!busy}
      keyboard={!busy}
      className="form-drawer"
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
          <h1>{title}</h1>
          {description && <p className="page-description">{description}</p>}
        </div>
        <div className="page-actions">{actions}</div>
      </div>
    </header>
  );
}

/** Ant-Design-backed labeled controls. The wrapping <label> keeps every
 * input addressable by its visible label (tests and screen readers). */
export function TextInput({
  label,
  value,
  onChange,
  placeholder,
  prefix,
  ariaLabel,
  disabled,
  type,
  min,
  max,
  step,
  className,
  onEnter,
}: {
  label?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  prefix?: ReactNode;
  ariaLabel?: string;
  disabled?: boolean;
  type?: "text" | "number";
  min?: number;
  max?: number;
  step?: number;
  className?: string;
  onEnter?: () => void;
}) {
  const id = useId();
  const control = type === "number" ? (
    <Input
      id={id}
      aria-label={ariaLabel ?? label}
      type="number"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      placeholder={placeholder}
      className={className}
      onPressEnter={onEnter}
    />
  ) : (
    <Input
      id={id}
      aria-label={ariaLabel ?? label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      prefix={prefix}
      disabled={disabled}
      className={className}
      onPressEnter={onEnter}
    />
  );
  if (!label) return control;
  return (
    <label className="afield" htmlFor={id}>
      <span>{label}</span>
      {control}
    </label>
  );
}

export function TextArea({
  label,
  value,
  onChange,
  placeholder,
  rows = 3,
  ariaLabel,
  disabled,
  className,
}: {
  label?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
  className?: string;
  ariaLabel?: string;
}) {
  const id = useId();
  const control = (
    <Input.TextArea
      id={id}
      aria-label={ariaLabel ?? label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      rows={rows}
      disabled={disabled}
      className={className}
    />
  );
  if (!label) return control;
  return (
    <label className="afield" htmlFor={id}>
      <span>{label}</span>
      {control}
    </label>
  );
}

export type SelectOption = { value: string; label: string };

export function SelectInput({
  label,
  value,
  onChange,
  options,
  placeholder,
  ariaLabel,
  disabled,
  className,
}: {
  label?: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  ariaLabel?: string;
}) {
  const id = useId();
  const control = (
    <Select
      id={id}
      aria-label={ariaLabel ?? label}
      value={value === "" ? undefined : value}
      onChange={(next) => onChange(next ?? "")}
      options={options}
      placeholder={placeholder}
      disabled={disabled}
      className={className}
      style={{ width: "100%" }}
    />
  );
  if (!label) return control;
  return (
    <label className="afield" htmlFor={id}>
      <span>{label}</span>
      {control}
    </label>
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
