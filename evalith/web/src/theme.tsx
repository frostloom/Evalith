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
import { createTheme, ThemeProvider } from "@mui/material/styles";
import { CssBaseline, GlobalStyles, IconButton, Tooltip } from "@mui/material";

export type ColorMode = "light" | "dark";
export const THEME_KEY = "evalith.theme";
export const ui = {
  font: 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif',
  drawer: 560,
};

/**
 * One design system, "precision instrument": a barely-warm neutral canvas,
 * ink-first hierarchy, a single restrained blue accent reserved for actions,
 * active states and links, semantic states as tinted pills, depth from
 * 1px borders plus two subtle shadow steps, and a 120–240ms motion layer
 * (see system.css) with visible focus rings.
 */
const palettes = {
  light: {
    bg: "#ffffff",
    directory: "#fcfcfb",
    rail: "#f7f7f5",
    surface: "#ffffff",
    surface2: "#f3f3f1",
    input: "#ffffff",
    ink: "#191c22",
    body: "#474e5c",
    muted: "#676f7e",
    border: "#e7e7e5",
    borderStrong: "#d4d5d4",
    accent: "#3b5bdb",
    accentText: "#2f4cc0",
    accentSoft: "#eef1fb",
    button: "#2f4cc0",
    buttonHover: "#2843ab",
    buttonText: "#ffffff",
    success: "#157347",
    warning: "#8a5e08",
    error: "#b8394c",
    warningBg: "#faf3e2",
    errorBg: "#fbeef0",
    successBg: "#eaf5ef",
    overlay: "rgba(23,25,31,0.32)",
  },
  dark: {
    bg: "#0f1115",
    directory: "#12141a",
    rail: "#0f1115",
    surface: "#161920",
    surface2: "#20242d",
    input: "#171b22",
    ink: "#eceef4",
    body: "#b9c0cd",
    muted: "#8b93a5",
    border: "#262b35",
    borderStrong: "#3a4150",
    accent: "#8fa7ff",
    accentText: "#b3c4ff",
    accentSoft: "#1e2740",
    button: "#a7b9ff",
    buttonHover: "#9bb0ff",
    buttonText: "#10131a",
    success: "#6ec298",
    warning: "#d3b571",
    error: "#ef97a1",
    warningBg: "#2a2318",
    errorBg: "#2e1d22",
    successBg: "#15271e",
    overlay: "rgba(0,0,0,0.55)",
  },
};
export type Palette = (typeof palettes)["light"];

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
          primary: {
            main: c.button,
            dark: c.buttonHover,
            contrastText: c.buttonText,
          },
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
            lineHeight: 1.35,
            fontWeight: 650,
            letterSpacing: "-0.018em",
          },
          h5: {
            fontSize: "1.0625rem",
            lineHeight: 1.4,
            fontWeight: 650,
            letterSpacing: "-0.012em",
          },
          h6: { fontSize: "0.9375rem", fontWeight: 650 },
          body1: { fontSize: "0.875rem", lineHeight: 1.7 },
          body2: { fontSize: "0.8125rem", lineHeight: 1.65 },
          button: {
            fontSize: "0.8125rem",
            textTransform: "none",
            fontWeight: 560,
          },
        },
        shape: { borderRadius: 8 },
        components: {
          MuiButtonBase: {
            defaultProps: { disableRipple: true },
          },
          MuiButton: {
            defaultProps: { disableElevation: true, size: "small" },
            styleOverrides: {
              root: {
                minHeight: 32,
                padding: "6px 14px",
                borderRadius: 8,
                transition:
                  "background-color 140ms cubic-bezier(0.2,0,0,1), border-color 140ms cubic-bezier(0.2,0,0,1), color 140ms cubic-bezier(0.2,0,0,1), box-shadow 140ms cubic-bezier(0.2,0,0,1)",
                "&:active": { transform: "scale(0.985)" },
                "&.Mui-focusVisible": {
                  boxShadow: `0 0 0 2px ${c.surface}, 0 0 0 4px ${c.accent}`,
                },
              },
              containedPrimary: {
                backgroundColor: c.button,
                color: c.buttonText,
                "&:hover": { backgroundColor: c.buttonHover },
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
                borderRadius: 8,
                transition:
                  "background-color 140ms cubic-bezier(0.2,0,0,1), color 140ms cubic-bezier(0.2,0,0,1)",
                "&:hover": { backgroundColor: c.surface2, color: c.ink },
                "&.Mui-focusVisible": {
                  boxShadow: `0 0 0 2px ${c.surface}, 0 0 0 4px ${c.accent}`,
                },
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
                borderRadius: 8,
                transition:
                  "border-color 140ms cubic-bezier(0.2,0,0,1), box-shadow 140ms cubic-bezier(0.2,0,0,1)",
                "&:hover fieldset": { borderColor: c.muted },
                "& fieldset": { borderColor: c.borderStrong },
                "&.Mui-focused fieldset": {
                  borderColor: c.accent,
                  boxShadow: `0 0 0 3px ${c.accentSoft}`,
                },
                "&.Mui-focused": { backgroundColor: c.input },
              },
              input: {
                padding: "8px 12px",
                "&::placeholder": { color: c.muted, opacity: 1 },
              },
            },
          },
          MuiPaper: {
            styleOverrides: {
              root: { backgroundImage: "none" },
            },
          },
          MuiDialog: {
            styleOverrides: {
              paper: {
                borderRadius: 12,
                border: `1px solid ${c.border}`,
                boxShadow:
                  mode === "light"
                    ? "0 1px 2px rgba(16,20,28,0.06), 0 12px 40px rgba(16,20,28,0.16)"
                    : "0 1px 2px rgba(0,0,0,0.4), 0 12px 40px rgba(0,0,0,0.55)",
              },
            },
          },
          MuiDrawer: {
            styleOverrides: {
              paper: {
                borderRadius: 0,
                backgroundColor: c.bg,
                borderLeft: `1px solid ${c.border}`,
                boxShadow:
                  mode === "light"
                    ? "-12px 0 40px rgba(16,20,28,0.08)"
                    : "-12px 0 40px rgba(0,0,0,0.45)",
              },
            },
          },
          MuiMenu: {
            styleOverrides: {
              paper: {
                borderRadius: 10,
                border: `1px solid ${c.border}`,
                boxShadow:
                  mode === "light"
                    ? "0 1px 2px rgba(16,20,28,0.06), 0 8px 28px rgba(16,20,28,0.14)"
                    : "0 1px 2px rgba(0,0,0,0.4), 0 8px 28px rgba(0,0,0,0.5)",
              },
            },
          },
          MuiMenuItem: {
            styleOverrides: {
              root: {
                fontSize: 13,
                transition:
                  "background-color 120ms cubic-bezier(0.2,0,0,1)",
                "&:hover": { backgroundColor: c.surface2 },
                "&.Mui-selected": { backgroundColor: c.accentSoft },
              },
            },
          },
          MuiTab: {
            styleOverrides: {
              root: {
                textTransform: "none",
                fontSize: 13,
                fontWeight: 550,
                padding: "10px 0",
                marginRight: 26,
                minWidth: 0,
                minHeight: 40,
                color: c.muted,
                transition: "color 140ms cubic-bezier(0.2,0,0,1)",
                "&:hover": { color: c.body },
                "&.Mui-selected": { color: c.ink },
              },
            },
          },
          MuiTabs: {
            styleOverrides: {
              root: { minHeight: 40 },
              indicator: { height: 2, backgroundColor: c.accent },
            },
          },
          MuiChip: {
            styleOverrides: {
              root: {
                fontSize: 11,
                fontWeight: 550,
                letterSpacing: "0.01em",
                borderRadius: 999,
                height: 22,
                backgroundColor: c.surface2,
                color: c.muted,
              },
            },
          },
          MuiAlert: {
            styleOverrides: {
              root: { borderRadius: 10, fontSize: 13, alignItems: "center" },
            },
          },
          MuiTooltip: {
            defaultProps: { arrow: false },
            styleOverrides: {
              tooltip: {
                backgroundColor:
                  mode === "light" ? "#1f232b" : "#e8ebf1",
                color: mode === "light" ? "#f2f4f8" : "#14171d",
                fontSize: 12,
                fontWeight: 500,
                borderRadius: 6,
                padding: "5px 9px",
              },
            },
          },
          MuiListItemButton: {
            styleOverrides: {
              root: {
                borderRadius: 8,
                "&.Mui-selected": {
                  backgroundColor: c.accentSoft,
                  "&:hover": { backgroundColor: c.accentSoft },
                },
              },
            },
          },
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
    "--button-hover": c.buttonHover,
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
