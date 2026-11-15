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
  // Rhesis product tokens (apps/frontend/src/styles/theme.ts + theme-constants.ts).
  light: {
    bg: "#ffffff",
    directory: "#ffffff",
    rail: "#f7f8f9",
    surface: "#ffffff",
    surface2: "#eef0f3",
    input: "#f9f9fa",
    ink: "#1a1c20",
    body: "#2a2e36",
    muted: "#545a65",
    border: "#cdd2da",
    borderStrong: "#cdd2da",
    accent: "#164B40",
    accentText: "#10372F",
    accentSoft: "#E8F0EE",
    button: "#164B40",
    buttonHover: "#0F3A31",
    buttonText: "#ffffff",
    success: "#2E7D32",
    warning: "#F57C00",
    error: "#C62828",
    warningBg: "#FFF8E1",
    errorBg: "#FFEBEE",
    successBg: "#E8F5E8",
    overlay: "rgba(26, 28, 32, 0.32)",
  },
  dark: {
    bg: "#161b22",
    directory: "#161b22",
    rail: "#0d1117",
    surface: "#161b22",
    surface2: "#0d1117",
    input: "#2a2e36",
    ink: "#e6edf3",
    body: "#c9d1d9",
    muted: "#8b949e",
    border: "#30363d",
    borderStrong: "#30363d",
    accent: "#5FA38F",
    accentText: "#8FC4B2",
    accentSoft: "#1D2B26",
    button: "#3E7A66",
    buttonHover: "#5FA38F",
    buttonText: "#ffffff",
    success: "#86EFAC",
    warning: "#FCD34D",
    error: "#FCA5A5",
    warningBg: "#1F2937",
    errorBg: "#1F2937",
    successBg: "#1F2937",
    overlay: "rgba(0, 0, 0, 0.55)",
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
            colorPrimary: c.button,
            colorBgLayout: c.rail,
            // Rhesis ELEVATION tokens (theme-constants.ts), measured from their product.
            boxShadow: "0px 2px 4px rgba(84, 90, 101, 0.25)",
            boxShadowSecondary:
              "0px 16px 32px -4px rgba(84, 90, 101, 0.10), 0px 4px 4px rgba(84, 90, 101, 0.04)",
            boxShadowTertiary:
              "0px 24px 48px -8px rgba(84, 90, 101, 0.12), 0px 4px 4px rgba(84, 90, 101, 0.04)",
          },
          components: {
            Button: { primaryShadow: "none", defaultShadow: "none" },
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
