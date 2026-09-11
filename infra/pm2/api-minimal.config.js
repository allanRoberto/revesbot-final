const path = require("path");
const fs = require("fs");

const currentRoot = process.env.REVESBOT_API_CURRENT || "/var/www/revesbot/api-current";
const python = path.join(currentRoot, ".venv", "bin", "python");
const apiPort = process.env.API_PORT || "8082";
const releaseId =
  process.env.BEHAVIOR_LAB_RELEASE_ID || path.basename(fs.realpathSync(currentRoot));
const behaviorLabConfig = path.join(
  currentRoot,
  "apps",
  "behavior_lab",
  "config",
  "default_v1.json",
);
const behaviorLabContract = Object.freeze({
  roulette_id: "pragmatic-auto-roulette",
  context_size: 500,
  signal_horizon: 10,
  redis_namespace: "behavior_lab:v1",
});
const behaviorLabSettings = require(behaviorLabConfig);

for (const [field, expected] of Object.entries(behaviorLabContract)) {
  if (behaviorLabSettings[field] !== expected) {
    throw new Error(`Behavior Lab config mismatch for ${field}`);
  }
}

module.exports = {
  apps: [
    {
      name: "revesbot-api",
      cwd: currentRoot,
      script: "apps/api/start_minimal.py",
      interpreter: python,
      instances: 1,
      autorestart: true,
      exp_backoff_restart_delay: 1000,
      restart_delay: 2000,
      kill_timeout: 10000,
      max_memory_restart: "700M",
      time: true,
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONDONTWRITEBYTECODE: "1",
        API_HOST: "127.0.0.1",
        API_PORT: apiPort,
        API_WORKERS: process.env.API_WORKERS || "2",
        MONGO_URL: process.env.MONGO_URL,
        MONGO_DATABASE: process.env.MONGO_DATABASE || "roleta_db",
        PIXGO_MONGO_URL: process.env.PIXGO_MONGO_URL,
        PIXGO_MONGO_DATABASE: process.env.PIXGO_MONGO_DATABASE || "roleta_db",
        REDIS_CONNECT: process.env.REDIS_CONNECT,
        PIXGO_API_KEY: process.env.PIXGO_API_KEY,
        PIXGO_WEBHOOK_SECRET: process.env.PIXGO_WEBHOOK_SECRET,
        PIXGO_BASE_URL: process.env.PIXGO_BASE_URL,
        BEHAVIOR_LAB_RELEASE_ID: releaseId,
        BEHAVIOR_LAB_HEARTBEAT_MAX_AGE_SECONDS:
          process.env.BEHAVIOR_LAB_HEARTBEAT_MAX_AGE_SECONDS || "90",
      },
    },
    {
      name: "revesbot-behavior-lab",
      cwd: currentRoot,
      script: "apps/behavior_lab/__main__.py",
      args: ["worker"],
      interpreter: python,
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      exp_backoff_restart_delay: 1000,
      restart_delay: 2000,
      min_uptime: "10s",
      max_restarts: 10,
      kill_timeout: 15000,
      treekill: true,
      max_memory_restart: "512M",
      time: true,
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONDONTWRITEBYTECODE: "1",
        BEHAVIOR_LAB_CONFIG: behaviorLabConfig,
        BEHAVIOR_LAB_API_BASE_URL: `http://127.0.0.1:${apiPort}`,
        BEHAVIOR_LAB_WS_URL: `ws://127.0.0.1:${apiPort}/ws?slug=${behaviorLabContract.roulette_id}`,
        BEHAVIOR_LAB_REDIS_URL:
          process.env.REDIS_CONNECT || "redis://127.0.0.1:6380/0",
        BEHAVIOR_LAB_RECONCILE_INTERVAL_SECONDS:
          process.env.BEHAVIOR_LAB_RECONCILE_INTERVAL_SECONDS || "30",
        BEHAVIOR_LAB_LOG_LEVEL: process.env.BEHAVIOR_LAB_LOG_LEVEL || "INFO",
        BEHAVIOR_LAB_RELEASE_ID: releaseId,
      },
    },
  ],
};
