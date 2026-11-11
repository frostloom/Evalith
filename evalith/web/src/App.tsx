import {
  Plus as AddRounded,
  Search as SearchRounded,
  ArrowUpRight as ArrowOutwardRounded,
  Clock3 as ScheduleRounded,
  FolderClosed as FolderOutlined,
} from "lucide-react";
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
import { ExecutorSettings } from "./ExecutorSettings";
import { Workspace } from "./Workspace";
import { Navigation } from "./Navigation";
import { PageHeader } from "./ui";
import { AppThemeProvider } from "./theme";
import {
  Alert,
  Button,
  InputAdornment,
  Snackbar,
  TextField,
  Tooltip,
  ToggleButton,
  ToggleButtonGroup,
} from "@mui/material";

type View = "home" | "project" | "import" | "models" | "executors";

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
    selectedProjectRef.current = null;
    displayedProjectRef.current = null;
    setDetail(null);
    setProjects((current) => [
      next.project,
      ...current.filter((item) => item.id !== next.project.id),
    ]);
    setView("home");
    writeRoute("#/projects");
    setNotice(
      next.project.analysis_error
        ? "项目已建立，初步分析失败。可从项目卡片进入检查原因。"
        : "项目已建立，点击项目卡片开始会话。",
    );
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

  const openExecutors = () => {
    setNavOpen(false);
    importGeneration.current += 1;
    openSequence.current += 1;
    selectedProjectRef.current = null;
    setBusy(false);
    setView("executors");
    writeRoute("#/executors");
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
    openExecutors,
    goHome,
    view,
  });
  routeActions.current = {
    projects,
    openProject,
    openModels,
    openExecutors,
    goHome,
    view,
  };
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
      else if (window.location.hash === "#/executors") actions.openExecutors();
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
    <div
      className={`app-shell ${effectiveView === "project" ? "is-project" : "is-directory"} ${collapsed ? "sidebar-collapsed" : ""}`}
    >
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
        activeProject={
          effectiveView === "project" ? (detail?.project ?? null) : null
        }
        section={workspaceTab}
        modelsActive={effectiveView === "models"}
        executorsActive={effectiveView === "executors"}
        collapsed={collapsed}
        mobileOpen={navOpen}
        onCollapse={() => setCollapsed((current) => !current)}
        onMobileToggle={() => setNavOpen((current) => !current)}
        onHome={goHome}
        onModels={openModels}
        onExecutors={openExecutors}
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
            models={models}
            loading={!loaded}
            onOpen={(project) => void openProject(project)}
            onImport={startImport}
          />
        )}
        {effectiveView === "executors" && <ExecutorSettings />}
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
            hideTabs
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
  models,
  onOpen,
  onImport,
  loading,
}: {
  projects: Project[];
  models: ModelConfig[];
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
    <div className="project-directory">
      <div className="directory-topbar">
        <FolderOutlined />
        <span>工作区</span>
        <span className="toolbar-slash">/</span>
        <strong>项目目录</strong>
      </div>
      <div className="directory-body">
        <PageHeader
          title="项目"
          description="从一个项目开始，整理资料，明确评测方向。"
          actions={
            projects.length ? (
              <Tooltip title="从本地目录建立项目">
                <Button
                  variant="contained"
                  aria-label="建立项目"
                  startIcon={<AddRounded />}
                  onClick={onImport}
                >
                  建立项目
                </Button>
              </Tooltip>
            ) : undefined
          }
        />
        {!!projects.length && (
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
        )}
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
                <div className="project-card-top">
                  <span className="project-card-icon" aria-hidden="true">
                    <FolderOutlined />
                  </span>
                  <div className="project-card-heading">
                    <strong>{project.name}</strong>
                    <span>持续会话</span>
                  </div>
                  <ArrowOutwardRounded className="card-enter-arrow" />
                </div>
                <p className="project-card-path" title={project.root_path}>
                  {compactPath(project.root_path)}
                </p>
                <div className="project-card-details">
                  <span>
                    <FolderOutlined />
                    {project.file_count} 个文件
                  </span>
                  <span className="project-card-model">
                    <span className="model-presence" />
                    {models.find(
                      (model) => model.id === project.model_config_id,
                    )?.name ?? "尚未关联模型"}
                  </span>
                </div>
                {project.analysis_error && (
                  <span className="project-card-error">初步分析需要检查</span>
                )}
                <div className="project-card-footer">
                  <span>
                    <ScheduleRounded />
                    {new Date(project.updated_at).toLocaleDateString("zh-CN", {
                      month: "short",
                      day: "numeric",
                    })}
                    更新
                  </span>
                  <span className="card-open-label">
                    打开会话 <ArrowOutwardRounded />
                  </span>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <section className="empty-state">
            <div className="empty-project-art" aria-hidden="true">
              <FolderOutlined />
            </div>
            <h2>{projects.length ? "没有匹配的项目" : "创建第一个项目"}</h2>
            <p>
              {projects.length
                ? "调整搜索词或筛选条件，找到需要的项目。"
                : "连接本地项目与资料，和模型一起明确评测方向。"}
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
              {projects.length ? "清除筛选" : "建立项目"}
            </Button>
          </section>
        )}
      </div>
    </div>
  );
}
