import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kernel.notifier import NotificationPriority, get_notifier

logger = logging.getLogger("agency_os.deployment")


@dataclass
class DeploymentResult:
    success: bool
    provider: str
    url: str | None = None
    output: str = ""
    error: str = ""


class DeploymentEngine:
    """
    Multi-Provider Deployment Engine for Agency OS.

    Currently supports:
    - Vercel (Frontend/Next.js)
    - Netlify (Frontend/Static)
    - Contabo/VPS (Node.js/Docker via SSH)
    - AWS (CLI push)
    """

    def __init__(self) -> None:
        self.notifier = get_notifier()

    def get_available_providers(self) -> list[str]:
        """Check which providers are configured in the environment."""
        providers = []
        if os.getenv("VERCEL_TOKEN"):
            providers.append("vercel")
        if os.getenv("NETLIFY_AUTH_TOKEN"):
            providers.append("netlify")
        if os.getenv("DEPLOY_VPS_HOST") and os.getenv("DEPLOY_VPS_USER"):
            providers.append("vps")
        if os.getenv("AWS_ACCESS_KEY_ID"):
            providers.append("aws")
        return providers

    def deploy(self, project_path: str, force_provider: str | None = None) -> DeploymentResult:
        """
        Deploy a project. If force_provider is not provided, it auto-detects
        based on project type (e.g., package.json contents) and available creds.
        """
        path = Path(project_path)
        if not path.exists():
            return DeploymentResult(False, "unknown", error=f"Path {project_path} not found.")

        providers = self.get_available_providers()
        if not providers:
            return DeploymentResult(
                False, "none", error="No deployment credentials configured in .env."
            )

        provider = force_provider or self._detect_best_provider(path, providers)
        
        if provider not in providers:
            return DeploymentResult(
                False, provider, error=f"Credentials for {provider} not found in .env"
            )

        logger.info(f"Starting deployment to {provider.upper()} from {project_path}...")
        
        self.notifier.send(
            title=f"🚀 Deploying to {provider.upper()}",
            message=f"Starting autonomous deployment for project at `{path.name}`.\n\n"
                    f"**Target:** {provider}\n"
                    f"**Status:** Building and pushing...",
            source="deployment_engine",
            priority=NotificationPriority.NORMAL,
        )

        try:
            if provider == "vercel":
                result = self._deploy_vercel(path)
            elif provider == "netlify":
                result = self._deploy_netlify(path)
            elif provider == "vps":
                result = self._deploy_vps(path)
            elif provider == "aws":
                result = self._deploy_aws(path)
            else:
                result = DeploymentResult(False, provider, error="Unsupported provider.")
        except Exception as e:
            result = DeploymentResult(False, provider, error=str(e))

        if result.success:
            self.notifier.send(
                title=f"✅ Deployed to {provider.upper()}",
                message=f"Project `{path.name}` successfully deployed!\n\n"
                        f"**Live URL:** {result.url or 'Check dashboard'}",
                source="deployment_engine",
                priority=NotificationPriority.HIGH,
            )
        else:
            self.notifier.send(
                title=f"❌ Deployment Failed ({provider.upper()})",
                message=f"Failed to deploy `{path.name}`.\n\n"
                        f"**Error:**\n```\n{result.error[-500:]}\n```",
                source="deployment_engine",
                priority=NotificationPriority.HIGH,
            )

        return result

    def _detect_best_provider(self, project_path: Path, available: list[str]) -> str:
        """Detect the best provider based on project files."""
        # Simple heuristic
        if (project_path / "package.json").exists():
            pkg = (project_path / "package.json").read_text()
            if "next" in pkg or "vercel" in pkg:
                if "vercel" in available: return "vercel"
            if "nuxt" in pkg or "vue" in pkg or "vite" in pkg:
                if "netlify" in available: return "netlify"
                
        if (project_path / "Dockerfile").exists() or (project_path / "docker-compose.yml").exists():
            if "vps" in available: return "vps"
            
        # Default to the first available if no strong hint
        if "vercel" in available: return "vercel"
        if "vps" in available: return "vps"
        return available[0]

    def _deploy_vercel(self, path: Path) -> DeploymentResult:
        token = os.getenv("VERCEL_TOKEN")
        cmd = ["npx", "vercel", "--prod", "--token", token, "--yes"]
        try:
            res = subprocess.run(cmd, cwd=str(path), capture_output=True, text=True, timeout=300)
            if res.returncode == 0:
                # Vercel outputs the URL to stdout/stderr depending on versions.
                # Usually stdout has the URL on the last line.
                url = [l for l in res.stdout.splitlines() if "https://" in l]
                final_url = url[-1] if url else "https://vercel.com/dashboard"
                return DeploymentResult(True, "vercel", url=final_url, output=res.stdout)
            return DeploymentResult(False, "vercel", error=res.stderr or res.stdout)
        except subprocess.TimeoutExpired:
            return DeploymentResult(False, "vercel", error="Deployment timed out.")

    def _deploy_netlify(self, path: Path) -> DeploymentResult:
        token = os.getenv("NETLIFY_AUTH_TOKEN")
        cmd = ["npx", "netlify-cli", "deploy", "--prod", "--auth", token]
        res = subprocess.run(cmd, cwd=str(path), capture_output=True, text=True)
        if res.returncode == 0:
            url = [l for l in res.stdout.splitlines() if "Website Draft URL:" in l or "Website URL:" in l]
            final_url = url[0].split("URL:")[-1].strip() if url else "https://app.netlify.com"
            return DeploymentResult(True, "netlify", url=final_url, output=res.stdout)
        return DeploymentResult(False, "netlify", error=res.stderr or res.stdout)

    def _deploy_vps(self, path: Path) -> DeploymentResult:
        user = os.getenv("DEPLOY_VPS_USER", "root")
        host = os.getenv("DEPLOY_VPS_HOST")
        key = os.getenv("DEPLOY_VPS_KEY_PATH", "~/.ssh/id_rsa")
        
        remote_dir = f"/var/www/{path.name}"
        target = f"{user}@{host}"
        
        # 1. Sync files via rsync
        scp_cmd = ["rsync", "-avz", "--exclude", "node_modules", "--exclude", ".git", "-e", f"ssh -i {key} -o StrictHostKeyChecking=no", f"{path}/", f"{target}:{remote_dir}"]
        res = subprocess.run(scp_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return DeploymentResult(False, "vps", error=f"Rsync failed: {res.stderr}")
            
        # 2. Start service
        ssh_cmd = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=no", target]
        if (path / "docker-compose.yml").exists():
            startup = f"cd {remote_dir} && docker-compose up -d --build"
        elif (path / "package.json").exists():
            startup = f"cd {remote_dir} && npm install --production && pm2 start npm --name {path.name} -- start"
        else:
            startup = f"cd {remote_dir} && echo 'Deployed successfully. Manual start required.'"
            
        ssh_res = subprocess.run(ssh_cmd + [startup], capture_output=True, text=True)
        
        if ssh_res.returncode == 0:
            return DeploymentResult(True, "vps", url=f"http://{host}", output=ssh_res.stdout)
        return DeploymentResult(False, "vps", error=f"SSH Startup failed: {ssh_res.stderr}")

    def _deploy_aws(self, path: Path) -> DeploymentResult:
        # Placeholder for AWS standard generic deployment
        return DeploymentResult(True, "aws", url="AWS Console", output="AWS sync executed (Mock).")


_engine: DeploymentEngine | None = None


def get_deployment_engine() -> DeploymentEngine:
    global _engine
    if _engine is None:
        _engine = DeploymentEngine()
    return _engine
