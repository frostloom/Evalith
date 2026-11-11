import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  ModelConfig,
  Project,
  ProjectDetail,
  WorkspaceTab,
} from "./types";
import { ImportSheet } from "./ImportSheet";
import { ModelSettings } from "./ModelSettings";
import { Workspace } from "./Workspace";
import { Navigation } from "./Navigation";
import { PageHeader } from "./ui";
import { AppThemeProvider } from "./theme";
import {
  Alert,
  Button,
  Chip,
  InputAdornment,
  Snackbar,
  TextField,
  Tooltip,
  ToggleButton,
  ToggleButtonGroup,
} from "@mui/material";
import AddRounded from "@mui/icons-material/AddRounded";
import SearchRounded from "@mui/icons-material/SearchRounded";
import SmartToyOutlined from "@mui/icons-material/SmartToyOutlined";
import FolderOutlined from "@mui/icons-material/FolderOutlined";

type View = "home" | "project" | "import" | "models";

function compactPath(value: string): string {
  const parts = value.split("/").filter(Boolean);
  return parts.length <= 3 ? value : `…/${parts.slice(-2).join("/")}`;
}

export function App() {
  return (
    <AppThemeProvider>
      <AppContent />
    </AppThemeProvider>
  );
}

function AppContent() {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [view, setView] = useState<View>("home");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [workspaceTab, setWorkspaceTab] =
    useState<WorkspaceTab>("conversation");
  const [loaded, setLoaded] = useState(false);
  const importReturnView = useRef<"home" | "project">("home");
  const selectedProjectRef = useRef<string | null>(null);
  const displayedProjectRef = useRef<string | null>(null);
  const openSequence = useRef(0);
  const importGeneration = useRef(0);
  const routedHash = useRef<string | undefined>(undefined);
  const writeRoute = (hash: string) => {
    routedHash.current = hash;
    if (window.location.hash !== hash) window.history.pushState(null, "", hash);
  };

  const load = useCallback(async () => {
    try {
      const [modelResponse, projectResponse] = await Promise.all([
        api.listModels(),
        api.listProjects(),
      ]);
      setModels(modelResponse.items);
      setProjects(projectResponse.items);
      setLoaded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法连接 Evalith 服务");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const openProject = async (
    project: Project,
    tab: WorkspaceTab = "conversation",
  ) => {
    setNavOpen(false);
    importGeneration.current += 1;
    const sequence = ++openSequence.current;
    selectedProjectRef.current = project.id;
    setBusy(true);
    setError(null);
    try {
      const next = await api.enterProject(project.id);
      if (sequence !== openSequence.current) return;
      if (next.project.id !== selectedProjectRef.current) return;
      displayedProjectRef.current = next.project.id;
      setDetail(next);
      setView("project");
      setWorkspaceTab(tab);
      writeRoute(`#/projects/${project.id}?tab=${tab}`);
    } catch (err) {
      if (sequence === openSequence.current) {
        selectedProjectRef.current = displayedProjectRef.current;
        setError(err instanceof Error ? err.message : "无法进入项目");
      }
    } finally {
      if (sequence === openSequence.current) setBusy(false);
    }
  };

  const handleCreated = (next: ProjectDetail, token: number) => {
    if (token !== importGeneration.current) return;
    if (selectedProjectRef.current !== null) return;
    selectedProjectRef.current = next.project.id;
    displayedProjectRef.current = next.project.id;
    setDetail(next);
    setView("project");
    setWorkspaceTab("conversation");
    writeRoute(`#/projects/${next.project.id}?tab=conversation`);
    setNotice("项目已导入，初步理解已生成。");
    void load();
  };

  const handleDetail = (next: ProjectDetail) => {
    // A pending response from project A must never replace the workspace of
    // the project the user switched to, nor submit its drafts to B.
    if (selectedProjectRef.current !== next.project.id) return;
    setDetail(next);
    setProjects((current) =>
      current.map((item) =>
        item.id === next.project.id ? next.project : item,
      ),
    );
  };

  const startImport = () => {
    setNavOpen(false);
    importGeneration.current += 1;
    openSequence.current += 1;
    selectedProjectRef.current = null;
    setBusy(false);
    importReturnView.current = view === "project" ? "project" : "home";
    setView("import");
  };

  const openModels = () => {
    setNavOpen(false);
    importGeneration.current += 1;
    openSequence.current += 1;
    selectedProjectRef.current = null;
    setBusy(false);
    setView("models");
    writeRoute("#/models");
  };

  const goHome = (updateHistory = true) => {
    setNavOpen(false);
    importGeneration.current += 1;
    openSequence.current += 1;
    selectedProjectRef.current = null;
    setView("home");
    setBusy(false);
    setDetail(null);
    displayedProjectRef.current = null;
    if (updateHistory) writeRoute("#/projects");
    void load();
  };

  const effectiveView = view === "import" ? importReturnView.current : view;
  const changeTab = (tab: WorkspaceTab) => {
    setNavOpen(false);
    if (!detail) return;
    if (effectiveView !== "project") {
      void openProject(detail.project, tab);
      return;
    }
    setWorkspaceTab(tab);
    writeRoute(`#/projects/${detail.project.id}?tab=${tab}`);
  };
  const cancelImport = () => {
    importGeneration.current += 1;
    selectedProjectRef.current =
      importReturnView.current === "project"
        ? displayedProjectRef.current
        : null;
    setView(importReturnView.current);
  };
  const routeActions = useRef({
    projects,
    openProject,
    openModels,
    goHome,
    view,
  });
  routeActions.current = { projects, openProject, openModels, goHome, view };
  useEffect(() => {
    if (!loaded) return;
    const restore = () => {
      if (routedHash.current === window.location.hash) return;
      routedHash.current = window.location.hash;
      const actions = routeActions.current;
      const match = window.location.hash.match(
        /^#\/projects\/([^?]+)(?:\?(.*))?$/,
      );
      if (match) {
        const project = actions.projects.find(
          (item) => encodeURIComponent(item.id) === match[1],
        );
        const tab = new URLSearchParams(match[2] ?? "").get("tab");
        if (project)
          void actions.openProject(
            project,
            tab === "overview" || tab === "sources" ? tab : "conversation",
          );
        else {
          actions.goHome();
          setError("项目不存在或不在当前工作区中。");
        }
      } else if (window.location.hash === "#/models") actions.openModels();
      else if (actions.view !== "home") actions.goHome(false);
    };
    restore();
    window.addEventListener("popstate", restore);
    window.addEventListener("hashchange", restore);
    return () => {
      window.removeEventListener("popstate", restore);
      window.removeEventListener("hashchange", restore);
    };
  }, [loaded]);

  return (
    <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        跳到主要内容
      </a>
      <Navigation
        projects={projects}
        activeProject={detail?.project ?? null}
        section={workspaceTab}
        modelsActive={effectiveView === "models"}
        collapsed={collapsed}
        mobileOpen={navOpen}
        onCollapse={() => setCollapsed((current) => !current)}
        onMobileToggle={() => setNavOpen((current) => !current)}
        onHome={goHome}
        onModels={openModels}
        onImport={startImport}
        onOpen={(project) => void openProject(project)}
        onSection={changeTab}
      />
      <main id="main-content" className="main" tabIndex={-1} aria-busy={busy}>
        {error && (
          <Alert
            severity="error"
            onClose={() => setError(null)}
            className="global-error"
          >
            {error}
          </Alert>
        )}
        {effectiveView === "home" && (
          <Home
            projects={projects}
            loading={!loaded}
            onOpen={(project) => void openProject(project)}
            onImport={startImport}
          />
        )}
        {effectiveView === "models" && (
          <ModelSettings
            models={models}
            onRefresh={load}
            onBack={() =>
              detail ? void openProject(detail.project) : goHome()
            }
            onError={setError}
            onNotice={setNotice}
          />
        )}
        {effectiveView === "project" && detail && (
          <Workspace
            key={detail.project.id}
            detail={detail}
            models={models}
            busy={busy}
            tab={workspaceTab}
            onTabChange={changeTab}
            onDetail={handleDetail}
            onHome={goHome}
            onError={setError}
            onNotice={setNotice}
          />
        )}
      </main>
      {view === "import" && (
        <ImportSheet
          models={models}
          token={importGeneration.current}
          onCancel={cancelImport}
          onCreated={handleCreated}
          onNeedModel={openModels}
          onError={setError}
        />
      )}
      <Snackbar
        open={Boolean(notice)}
        autoHideDuration={4200}
        onClose={() => setNotice(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
      >
        <Alert
          severity="success"
          variant="filled"
          onClose={() => setNotice(null)}
        >
          {notice}
        </Alert>
      </Snackbar>
    </div>
  );
}

function Home({
  projects,
  onOpen,
  onImport,
  loading,
}: {
  projects: Project[];
  onOpen: (project: Project) => void;
  onImport: () => void;
  loading: boolean;
}) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const filtered = projects.filter(
    (project) =>
      `${project.name} ${project.root_path}`
        .toLowerCase()
        .includes(search.toLowerCase()) &&
      (filter === "all" ||
        (filter === "configured"
          ? Boolean(project.model_config_id)
          : !project.model_config_id)),
  );
  return (
    <div className="page project-directory">
      <PageHeader
        title="项目"
        description="从项目资料开始，逐步明确评测方向。"
        actions={
          <Tooltip title="导入本地项目">
            <Button
              variant="contained"
              aria-label="导入本地项目"
              startIcon={<AddRounded />}
              onClick={onImport}
            >
              导入项目
            </Button>
          </Tooltip>
        }
      />
      <div className="directory-toolbar">
        <TextField
          placeholder="搜索项目…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          slotProps={{
            htmlInput: { "aria-label": "搜索项目" },
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <SearchRounded fontSize="small" />
                </InputAdornment>
              ),
            },
          }}
        />
        <ToggleButtonGroup
          exclusive
          size="small"
          value={filter}
          onChange={(_, value: string | null) => {
            if (value) setFilter(value);
          }}
          aria-label="项目筛选"
        >
          <ToggleButton value="all">全部</ToggleButton>
          <ToggleButton value="configured">已配置模型</ToggleButton>
          <ToggleButton value="unconfigured">待配置模型</ToggleButton>
        </ToggleButtonGroup>
        <span className="directory-count">{filtered.length} 个项目</span>
      </div>
      {loading ? (
        <p role="status" className="empty-state">
          正在加载项目…
        </p>
      ) : filtered.length ? (
        <div className="project-grid">
          {filtered.map((project) => (
            <button
              className="project-card"
              key={project.id}
              onClick={() => onOpen(project)}
            >
              <div className="project-card-heading">
                <SmartToyOutlined />
                <strong>{project.name}</strong>
              </div>
              <p className="project-card-path" title={project.root_path}>
                {compactPath(project.root_path)}
              </p>
              <div className="project-card-field">
                <span>状态</span>
                <Chip
                  size="small"
                  label={
                    project.analysis_error
                      ? "分析失败"
                      : project.model_config_id
                        ? "已配置模型"
                        : "待配置模型"
                  }
                  color={project.analysis_error ? "error" : "default"}
                />
              </div>
              <div className="project-card-field">
                <span>资料范围</span>
                <span>
                  <FolderOutlined fontSize="small" />
                  {project.file_count} 个文件
                </span>
              </div>
              <div className="project-card-footer">
                <span>本地项目</span>
                <span className="mono">
                  {project.snapshot_digest?.slice(0, 10) ?? "未扫描"}
                </span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <section className="empty-state">
          <AppsEmpty />
          <h2>{projects.length ? "没有匹配的项目" : "创建第一个项目"}</h2>
          <p>
            {projects.length
              ? "调整搜索词或筛选条件，找到需要的项目。"
              : "导入本地目录，选择分析范围，然后核对项目理解。"}
          </p>
          <Button
            variant="contained"
            onClick={
              projects.length
                ? () => {
                    setSearch("");
                    setFilter("all");
                  }
                : onImport
            }
          >
            {projects.length ? "清除筛选" : "导入本地项目"}
          </Button>
        </section>
      )}
    </div>
  );
}

function AppsEmpty() {
  return (
    <span className="empty-state-icon">
      <SmartToyOutlined />
    </span>
  );
}
