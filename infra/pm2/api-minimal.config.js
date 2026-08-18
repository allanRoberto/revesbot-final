const path = require("path");

const currentRoot = process.env.REVESBOT_API_CURRENT || "/var/www/revesbot/api-current";

module.exports = {
  apps: [
    {
      name: "revesbot-api",
      cwd: currentRoot,
      script: "apps/api/start_minimal.py",
      interpreter: path.join(currentRoot, ".venv", "bin", "python"),
      instances: 1,
      autorestart: true,
      exp_backoff_restart_delay: 1000,
      restart_delay: 2000,
      kill_timeout: 10000,
      max_memory_restart: "700M",
      time: true,
      env: {
        PYTHONUNBUFFERED: "1",
        API_HOST: "127.0.0.1",
        API_PORT: process.env.API_PORT || "8082",
        API_WORKERS: process.env.API_WORKERS || "2",
        MONGO_URL: process.env.MONGO_URL,
        MONGO_DATABASE: process.env.MONGO_DATABASE || "roleta_db",
        PIXGO_MONGO_URL: process.env.PIXGO_MONGO_URL,
        PIXGO_MONGO_DATABASE: process.env.PIXGO_MONGO_DATABASE || "roleta_db",
        REDIS_CONNECT: process.env.REDIS_CONNECT,
        PIXGO_API_KEY: process.env.PIXGO_API_KEY,
        PIXGO_WEBHOOK_SECRET: process.env.PIXGO_WEBHOOK_SECRET,
        PIXGO_BASE_URL: process.env.PIXGO_BASE_URL,
      },
    },
  ],
};
