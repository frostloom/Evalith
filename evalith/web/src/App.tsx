import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { ModelConfig, Project, ProjectDetail } from "./types";
import { ImportSheet } from "./ImportSheet";
import { ModelSettings } from "./ModelSettings";
import { Workspace } from "./Workspace";

type View = "home" | "project" | "import" | "models";

function compactPath(value: string): string {
  const parts = value.split("/").filter(Boolean);
  return parts.length <= 3 ? value : `…/${parts.slice(-2).join("/")}`;
}

export function App() {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [view, setView] = useState<View>("home");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const selectedProjectRef = useRef<string | null>(null);
  const displayedProjectRef = useRef<string | null>(null);
  const openSequence = useRef(0);
  const importGeneration = useRef(0);

  const load = useCallback(async () => {
    try {
      const [modelResponse, projectResponse] = await Promise.all([
        api.listModels(),
        api.listProjects(),
      ]);
      setModels(modelResponse.items);
      setProjects(projectResponse.items);
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

  const openProject = async (project: Project) => {
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
    setNotice("项目已导入，初步理解已生成。");
    void load();
  };

  const handleDetail = (next: ProjectDetail) => {
    // A pending response from project A must never replace the workspace of
    // the project the user switched to, nor submit its drafts to B.
    if (selectedProjectRef.current !== next.project.id) return;
    setDetail(next);
    setProjects((current) =>
      current.map((item) => (item.id === next.project.id ? next.project : item)),
    );
  };

  const startImport = () => {
    importGeneration.current += 1;
    openSequence.current += 1;
    selectedProjectRef.current = null;
    setBusy(false);
    setView("import");
  };

  const openModels = () => {
    importGeneration.current += 1;
    openSequence.current += 1;
    selectedProjectRef.current = null;
    setBusy(false);
    setView("models");
  };

  const goHome = () => {
    importGeneration.current += 1;
    openSequence.current += 1;
    selectedProjectRef.current = null;
    setView("home");
    setDetail(null);
    void load();
  };

  return (
    <div className="app-shell">
      <aside className="rail">
        <button className="brand" onClick={goHome} aria-label="回到项目列表">
          <span className="brand-name">Evalith</span>
          <span className="brand-sub">评测工作台 · 阶段 1</span>
        </button>

        <div className="rail-body">
          <div className="rail-label">项目</div>
          <nav className="project-nav" aria-label="项目列表">
            {projects.length === 0 && (
              <p className="rail-empty">还没有项目。先导入一个本地目录。</p>
            )}
            {projects.map((project) => (
              <button
                key={project.id}
                className={`project-nav-item ${
                  detail?.project.id === project.id ? "is-active" : ""
                }`}
                onClick={() => void openProject(project)}
              >
                <span className="project-nav-name">{project.name}</span>
                <span className="project-nav-meta">
                  {project.file_count} 个文件
                  {project.analysis_error ? " · 分析失败" : ""}
                </span>
              </button>
            ))}
          </nav>

          <button className="rail-action" onClick={startImport}>
            <span aria-hidden="true">＋</span> 导入本地项目
          </button>
        </div>

        <div className="rail-foot">
          <button
            className={`rail-link ${view === "models" ? "is-active" : ""}`}
            onClick={openModels}
          >
            模型与凭据
          </button>
          <p className="rail-note">资料只读分析。密钥加密保存，不进入模型上下文。</p>
        </div>
      </aside>

      <main className="main">
        {error && (
          <div className="global-error" role="alert">
            <span>{error}</span>
            <button onClick={() => setError(null)} aria-label="关闭错误提示">
              关闭
            </button>
          </div>
        )}

        {view === "home" && (
          <Home
            projects={projects}
            onOpen={(project) => void openProject(project)}
            onImport={startImport}
            onModels={openModels}
            models={models}
          />
        )}

        {view === "import" && (
          <ImportSheet
            models={models}
            token={importGeneration.current}
            onCancel={() => {
              importGeneration.current += 1;
              setView("home");
            }}
            onCreated={handleCreated}
            onNeedModel={() => {
              importGeneration.current += 1;
              setView("models");
            }}
            onError={setError}
          />
        )}

        {view === "models" && (
          <ModelSettings
            models={models}
            onRefresh={load}
            onBack={() => {
              if (detail) {
                void openProject(detail.project);
              } else {
                setView("home");
              }
            }}
            onError={setError}
            onNotice={setNotice}
          />
        )}

        {view === "project" && detail && (
          <Workspace
            key={detail.project.id}
            detail={detail}
            models={models}
            busy={busy}
            onDetail={handleDetail}
            onHome={goHome}
            onError={setError}
            onNotice={setNotice}
          />
        )}

        {view === "project" && !detail && (
          <div className="empty-main">
            <p>选择左侧项目，或导入新的本地项目。</p>
          </div>
        )}
      </main>

      {notice && (
        <div className="toast" role="status">
          {notice}
        </div>
      )}
    </div>
  );
}

function Home({
  projects,
  models,
  onOpen,
  onImport,
  onModels,
}: {
  projects: Project[];
  models: ModelConfig[];
  onOpen: (project: Project) => void;
  onImport: () => void;
  onModels: () => void;
}) {
  return (
    <div className="home">
      <header className="page-head">
        <p className="kicker">本地项目 · 只读分析</p>
        <h1>先理解项目，再决定评测方向。</h1>
        <p className="lede">
          Evalith 读取你明确选择的本地资料，形成一份区分已知、推断与未知的项目理解。
          你可以纠正它，或在资料足够时继续。题目、环境与运行属于后续阶段。
        </p>
        <div className="page-head-actions">
          <button className="btn btn-primary" onClick={onImport}>
            导入本地项目
          </button>
          <button className="btn btn-quiet" onClick={onModels}>
            配置模型服务
          </button>
        </div>
      </header>

      <section className="home-grid">
        <div className="list-block">
          <div className="section-heading">
            <h2>项目</h2>
            <span>{projects.length} 个</span>
          </div>
          {projects.length === 0 ? (
            <div className="empty-list">
              <p>还没有项目。</p>
              <p>
                从左侧导入一个本地目录：只读、按选择范围读取、自动排除凭据与越界符号链接。
              </p>
            </div>
          ) : (
            <div className="project-grid">
              {projects.map((project) => (
                <button
                  className="project-card"
                  key={project.id}
                  onClick={() => onOpen(project)}
                >
                  <span className="project-card-name">{project.name}</span>
                  <span className="project-card-path mono" title={project.root_path}>
                    {compactPath(project.root_path)}
                  </span>
                  <span className="project-card-foot">
                    <span>{project.file_count} 个文件</span>
                    <span className="mono">
                      {project.snapshot_digest?.slice(0, 12) ?? "未扫描"}
                    </span>
                    {project.analysis_error && (
                      <span className="badge badge-error">分析失败</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <aside className="home-aside">
          <h2>当前状态</h2>
          <dl className="stat-list">
            <div>
              <dt>模型配置</dt>
              <dd>{models.length ? `${models.length} 个` : "未配置"}</dd>
            </div>
            <div>
              <dt>确定性替身</dt>
              <dd>{models.some((item) => item.provider === "stub") ? "可用" : "未添加"}</dd>
            </div>
            <div>
              <dt>题目生成</dt>
              <dd>阶段 2</dd>
            </div>
          </dl>
          <p className="aside-note">
            阶段 1 只建立项目工作区与会话理解。不会生成题目，也不会修改你的项目文件。
          </p>
        </aside>
      </section>
    </div>
  );
}
