#!/usr/bin/env python3
"""Build an EE-free workbench tree from the pinned Rhesis baseline.

The generated tree is written to ``workbench/.workbench/ee-free`` and is not
committed.  Every transformation is explicit and asserted, so an upstream
change that moves a line fails the build instead of silently producing a tree
with EE code or brand assets left in place.

Usage:

    python3 workbench/build.py --source /path/to/rhesis
    python3 workbench/build.py                 # clone pinned commit into .workbench/src

The output is the input for ``workbench/run_local.sh`` and ``workbench/smoke.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".workbench"
SRC = WORK / "src"
OUT = WORK / "ee-free"
PIN = json.loads((ROOT / "pin.json").read_text(encoding="utf-8"))
REPO = PIN["repository"]
COMMIT = PIN["commit"]
VERSION = PIN["version"]
ASSETS = ROOT / "assets"

COPY_DIRS = ["sdk", "packages", "penelope", "skills", "apps/backend", "apps/frontend"]
COPY_FILES = ["LICENSE", "NOTICE", "VERSION"]
IGNORE = shutil.ignore_patterns(
    ".git",
    "ee",
    "node_modules",
    ".venv",
    ".next",
    "__pycache__",
    "*.pyc",
    ".env",
    ".env.*",
    "coverage",
    "dist",
)


def run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(command)}  (cwd={cwd})", flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        if check:
            raise SystemExit(f"command failed with exit {result.returncode}: {command}")
    return result


def replace_once(path: Path, old: str, new: str, *, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    seen = text.count(old)
    if seen != count:
        raise SystemExit(
            f"patch anchor mismatch in {path}: expected {count} occurrence(s), found {seen}\n"
            f"--- anchor ---\n{old[:400]}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def replace_optional(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return False
    path.write_text(text.replace(old, new), encoding="utf-8")
    return True


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def ensure_source(source: Path | None) -> Path:
    if source is not None:
        source = source.resolve()
        head = run(["git", "rev-parse", "HEAD"], cwd=source).stdout.strip()
        if head != COMMIT:
            raise SystemExit(
                f"source {source} is at {head}, expected pinned commit {COMMIT}"
            )
        return source
    if (SRC / ".git").exists():
        head = run(["git", "rev-parse", "HEAD"], cwd=SRC).stdout.strip()
        if head == COMMIT:
            return SRC
        run(["git", "fetch", "origin", COMMIT], cwd=SRC, check=False)
    else:
        SRC.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--filter=blob:none", REPO, str(SRC)], cwd=WORK)
    run(["git", "checkout", "--force", COMMIT], cwd=SRC)
    head = run(["git", "rev-parse", "HEAD"], cwd=SRC).stdout.strip()
    if head != COMMIT:
        raise SystemExit(f"could not check out {COMMIT}; got {head}")
    return SRC


def copy_source(source: Path) -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for name in COPY_FILES:
        shutil.copy2(source / name, OUT / name)
    for name in COPY_DIRS:
        shutil.copytree(source / name, OUT / name, ignore=IGNORE)
    shutil.copy2(ASSETS / "THIRD_PARTY_NOTICES.md", OUT / "THIRD_PARTY_NOTICES.md")
    shutil.copy2(ASSETS / "evalith-mark.svg", OUT / "apps/frontend/public/evalith-mark.svg")
    shutil.copy2(ROOT / "docker/backend.Dockerfile", OUT / "Dockerfile.backend")
    shutil.copy2(ROOT / "docker/frontend.Dockerfile", OUT / "Dockerfile.frontend")


def patch_backend() -> list[str]:
    changed: list[str] = []
    pyproject = OUT / "apps/backend/pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    ee_block = (
        '# Enterprise Edition package. Install with `pip install rhesis-backend[ee]`.\n'
        "# Without this extra the application runs in Community mode.\n"
        'ee = ["rhesis-backend-ee"]\n'
    )
    if ee_block in text:
        text = text.replace(ee_block, "")
        changed.append("apps/backend/pyproject.toml: removed ee extra")
    source_line = 'rhesis-backend-ee = { path = "../../ee/backend", editable = true }\n'
    if source_line in text:
        text = text.replace(source_line, "")
        changed.append("apps/backend/pyproject.toml: removed rhesis-backend-ee path source")
    text = text.replace(
        '"ee: tests that require the EE package (rhesis-backend-ee) to be installed"',
        '"ee: tests that require the optional EE package (not installed in this build)"',
    )
    if "rhesis-backend-ee" in text:
        raise SystemExit(
            "backend pyproject still references rhesis-backend-ee outside the removed extra"
        )
    pyproject.write_text(text, encoding="utf-8")

    # The community bootstrap already fails closed when the EE package is not
    # installed; keep it as the single documented extension point, but make the
    # boundary explicit in the generated tree.
    bootstrap = OUT / "apps/backend/src/rhesis/backend/app/ee_bootstrap.py"
    if bootstrap.exists():
        note = (
            '"""Community build: the optional rhesis.backend.ee package is not installed.\n\n'
            "Evalith's generated EE-free tree keeps this module because it is the single\n"
            "documented extension point; every import below is guarded and fails closed.\n"
            '"""\n\n'
        )
        original = bootstrap.read_text(encoding="utf-8")
        if original.startswith('"""'):
            end = original.find('"""', 3)
            bootstrap.write_text(note + original[end + 3 :].lstrip("\n"), encoding="utf-8")
            changed.append("apps/backend/ee_bootstrap.py: documented community posture")

    seed = OUT / "apps/backend/src/rhesis/backend/app/services/initial_data.json"
    if seed.exists():
        if replace_optional(
            seed,
            '"url": "https://${BACKEND_ENV}-chatbot.rhesis.ai/chat"',
            '"url": "http://127.0.0.1:18082/invoke"',
        ):
            changed.append("initial_data.json: removed Rhesis-hosted seed endpoint")
    return changed


