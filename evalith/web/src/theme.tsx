import {
  createContext,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { createTheme, ThemeProvider } from "@mui/material/styles";
import { CssBaseline, GlobalStyles, IconButton, Tooltip } from "@mui/material";
import DarkModeOutlined from "@mui/icons-material/DarkModeOutlined";
import LightModeOutlined from "@mui/icons-material/LightModeOutlined";

export type ColorMode = "light" | "dark";
export const THEME_KEY = "evalith.theme";
export const ui = {
  font: 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif',
  drawer: 560,
};
const palettes = {
  light: {
    bg: "#ffffff",
    directory: "#fafafb",
    rail: "#f6f6f8",
    surface: "#ffffff",
    surface2: "#f8f8fa",
    input: "#fafafb",
    ink: "#24252b",
    body: "#3e3f48",
    muted: "#6b6d79",
    border: "#e6e6eb",
    borderStrong: "#d6d7df",
    accent: "#626bd2",
    accentText: "#5058b9",
    accentSoft: "#ececf5",
    button: "#282931",
    buttonText: "#ffffff",
    success: "#237c55",
    warning: "#956108",
    error: "#b43d50",
    warningBg: "#faf5e9",
    errorBg: "#fcf0f2",
    successBg: "#edf7f1",
    overlay: "rgba(24,25,31,0.28)",
  },
  dark: {
    bg: "#191a1e",
    directory: "#16171b",
    rail: "#15161a",
    surface: "#202126",
    surface2: "#23242b",
    input: "#1c1d22",
    ink: "#ebebef",
    body: "#c4c5ce",
    muted: "#999ba8",
    border: "#2d2e36",
    borderStrong: "#42444f",
    accent: "#8189e4",
    accentText: "#a5acf8",
    accentSoft: "#2b2c3b",
    button: "#e5e5eb",
    buttonText: "#22232a",
    success: "#81c9a3",
    warning: "#d4b474",
    error: "#ed919e",
    warningBg: "#2b271e",
    errorBg: "#302229",
    successBg: "#1d2d26",
    overlay: "rgba(0,0,0,0.5)",
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
  const theme = useMemo(
    () =>
      createTheme({
        palette: {
          mode,
          primary: { main: c.accent, dark: c.accentText, contrastText: "#fff" },
          background: { default: c.bg, paper: c.surface },
          text: { primary: c.ink, secondary: c.muted },
          divider: c.border,
          success: { main: c.success },
          warning: { main: c.warning },
          error: { main: c.error },
        },
        typography: {
          fontFamily: ui.font,
          h4: {
            fontSize: "1.375rem",
            lineHeight: 1.4,
            fontWeight: 600,
            letterSpacing: "-0.025em",
          },
          h5: {
            fontSize: "1.125rem",
            lineHeight: 1.4,
            fontWeight: 600,
            letterSpacing: "-0.02em",
          },
          h6: { fontSize: "1rem", fontWeight: 600 },
          body1: { fontSize: "0.875rem", lineHeight: 1.75 },
          body2: { fontSize: "0.8125rem", lineHeight: 1.65 },
          button: {
            fontSize: "0.8125rem",
            textTransform: "none",
            fontWeight: 500,
          },
        },
        shape: { borderRadius: 6 },
        components: {
          MuiButton: {
            defaultProps: { disableElevation: true, size: "small" },
            styleOverrides: {
              root: {
                minHeight: 32,
                padding: "5px 11px",
                boxShadow: "none",
                transition: "none",
              },
              containedPrimary: {
                backgroundColor: c.button,
                color: c.buttonText,
                "&:hover": {
                  backgroundColor: c.button,
                  filter: "brightness(0.92)",
                },
              },
              outlinedPrimary: {
                color: c.body,
                borderColor: c.borderStrong,
                "&:hover": {
                  borderColor: c.muted,
                  backgroundColor: c.surface2,
                },
              },
              textPrimary: {
                color: c.muted,
                "&:hover": { backgroundColor: c.surface2, color: c.ink },
              },
            },
          },
          MuiIconButton: {
            defaultProps: { size: "small" },
            styleOverrides: {
              root: {
                color: c.muted,
                "&:hover": { backgroundColor: c.surface2 },
              },
            },
          },
          MuiTextField: {
            defaultProps: { size: "small", variant: "outlined" },
          },
          MuiOutlinedInput: {
            styleOverrides: {
              root: {
                backgroundColor: c.input,
                fontSize: 13,
                "& fieldset": { borderColor: c.borderStrong },
              },
              input: { padding: "8px 11px" },
            },
          },
          MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
          MuiDrawer: {
            styleOverrides: {
              paper: {
                borderRadius: 0,
                backgroundColor: c.bg,
                borderLeft: `1px solid ${c.border}`,
              },
            },
          },
          MuiTab: {
            styleOverrides: {
              root: {
                textTransform: "none",
                fontSize: 12,
                fontWeight: 500,
                padding: "10px 0",
                marginRight: 26,
                minWidth: 0,
                minHeight: 40,
                color: c.muted,
                "&.Mui-selected": { color: c.ink },
              },
            },
          },
          MuiTabs: {
            styleOverrides: {
              root: { minHeight: 40 },
              indicator: { height: 1, backgroundColor: c.ink },
            },
          },
          MuiChip: {
            styleOverrides: {
              root: {
                fontSize: 11,
                borderRadius: 4,
                height: 22,
                backgroundColor: c.surface2,
                color: c.muted,
              },
            },
          },
          MuiListItemButton: {
            styleOverrides: {
              root: {
                "&.Mui-selected": {
                  backgroundColor: c.accentSoft,
                  "&:hover": { backgroundColor: c.accentSoft },
                },
              },
            },
          },
          MuiTooltip: { defaultProps: { arrow: false } },
        },
      }),
    [c, mode],
  );
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = mode;
    document.documentElement.style.colorScheme = mode;
  }, [mode]);
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
  const variables = {
    "--canvas": c.bg,
    "--directory": c.directory,
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
    "--button-text": c.buttonText,
    "--success": c.success,
    "--warning": c.warning,
    "--error": c.error,
    "--warning-bg": c.warningBg,
    "--error-bg": c.errorBg,
    "--success-bg": c.successBg,
    "--overlay": c.overlay,
  };
  return (
    <ThemeContext.Provider value={{ mode, toggle }}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <GlobalStyles styles={{ ":root": variables }} />
        {children}
      </ThemeProvider>
    </ThemeContext.Provider>
  );
}

export function ThemeToggle() {
  const { mode, toggle } = useColorMode();
  const label = mode === "light" ? "切换到深色模式" : "切换到浅色模式";
  return (
    <Tooltip title={label}>
      <IconButton onClick={toggle} aria-label={label} className="theme-toggle">
        {mode === "light" ? (
          <DarkModeOutlined fontSize="small" />
        ) : (
          <LightModeOutlined fontSize="small" />
        )}
      </IconButton>
    </Tooltip>
  );
}
