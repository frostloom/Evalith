import {
  Moon as DarkModeOutlined,
  Sun as LightModeOutlined,
} from "lucide-react";
import {
  createContext,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { App as AntApp, Button, ConfigProvider, theme as antdTheme } from "antd";
import zhCN from "antd/locale/zh_CN";

export type ColorMode = "light" | "dark";
export const THEME_KEY = "evalith.theme";
export const ui = {
  font: '"Be Vietnam Pro", Inter, "PingFang SC", "Microsoft YaHei", sans-serif',
  drawer: 560,
};

/**
 * Ant Design carries the component system; this provider only supplies the
 * light/dark algorithm, the Chinese locale and Inter. The CSS variables below
 * mirror Ant Design's default palette so the legacy page CSS (which consumes
 * --surface/--ink/…) stays visually consistent with the components.
 */
const palettes = {
  light: {
    bg: "#ffffff",
    directory: "#ffffff",
    rail: "#f5f5f5",
    surface: "#ffffff",
    surface2: "#f5f5f5",
    input: "#ffffff",
    ink: "rgba(0, 0, 0, 0.88)",
    body: "rgba(0, 0, 0, 0.65)",
    muted: "rgba(0, 0, 0, 0.58)",
    border: "#d9d9d9",
    borderStrong: "#d9d9d9",
    accent: "#164b40",
    accentText: "#0f3a31",
    accentSoft: "#e8f0ee",
    button: "#164b40",
    buttonHover: "#1e5a4c",
    buttonText: "#ffffff",
    success: "#389e0d",
    warning: "#d48806",
    error: "#cf1322",
    warningBg: "#fffbe6",
    errorBg: "#fff2f0",
    successBg: "#f6ffed",
    overlay: "rgba(0, 0, 0, 0.45)",
  },
  dark: {
    bg: "#141414",
    directory: "#141414",
    rail: "#141414",
    surface: "#1f1f1f",
    surface2: "#2a2a2a",
    input: "#1f1f1f",
    ink: "rgba(255, 255, 255, 0.85)",
    body: "rgba(255, 255, 255, 0.65)",
    muted: "rgba(255, 255, 255, 0.58)",
    border: "#424242",
    borderStrong: "#424242",
    accent: "#5fa38f",
    accentText: "#8fc4b2",
    accentSoft: "#1d2b26",
    button: "#3e7a66",
    buttonHover: "#5fa38f",
    buttonText: "#ffffff",
    success: "#49aa19",
    warning: "#d89614",
    error: "#dc4446",
    warningBg: "#2b2111",
    errorBg: "#2a1215",
    successBg: "#162312",
    overlay: "rgba(0, 0, 0, 0.45)",
  },
};

function initialMode(): ColorMode {
  try {
    const saved = window.localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* Theme switching still works when browser storage is unavailable. */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

const ThemeContext = createContext({
  mode: "light" as ColorMode,
  toggle: () => {},
});
export function useColorMode() {
  return useContext(ThemeContext);
}

export function AppThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ColorMode>(initialMode);
  const c = palettes[mode];
  const toggle = () =>
    setMode((current) => {
      const next = current === "light" ? "dark" : "light";
      try {
        window.localStorage.setItem(THEME_KEY, next);
      } catch {
        /* Storage is optional. */
      }
      return next;
    });
  const variables = useMemo(
    () => ({
      "--canvas": c.bg,
        "--rail": c.rail,
      "--surface": c.surface,
      "--surface2": c.surface2,
      "--input": c.input,
      "--ink": c.ink,
      "--body": c.body,
      "--muted": c.muted,
      "--border": c.border,
      "--border-strong": c.borderStrong,
      "--primary": c.accent,
      "--primary-dark": c.accentText,
      "--primary-soft": c.accentSoft,
      "--button-bg": c.button,
      "--button-hover": c.buttonHover,
      "--button-text": c.buttonText,
      "--success": c.success,
      "--warning": c.warning,
      "--error": c.error,
      "--warning-bg": c.warningBg,
      "--error-bg": c.errorBg,
      "--success-bg": c.successBg,
      "--overlay": c.overlay,
    }),
    [c],
  );
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = mode;
    document.documentElement.style.colorScheme = mode;
    for (const [key, value] of Object.entries(variables)) {
      document.documentElement.style.setProperty(key, value);
    }
  }, [mode, variables]);
  return (
    <ThemeContext.Provider value={{ mode, toggle }}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm:
            mode === "dark"
              ? antdTheme.darkAlgorithm
              : antdTheme.defaultAlgorithm,
          token: {
            fontFamily: ui.font,
            borderRadius: 8,
            colorPrimary: c.accent,
          },
        }}
        button={{ autoInsertSpace: false }}
      >
        <AntApp>{children}</AntApp>
      </ConfigProvider>
    </ThemeContext.Provider>
  );
}

export function ThemeToggle() {
  const { mode, toggle } = useColorMode();
  const label = mode === "light" ? "切换到深色模式" : "切换到浅色模式";
  return (
    <Button
      type="text"
      size="small"
      onClick={toggle}
      aria-label={label}
      className="theme-toggle"
      icon={
        mode === "light" ? (
          <DarkModeOutlined size={16} />
        ) : (
          <LightModeOutlined size={16} />
        )
      }
    />
  );
}
