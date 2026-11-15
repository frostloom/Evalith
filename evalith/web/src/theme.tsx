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
  font: 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif',
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
    rail: "#edeef2",
    surface: "#ffffff",
    surface2: "#f6f7f9",
    input: "#ffffff",
    ink: "rgba(0, 0, 0, 0.88)",
    body: "rgba(0, 0, 0, 0.65)",
    muted: "rgba(0, 0, 0, 0.58)",
    border: "#d9d9d9",
    borderStrong: "#d9d9d9",
    accent: "#0958d9",
    accentText: "#003eb3",
    accentSoft: "#e6f4ff",
    button: "#1677ff",
    buttonHover: "#4096ff",
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
    bg: "#141821",
    directory: "#141414",
    rail: "#0c0e13",
    surface: "#191d26",
    surface2: "#262a33",
    input: "#1d222d",
    ink: "rgba(255, 255, 255, 0.85)",
    body: "rgba(255, 255, 255, 0.65)",
    muted: "rgba(255, 255, 255, 0.58)",
    border: "#2a3140",
    borderStrong: "#3a4356",
    accent: "#3c89e8",
    accentText: "#69b1ff",
    accentSoft: "#111a2c",
    button: "#1677ff",
    buttonHover: "#4096ff",
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
            colorBgLayout: c.rail,
            boxShadow:
              mode === "light"
                ? "0 1px 2px rgba(16,24,40,.05), 0 2px 6px -2px rgba(16,24,40,.08)"
                : "0 1px 2px rgba(0,0,0,.5), 0 2px 8px -2px rgba(0,0,0,.5)",
            boxShadowSecondary:
              mode === "light"
                ? "0 4px 8px -2px rgba(16,24,40,.08), 0 12px 28px -6px rgba(16,24,40,.14)"
                : "0 4px 10px rgba(0,0,0,.5), 0 12px 32px -4px rgba(0,0,0,.6)",
            boxShadowTertiary:
              mode === "light"
                ? "0 8px 16px -4px rgba(16,24,40,.10), 0 24px 64px -12px rgba(16,24,40,.20)"
                : "0 8px 20px rgba(0,0,0,.55), 0 24px 64px -8px rgba(0,0,0,.65)",
          },
          components: {
            Button: {
              primaryShadow:
                mode === "light"
                  ? "0 1px 2px rgba(9,88,217,.35), inset 0 1px 0 rgba(255,255,255,.18)"
                  : "0 1px 3px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.12)",
              defaultShadow:
                mode === "light"
                  ? "0 1px 2px rgba(16,24,40,.06)"
                  : "0 1px 2px rgba(0,0,0,.4)",
            },
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
