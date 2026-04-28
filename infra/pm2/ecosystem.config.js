const path = require("path");

const stage = process.env.DEPLOY_STAGE;

if (!["develop", "main"].includes(stage)) {
  throw new Error(
    "DEPLOY_STAGE must be one of: develop, main"
  );
}

const repoRoot = process.env.REPO_ROOT || path.resolve(__dirname, "../..");
const pythonBin = process.env.PYTHON_BIN || path.join(repoRoot, ".venv", "bin", "python");
const isDevelop = stage === "develop";
const suffix = isDevelop ? "dev" : "prod";
const apiPort = process.env.API_PORT || (isDevelop ? "8081" : "8080");
const authApiPort = process.env.AUTH_API_PORT || (isDevelop ? "3091" : "3090");
const nodeEnv = isDevelop ? "development" : "production";

module.exports = {
  apps: [
    {
      name: `api-${suffix}`,
      cwd: repoRoot,
      script: "apps/api/start.py",
      interpreter: pythonBin,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        PORT: apiPort,
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      name: `collector-${suffix}`,
      cwd: path.join(repoRoot, "apps", "collector"),
      script: "main.py",
      interpreter: pythonBin,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      name: `signals-${suffix}`,
      cwd: path.join(repoRoot, "apps", "signals"),
      script: "main.py",
      interpreter: pythonBin,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      name: `monitoring-${suffix}`,
      cwd: path.join(repoRoot, "apps", "monitoring"),
      script: "main.py",
      interpreter: pythonBin,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      name: `auth-api-${suffix}`,
      cwd: path.join(repoRoot, "apps", "auth_api"),
      script: "dist/main.js",
      interpreter: "node",
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        NODE_ENV: nodeEnv,
        PORT: authApiPort,
      },
    },
    {
      name: `bot_automatico-${suffix}`,
      cwd: path.join(repoRoot, "apps", "bot_automatico"),
      script: "main.js",
      interpreter: "node",
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        NODE_ENV: nodeEnv,
      },
    },
  ],
};