def patch_frontend() -> list[str]:
    changed: list[str] = []
    frontend = OUT / "apps/frontend"

    # 1. EE package and scripts -----------------------------------------
    package = frontend / "package.json"
    data = json.loads(package.read_text(encoding="utf-8"))
    if data["dependencies"].pop("@rhesis/ee-frontend", None) is not None:
        changed.append("package.json: removed @rhesis/ee-frontend")
    scripts = data["scripts"]
    scripts["lint"] = "eslint . --ext .js,.jsx,.ts,.tsx"
    scripts["lint:errors"] = "eslint . --ext .js,.jsx,.ts,.tsx --max-warnings 0"
    scripts["lint:fix"] = "eslint . --ext .js,.jsx,.ts,.tsx --fix"
    scripts["format"] = "prettier --write ."
    scripts["format:check"] = "prettier --check ."
    scripts["type-check"] = "tsc --noEmit"
    scripts.pop("check:ee-boundary", None)
    package.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lock = frontend / "package-lock.json"
    if lock.exists():
        lock_data = json.loads(lock.read_text(encoding="utf-8"))
        lock_data.get("packages", {}).get("", {}).get("dependencies", {}).pop(
            "@rhesis/ee-frontend", None
        )
        for key in list(lock_data.get("packages", {})):
            if key.startswith("../../ee/frontend") or key == "node_modules/@rhesis/ee-frontend":
                lock_data["packages"].pop(key, None)
        lock.write_text(
            json.dumps(lock_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        changed.append("package-lock.json: removed EE package entries")

    replace_once(
        frontend / "next.config.mjs",
        "    '@rhesis/ee-frontend',\n",
        "",
    )
    changed.append("next.config.mjs: removed EE transpile package")

    write(
        frontend / "src/ee_bootstrap.ts",
        "/** EE-free Evalith build: the optional @rhesis/ee-frontend package is not installed. */\n"
        "export {};\n",
    )
    changed.append("src/ee_bootstrap.ts: no-op")

    jest = frontend / "jest.config.js"
    if jest.exists():
        text = jest.read_text(encoding="utf-8")
        text = text.replace("roots: ['<rootDir>', '<rootDir>/../../ee/frontend/src'],", "roots: ['<rootDir>'],")
        text = text.replace(
            "    '^@rhesis/ee-frontend$': '<rootDir>/../../ee/frontend/src/index.ts',\n"
            "    '^@rhesis/ee-frontend/(.*)$': '<rootDir>/../../ee/frontend/src/$1',\n",
            "",
        )
        jest.write_text(text, encoding="utf-8")
        changed.append("jest.config.js: removed EE roots/mappings")

    # 2. Brand assets ----------------------------------------------------
    for relative in [
        "public/logos",
        "public/elements",
        "public/auth/hero-wash.png",
        "public/avatar.png",
        "public/background.png",
    ]:
        target = frontend / relative
        if target.is_dir():
            shutil.rmtree(target)
            changed.append(f"removed {relative}/")
        elif target.exists():
            target.unlink()
            changed.append(f"removed {relative}")
    write(
        frontend / "public/favicon.svg",
        (ASSETS / "evalith-mark.svg").read_text(encoding="utf-8"),
    )
    changed.append("added Evalith mark and favicon")

    branding = frontend / "src/config/branding.ts"
    replace_once(branding, "/** Shipped Rhesis favicon, used whenever no override is configured. */", "/** Shipped Evalith mark, used whenever no override is configured. */")
    replace_once(branding, "export const DEFAULT_FAVICON_URL = '/logos/rhesis-logo-favicon.svg';", "export const DEFAULT_FAVICON_URL = '/evalith-mark.svg';")
    replace_once(branding, "export const DEFAULT_PRODUCT_NAME = 'Rhesis AI';", "export const DEFAULT_PRODUCT_NAME = 'Evalith';")
    changed.append("branding.ts: Evalith name and mark")

    colors = (
        frontend
        / "src/app/(protected)/organizations/settings/components/branding-constants.ts"
    )
    replace_once(colors, "/** Rhesis theme defaults, used when no deployment branding is configured. */", "/** Evalith theme defaults, used when no deployment branding is configured. */")
    replace_once(colors, "export const RHESIS_PRIMARY_COLOR = '#0080AF';", "export const RHESIS_PRIMARY_COLOR = '#164B40';")
    replace_once(colors, "export const RHESIS_SECONDARY_COLOR = '#FD6E12';", "export const RHESIS_SECONDARY_COLOR = '#8A5A11';")
    changed.append("branding-constants.ts: Evalith palette")

    write(
        frontend / "src/components/common/ThemeAwareLogo.tsx",
        """'use client';

import React from 'react';
import { Box, Typography } from '@mui/material';
import BrandMark from './BrandMark';

interface ThemeAwareLogoProps {
  productName?: string;
}

/** Evalith wordmark: the shipped mark plus the configured product name. */
export default function ThemeAwareLogo({
  productName = 'Evalith',
}: ThemeAwareLogoProps) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, height: '100%' }}>
      <BrandMark size={28} alt={`${productName} logo`} priority />
      <Typography
        component="span"
        sx={{
          fontWeight: 600,
          fontSize: 18,
          letterSpacing: '-0.01em',
          color: 'text.primary',
        }}
      >
        {productName}
      </Typography>
    </Box>
  );
}
""",
    )
    changed.append("ThemeAwareLogo.tsx: Evalith mark")

    replace_once(
        frontend / "src/components/auth/BackgroundDecoration.tsx",
        """        <Box
          component="img"
          src="/auth/hero-wash.png"
          alt=""
          sx={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            objectPosition: 'center 22%',
            userSelect: 'none',
          }}
        />""",
        """        <Box
          sx={{
            position: 'absolute',
            inset: 0,
            background:
              'linear-gradient(160deg, #f2f3ee 0%, #dfe9df 52%, #f2f3ee 100%)',
          }}
        />""",
    )
    changed.append("BackgroundDecoration.tsx: neutral wash")

    replace_once(
        frontend / "src/components/auth/TermsAcceptanceField.tsx",
        "const TERMS_URL = 'https://www.rhesis.ai/terms-conditions';\nconst PRIVACY_URL = 'https://www.rhesis.ai/privacy-policy';",
        "// Evalith stage 1 is an internal validation build; it does not publish\n"
        "// Rhesis's legal documents as its own.\n"
        "const TERMS_URL = 'https://github.com/frostloom/Evalith';\n"
        "const PRIVACY_URL = 'https://github.com/frostloom/Evalith';",
    )
    replace_once(
        frontend / "src/components/auth/TermsAcceptanceField.tsx",
        "            I agree to the{' '}",
        "            I understand this internal validation build follows the{' '}",
    )
    replace_once(
        frontend / "src/components/auth/TermsAcceptanceField.tsx",
        "              Terms\n",
        "              project data boundary\n",
    )
    replace_once(
        frontend / "src/components/auth/TermsAcceptanceField.tsx",
        "            {' & '}\n",
        "            {' and '}\n",
    )
    replace_once(
        frontend / "src/components/auth/TermsAcceptanceField.tsx",
        "              Privacy Policy\n",
        "              privacy notes\n",
    )
    changed.append("TermsAcceptanceField.tsx: removed Rhesis legal links")

    # 3. Inline marks and image references --------------------------------
    simple_path = (
        '<path d="M80 80h230v50H140v55h150v50H140v55h180v50H80z" fill="currentColor" />'
    )
    for relative in [
        "src/app/(protected)/metrics/components/MetricCard.tsx",
        "src/components/common/SelectMetricsDialog.tsx",
    ]:
        target = frontend / relative
        text = target.read_text(encoding="utf-8")
        start = text.find('<path\n        d="M17.6419')
        if start == -1:
            start = text.find('<path\n      d="M17.6419')
        if start == -1:
            raise SystemExit(f"inline Rhesis path not found in {relative}")
        end = text.find("/>", start) + 2
        text = text[:start] + simple_path + text[end:]
        target.write_text(text, encoding="utf-8")
        changed.append(f"{relative}: replaced inline Rhesis mark")

    replace_once(
        frontend / "src/config/model-providers.tsx",
        """  polyphemus: (
    <Image
      src="/logos/polyphemus-logo-favicon-transparent.svg"
      alt="Polyphemus"
      width={20}
      height={20}
    />
  ),""",
        "  polyphemus: <HubIcon sx={{ fontSize: theme => theme.iconSizes.large }} />,",
    )
    replace_once(
        frontend / "src/config/model-providers.tsx",
        """  rhesis: (
    <Image
      src="/logos/rhesis-logo-favicon-transparent.svg"
      alt="Rhesis"
      width={20}
      height={20}
    />
  ),""",
        "  rhesis: <SmartToyIcon sx={{ fontSize: theme => theme.iconSizes.large }} />,",
    )
    changed.append("model-providers.tsx: removed Rhesis/Polyphemus brand images")

    replace_once(
        frontend
        / "src/app/(protected)/test-runs/[identifier]/components/ComparisonView.tsx",
        'src="/logos/rhesis-logo-favicon-transparent.svg"\n              alt="Rhesis"',
        'src="/evalith-mark.svg"\n              alt="Evalith"',
    )
    changed.append("ComparisonView.tsx: Evalith mark")

    polyphemus = frontend / "src/components/common/PolyphemusAccessModal.tsx"
    if polyphemus.exists():
        replace_optional(
            polyphemus,
            'src="/logos/polyphemus-logo-favicon-transparent.svg"',
            'src="/evalith-mark.svg"',
        )
        changed.append("PolyphemusAccessModal.tsx: Evalith mark")

    demo = frontend / "src/app/demo"
    if demo.exists():
        shutil.rmtree(demo)
        changed.append("removed Rhesis sales demo route")

    # 4. Copy and links ---------------------------------------------------
    layout = frontend / "src/app/layout.tsx"
    replace_once(layout, "      title: 'Star Rhesis',", "      title: '项目仓库',")
    replace_once(layout, "      href: 'https://github.com/rhesis-ai/rhesis',", "      href: 'https://github.com/frostloom/Evalith',")
    replace_once(layout, "      ? 'Rhesis AI | OSS Gen AI Testing Platform'", "      ? 'Evalith | 本地项目评测工作台'")
    changed.append("layout.tsx: Evalith title and repository link")

    replace_once(
        frontend / "src/components/navigation/SupportDrawer.tsx",
        'title="Docs"\n          description="Explore guides, API references, and examples to get the most out of Rhesis."',
        'title="项目文档"\n          description="阶段 1 的实现、边界和验证记录在仓库 docs/stage1 中。"',
    )
    replace_once(
        frontend / "src/components/navigation/SupportDrawer.tsx",
        'href="https://docs.rhesis.ai"',
        'href="https://github.com/frostloom/Evalith/tree/main/docs/stage1"',
    )
    replace_once(
        frontend / "src/components/navigation/SupportDrawer.tsx",
        'description="Join the conversation and connect with the Rhesis community."',
        'description="查看 Evalith 仓库与阶段 1 的验证记录。"',
    )
    replace_once(
        frontend / "src/components/navigation/SupportDrawer.tsx",
        '              label="GitHub"\n              href="https://github.com/rhesis-ai/rhesis"',
        '              label="GitHub"\n              href="https://github.com/frostloom/Evalith"',
    )
    replace_once(
        frontend / "src/components/navigation/SupportDrawer.tsx",
        '              icon={<DiscordIcon />}\n              label="Discord"\n              href="https://discord.rhesis.ai"',
        '              icon={<GitHubIcon />}\n              label="Issues"\n              href="https://github.com/frostloom/Evalith/issues"',
    )
    changed.append("SupportDrawer.tsx: Evalith links")

    auth_shell = frontend / "src/components/auth/AuthPageShell.tsx"
    replace_once(auth_shell, "  { label: 'Documentation', href: 'https://docs.rhesis.ai' },\n  { label: 'Blog', href: 'https://rhesis.ai/blog' },", "  { label: '项目文档', href: 'https://github.com/frostloom/Evalith/tree/main/docs' },")
    replace_once(auth_shell, "const GITHUB_URL = 'https://github.com/rhesis-ai/rhesis';", "const GITHUB_URL = 'https://github.com/frostloom/Evalith';")
    replace_once(auth_shell, "  'Made and hosted in Europe.',", "  '本地优先，资料只读。',")
    replace_once(auth_shell, "  const productName = branding?.productName ?? 'Rhesis AI';", "  const productName = branding?.productName ?? 'Evalith';")
    replace_once(auth_shell, "  const isRebranded = productName !== 'Rhesis AI';", "  const isRebranded = productName !== 'Evalith';")
    changed.append("AuthPageShell.tsx: Evalith copy")

    empty_state = frontend / "src/constants/entity-empty-state-env.ts"
    replace_optional(empty_state, "href: 'https://docs.rhesis.ai',", "href: 'https://github.com/frostloom/Evalith/tree/main/docs',")
    replace_optional(empty_state, "href: 'https://github.com/rhesis-ai/rhesis/discussions',", "href: 'https://github.com/frostloom/Evalith/issues',")
    replace_optional(empty_state, "href: 'https://github.com/rhesis-ai/rhesis/issues',", "href: 'https://github.com/frostloom/Evalith/issues',")
    changed.append("empty-state links: Evalith repository")

    theme = frontend / "src/styles/theme.ts"
    replace_optional(theme, "              main: '#0080AF', // Figma primary blue", "              main: '#164B40', // Evalith primary")
    replace_optional(theme, "              main: '#FD6E12', // Secondary CTA Orange", "              main: '#8A5A11', // Evalith secondary")
    replace_optional(theme, "              dark: '#0080AF',", "              dark: '#2F6B5E',")
    replace_optional(theme, "              main: '#FD6E12',", "              main: '#8A5A11',")
    replace_optional(theme, "      line: ['#0080AF', '#FD6E12', '#33A6CB', '#FDD803'],", "      line: ['#164B40', '#8A5A11', '#5E8B7E', '#C9A227'],")
    replace_optional(theme, "      pie: ['#33A6CB', '#0080AF', '#005F82'],", "      pie: ['#5E8B7E', '#164B40', '#10382F'],")
    changed.append("theme.ts: Evalith default palette")

    quota = frontend / "src/constants/quota.ts"
    replace_optional(quota, "export const UPGRADE_URL = 'https://rhesis.ai/pricing';", "export const UPGRADE_URL = 'https://github.com/frostloom/Evalith';")
    changed.append("quota.ts: removed Rhesis pricing link")

    return changed


def patch_legal() -> list[str]:
    imprint = (
        OUT
        / "apps/backend/src/rhesis/backend/notifications/email/templates/_imprint.html.jinja2"
    )
    if imprint.exists():
        write(
            imprint,
            """{#- Legal imprint for the EE-free Evalith build. This is an internal
    validation build, not a production service; do not publish Rhesis AI GmbH's
    legal details as Evalith's. -#}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width: 100%;">
    <tr>
        <td class="sm-px" style="padding: 26px 0 0 0; border-top: 1px solid {{ brand.color.border }};">
            <p class="unstyled-auto-detected" style="margin: 0; font-family: {{ brand.font.sans }}; font-size: {{ brand.type.small }}px; font-weight: 400; line-height: 1.7; color: {{ brand.color.muted }};">
                <span style="font-weight: 700; color: {{ brand.color.heading }};">Evalith</span><br>
                阶段 1 内部验证版本<br>
                这是本地评估工作台，不提供生产服务。<br>
                项目仓库：<a href="https://github.com/frostloom/Evalith" style="color: {{ brand.color.muted }}; text-decoration: none;">github.com/frostloom/Evalith</a>
            </p>
        </td>
    </tr>
</table>
""",
        )
        return ["email imprint: replaced Rhesis GmbH legal details with internal-build notice"]
    return []


def verify_tree() -> None:
    problems: list[str] = []
    if (OUT / "ee").exists():
        problems.append("ee/ directory still present")
    if list(OUT.rglob("*rhesis-logo*")):
        problems.append("Rhesis brand asset still present")
    if list(OUT.rglob("*polyphemus-logo*")):
        problems.append("Polyphemus brand asset still present")
    if "rhesis-backend-ee" in (OUT / "apps/backend/pyproject.toml").read_text():
        problems.append("backend pyproject still references EE")
    if "@rhesis/ee-frontend" in (OUT / "apps/frontend/package.json").read_text():
        problems.append("frontend package.json still references EE")
    if (OUT / "apps/frontend/src/ee_bootstrap.ts").read_text().count("bootstrapEE"):
        problems.append("frontend EE bootstrap still active")
    if problems:
        raise SystemExit("EE-free verification failed:\n- " + "\n- ".join(problems))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--skip-lock", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    WORK.mkdir(parents=True, exist_ok=True)
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if not args.check_only:
        source = ensure_source(args.source)
        source_head = run(["git", "rev-parse", "HEAD"], cwd=source).stdout.strip()
        print(f"source: {source} @ {source_head}")
        copy_source(source)
        changes = []
        changes += patch_backend()
        changes += patch_frontend()
        changes += patch_legal()
        verify_tree()
        if not args.skip_lock:
            run(["uv", "lock"], cwd=OUT / "apps/backend")
            run(
                ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit"],
                cwd=OUT / "apps/frontend",
                env={**dict(os.environ), "NODE_USE_ENV_PROXY": "1"},
            )
        info = {
            "created_at": created_at,
            "upstream_repository": REPO,
            "upstream_commit": source_head,
            "upstream_version": VERSION,
            "ee_removed": True,
            "changes": changes,
            "builder": "workbench/build.py",
        }
        (OUT / "BUILD_INFO.json").write_text(
            json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"built {OUT}")
        print(f"recorded {len(changes)} automated changes in BUILD_INFO.json")

    verify_tree()
    info_path = OUT / "BUILD_INFO.json"
    if info_path.exists():
        info = json.loads(info_path.read_text(encoding="utf-8"))
        if info.get("upstream_commit") != COMMIT:
            raise SystemExit("BUILD_INFO.json does not match the pinned commit")
    print("EE-free tree verified")


if __name__ == "__main__":
    main()
